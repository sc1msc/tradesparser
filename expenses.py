# -*- coding: utf-8 -*-
r"""
Учёт расходов проекта - на ПК, отдельно от Google-таблицы с лотами.

  expenses/ledger.csv  - журнал, строка на трату. Открывается в Excel
                         (разделитель ";" и десятичная запятая - под русский
                         Excel). Можно дописывать руками: дата;сервис;что;
                         сколько;цена;сумма;баланс;вид;примечание.
  expenses/report.html - сводка в браузере: траты по месяцам и сервисам,
                         баланс TRONK и на сколько дней его хватит, последние
                         записи. Пересобирается в конце run_pipeline.py;
                         вручную - python expenses.py.

Что пишется само:
  - TRONK: после платного шага (fill_missing_mileage.py, evaluate_tronk.py)
    одна строка: сколько запросов, цена, баланс до и после. Сумма - РАЗНИЦА
    БАЛАНСА (реальное списание, бесплатный метод profile); если баланс
    узнать не удалось - расчёт "запросы x цена" (в примечании "расчёт");
  - TRONK, вид "баланс": снимок баланса в начале каждого прогона - из них
    видно пополнения и считается, на сколько дней хватит денег;
  - постоянные расходы (config.FIXED_MONTHLY_COSTS, например ВМ в Yandex
    Cloud по тарифу) - одна строка в месяц, при первом прогоне месяца.
    Настоящий счёт может отличаться - поправьте сумму в ledger.csv.

Ошибки учёта никогда не роняют пайплайн: учёт - вспомогательный.
"""
import csv
import datetime
import html
import os
import sys

import requests

import config

DIR = "expenses"
LEDGER = os.path.join(DIR, "ledger.csv")
REPORT = os.path.join(DIR, "report.html")
COLUMNS = ["дата", "сервис", "что", "сколько", "цена", "сумма", "баланс", "вид", "примечание"]
PROFILE_URL = "https://data.tronk.info/profile.ashx"  # бесплатный (цена 0 в activeMethods)

KIND_SPEND = "трата"
KIND_FIXED = "постоянные"
KIND_BALANCE = "баланс"


# ---------- журнал ----------

def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _fmt(value):
    """Число для CSV: десятичная запятая (русский Excel), пусто для None."""
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")
    return str(value)


def load():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def record(service, item, amount, qty=None, price=None, balance=None, kind=KIND_SPEND, note="", when=None):
    os.makedirs(DIR, exist_ok=True)
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(COLUMNS)
        w.writerow([(when or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M"), service, item,
                    _fmt(qty), _fmt(price), _fmt(amount), _fmt(balance), kind, note])


# ---------- TRONK ----------

def tronk_profile():
    """result метода profile (баланс, цены методов) или None."""
    try:
        r = requests.get(PROFILE_URL, params={"key": config.TRONK_API_KEY}, timeout=25)
        r.raise_for_status()
        return r.json().get("result") or None
    except (requests.RequestException, ValueError):
        return None


def tronk_balance():
    p = tronk_profile()
    return _num(p.get("accountBalance")) if p else None


def tronk_price(method, default=None):
    """Цена метода по прайсу TRONK (profile.activeMethods), иначе default."""
    p = tronk_profile()
    price = _num(((p or {}).get("activeMethods") or {}).get(method))
    return price if price else default


def record_tronk(method, requests_count, balance_before, balance_after, price, script):
    """Строка о платном шаге TRONK. Ничего не пишет, если запросов не было."""
    try:
        if not requests_count:
            return
        if balance_before is not None and balance_after is not None and balance_before >= balance_after:
            amount, note = round(balance_before - balance_after, 2), script
        else:
            amount, note = round(requests_count * (price or 0), 2), f"{script}, расчёт: баланс не получен"
        record("TRONK", method, amount, qty=requests_count, price=price, balance=balance_after, note=note)
    except OSError as e:
        print(f"  Учёт расходов: не удалось записать ({e})")


# ---------- постоянные расходы и снимок баланса ----------

def ensure_fixed_costs(today=None):
    """Строка постоянного расхода на текущий месяц, если её ещё нет."""
    today = today or datetime.date.today()
    month = today.strftime("%Y-%m")
    rows = load()
    for item, amount in (getattr(config, "FIXED_MONTHLY_COSTS", {}) or {}).items():
        service, _, what = item.partition(": ")
        if any(r["вид"] == KIND_FIXED and r["что"] == (what or item) and r["примечание"] == month for r in rows):
            continue
        # дата - первое число месяца: строка относится к месяцу, а не ко дню прогона
        record(service if what else item, what or item, float(amount), kind=KIND_FIXED, note=month,
               when=datetime.datetime(today.year, today.month, 1))


def snapshot_tronk_balance():
    bal = tronk_balance()
    if bal is not None:
        record("TRONK", "баланс счёта", None, balance=bal, kind=KIND_BALANCE)
    return bal


# ---------- сводка ----------

def _rows():
    out = []
    for r in load():
        try:
            when = datetime.datetime.strptime(r["дата"][:16], "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                when = datetime.datetime.strptime(r["дата"][:10], "%Y-%m-%d")
            except ValueError:
                continue
        out.append({**r, "_when": when, "_amount": _num(r["сумма"]) or 0.0, "_balance": _num(r["баланс"])})
    return out


def _spends(rows):
    return [r for r in rows if r["вид"] != KIND_BALANCE]


def tronk_burn_per_day(rows, now=None, days=30):
    """Средний расход TRONK в день за последние days дней (не раньше первой записи)."""
    now = now or datetime.datetime.now()
    tronk = [r for r in _spends(rows) if r["сервис"] == "TRONK"]
    if not tronk:
        return 0.0
    since = now - datetime.timedelta(days=days)
    span = max(1.0, min(days, (now - min(r["_when"] for r in tronk)).total_seconds() / 86400))
    return sum(r["_amount"] for r in tronk if r["_when"] >= since) / span


def last_tronk_balance(rows):
    known = [(r["_when"], i, r["_balance"]) for i, r in enumerate(rows)
             if r["сервис"] == "TRONK" and r["_balance"] is not None]
    return max(known)[2] if known else None  # при равном времени - записанная позже


def _rub(x):
    return f"{x:,.0f}".replace(",", " ") + " ₽" if abs(x) >= 100 else f"{x:.2f}".replace(".", ",") + " ₽"


def summary_text(now=None):
    now = now or datetime.datetime.now()
    rows = _rows()
    spends = _spends(rows)
    today = sum(r["_amount"] for r in spends if r["_when"].date() == now.date() and r["вид"] == KIND_SPEND)
    month = sum(r["_amount"] for r in spends if r["_when"].strftime("%Y-%m") == now.strftime("%Y-%m"))
    lines = [f"Расходы: сегодня {_rub(today)}, за {now.strftime('%m.%Y')} {_rub(month)} (с постоянными)."]
    bal, burn = last_tronk_balance(rows), tronk_burn_per_day(rows, now)
    if bal is not None:
        left = f", хватит примерно на {bal / burn:.0f} дн. (в среднем {_rub(burn)} в день)" if burn > 0 else ""
        lines.append(f"Баланс TRONK: {_rub(bal)}{left}.")
        low_days = getattr(config, "TRONK_LOW_BALANCE_DAYS", 5)
        if burn > 0 and bal / burn < low_days:
            lines.append(f"!!! Баланса TRONK осталось меньше чем на {low_days} дн. - пополните, иначе пробег "
                         f"перестанет заполняться (лоты пометятся ошибками).")
    lines.append(f"Подробно: {os.path.abspath(REPORT)}")
    return "\n".join(lines)


def build_report(now=None):
    now = now or datetime.datetime.now()
    rows = _rows()
    spends = _spends(rows)
    months = sorted({r["_when"].strftime("%Y-%m") for r in spends}, reverse=True)[:12]
    services = sorted({r["сервис"] for r in spends})
    by = {}
    for r in spends:
        key = (r["_when"].strftime("%Y-%m"), r["сервис"])
        by[key] = by.get(key, 0.0) + r["_amount"]
    cur = now.strftime("%Y-%m")
    month_total = sum(v for (m, _), v in by.items() if m == cur)
    bal, burn = last_tronk_balance(rows), tronk_burn_per_day(rows, now)
    days_left = f"≈ {bal / burn:.0f} дн." if bal is not None and burn > 0 else "—"
    esc = html.escape

    def cell(v):
        return f"<td class=n>{_rub(v)}</td>" if v else "<td class='n dim'>—</td>"

    table = "".join(
        f"<tr><th>{m}</th>" + "".join(cell(by.get((m, s), 0.0)) for s in services)
        + f"<td class='n b'>{_rub(sum(by.get((m, s), 0.0) for s in services))}</td></tr>" for m in months)
    recent = "".join(
        f"<tr><td>{esc(r['дата'])}</td><td>{esc(r['сервис'])}</td><td>{esc(r['что'])}</td>"
        f"<td class=n>{esc(r['сколько'])}</td><td class=n>{_rub(r['_amount']) if r['вид'] != KIND_BALANCE else ''}</td>"
        f"<td class=n>{_rub(r['_balance']) if r['_balance'] is not None else ''}</td>"
        f"<td class=dim>{esc(r['вид'])}{(' · ' + esc(r['примечание'])) if r['примечание'] else ''}</td></tr>"
        for r in sorted(rows, key=lambda r: r["_when"], reverse=True)[:40])
    page = f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Расходы HonestLot</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#16181d;--hint:#6b7280;--line:#e5e7eb;--accent:#179a50;--warn:#b45309}}
@media (prefers-color-scheme: dark){{:root{{--bg:#0f1115;--card:#181b21;--text:#e8eaee;--hint:#8b919b;--line:#2a2e36;--accent:#2fbf6c;--warn:#e0a23a}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.sub,.dim{{color:var(--hint)}} .sub{{font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.card .k{{font-size:13px;color:var(--hint)}} .card .v{{font-size:24px;font-weight:600;margin-top:2px}}
.card.warn .v{{color:var(--warn)}}
.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
thead th{{font-size:12px;color:var(--hint);font-weight:600}} tr:last-child td,tr:last-child th{{border-bottom:0}}
.n{{text-align:right;font-variant-numeric:tabular-nums}} .b{{font-weight:600}}
</style></head><body><main>
<h1>Расходы HonestLot</h1>
<div class=sub>Обновлено {now.strftime('%d.%m.%Y %H:%M')} · журнал: {esc(os.path.abspath(LEDGER))}</div>
<div class=cards>
<div class=card><div class=k>За {now.strftime('%m.%Y')}</div><div class=v>{_rub(month_total)}</div></div>
<div class="card{' warn' if bal is not None and burn > 0 and bal / burn < getattr(config, 'TRONK_LOW_BALANCE_DAYS', 5) else ''}"><div class=k>Баланс TRONK</div><div class=v>{_rub(bal) if bal is not None else '—'}</div><div class=sub>хватит {days_left}</div></div>
<div class=card><div class=k>TRONK в среднем за день</div><div class=v>{_rub(burn)}</div><div class=sub>за последние 30 дней</div></div>
</div>
<h2>По месяцам</h2>
<div class=wrap><table><thead><tr><th>Месяц</th>{''.join(f'<th class=n>{esc(s)}</th>' for s in services)}<th class=n>Итого</th></tr></thead>
<tbody>{table or '<tr><td class=dim>Пока пусто</td></tr>'}</tbody></table></div>
<h2>Последние записи</h2>
<div class=wrap><table><thead><tr><th>Дата</th><th>Сервис</th><th>Что</th><th class=n>Сколько</th><th class=n>Сумма</th><th class=n>Баланс</th><th>Вид</th></tr></thead>
<tbody>{recent or '<tr><td class=dim>Пока пусто</td></tr>'}</tbody></table></div>
</main></body></html>"""
    os.makedirs(DIR, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(page)
    return REPORT


if __name__ == "__main__":
    if "--balance" in sys.argv:
        print(f"Баланс TRONK: {snapshot_tronk_balance()}")
    print(f"Сводка: {os.path.abspath(build_report())}")
    print(summary_text())
