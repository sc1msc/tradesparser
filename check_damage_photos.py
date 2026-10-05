# -*- coding: utf-8 -*-
r"""
Проверка фото подозрительно дешёвых лотов через Claude: нет ли на фото
тотальных повреждений (сгорела, сильно смята, нарушена геометрия кузова,
нет колёс, разобрана).

Зачем. Сортировка "Выгоднее" в мини-аппе поднимает наверх лоты с огромным
дисконтом к оценке Авто.ру, а Авто.ру оценивает ИСПРАВНУЮ машину того же
года. Ключевые слова (lot_metrics.DAMAGE_KEYWORDS) ловят только то, что
написано в названии; BAIC X35 2023 за 87 тыс. (-91%) в описании выглядит
нормально, а на фото - сгоревший кузов. Смотреть фото всех ~1500 лотов
дорого и незачем: проверяем только лоты, где цена ниже середины рынка хотя
бы на config.DAMAGE_CHECK_MIN_GAP процентов (40% на 06.10.2026 - около 130
лотов, ~10% среза). Разовая разметка, дальше - только новые такие лоты.

Вердикт модели:
  total     - по фото ОДНОЗНАЧНО видны тотальные повреждения (см. PROMPT);
  not_total - машина видна, тотальных повреждений нет (мелкие - не в счёт);
  unclear   - по фото нельзя сказать (фото не машины, видно плохо, сомнения).
Битыми считаются только total: "нельзя однозначно сказать" - не битый
(решение пользователя 06.10.2026).

Результаты - в DAMAGE_CACHE_FILE (по lot_id, вместе со списком фото: если
фото у лота поменялись - проверяем заново). Страница для просмотра глазами
(фото + вердикт) - REPORT_FILE. В мини-апп результат пока не уходит.

Деньги: Claude API платный; перед запуском - оценка стоимости и
подтверждение (yes/да), лимит лотов за запуск config.DAMAGE_CHECK_MAX_PER_RUN.
Потраченное пишется в учёт расходов (expenses.py). Ключ - ANTHROPIC_API_KEY
в local_secrets.py или в переменной окружения.

Фото берутся из кэша карточек мини-аппа (miniapp_details_cache.json, его
заполняет export_to_miniapp.py), уменьшаются до PHOTO_MAX_SIDE по длинной
стороне (дешевле, для тотальных повреждений хватает) и уходят в запрос.

Запуск:
  python check_damage_photos.py            - проверить новые подходящие лоты
  python check_damage_photos.py --dry-run  - без API: какие лоты и фото пойдут,
                                             оценка стоимости, страница REPORT_FILE
  python check_damage_photos.py --report   - только пересобрать REPORT_FILE
"""
import base64
import datetime
import html
import io
import json
import os
import re
import sys
import time

import gspread
import requests
from google.oauth2.service_account import Credentials

import config
import expenses
import lot_metrics

SOURCE_SHEET = "lots_current_month"
DETAILS_CACHE_FILE = "miniapp_details_cache.json"
DAMAGE_CACHE_FILE = "damage_check_cache.json"
REPORT_FILE = "damage_check_report.html"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
LOT_ID_RE = re.compile(r"/lot/(\d+)")
PHOTO_MAX_SIDE = 1024
# Для оценки стоимости до запуска: картинка 1024x768 - около 1050 токенов,
# инструкция - около 900, ответ с размышлением на effort=low - до ~800.
EST_TOKENS_PER_PHOTO = 1100
EST_PROMPT_TOKENS = 900
EST_OUTPUT_TOKENS = 800

VERDICTS = ("total", "not_total", "unclear")

PROMPT = """Ты смотришь фотографии легкового автомобиля, который продаётся на торгах по банкротству. \
Цена лота намного ниже рыночной, и нужно понять: не объясняется ли это тем, что машина тотально повреждена.

Ответь verdict = "total" ТОЛЬКО если на фото однозначно видно хотя бы одно:
- машина горела: обгоревший кузов, салон или моторный отсек;
- сильная деформация кузова, нарушена геометрия: смят перед, зад или бок вместе со стойками, \
лонжеронами или крышей, кузов перекошен; машина после тяжёлого ДТП;
- нет колёс, машина стоит на подставках или кирпичах;
- машина разобрана или разукомплектована: нет двигателя, дверей, капота, сидений, большей части деталей;
- следы затопления по крышу или по окна.

verdict = "not_total", если машина видна и таких признаков нет. Царапины, вмятины, сколы, ржавчина, \
разбитое стекло или фара, оторванный бампер, мятое крыло или дверь, спущенное колесо, грязь, \
грязный салон - это НЕ тотальные повреждения.

verdict = "unclear", если по фото сказать нельзя: на фото не машина (документы, ключи, логотип или баннер площадки), \
машина видна плохо или частично, фото слишком мелкие или тёмные, либо признаки есть, но ты не уверен. \
Если сомневаешься между "total" и чем-то другим - выбирай не "total".

signs - короткие названия признаков, которые ты действительно видишь на фото (по-русски, например \
"обгоревший кузов", "смят передок со стойкой", "нет колёс"); для not_total и unclear можно пусто. \
comment - одно-два предложения по-русски: что видно на фото."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "signs": {"type": "array", "items": {"type": "string"}},
        "comment": {"type": "string"},
    },
    "required": ["verdict", "signs", "comment"],
    "additionalProperties": False,
}


# ---------- данные ----------

def _num(value):
    try:
        return float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_sheet():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    ws = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID).worksheet(SOURCE_SHEET)
    values = ws.get_all_values()
    header = values[0] if values else []
    return [dict(zip(header, row)) for row in values[1:]]


def pick_photos(photos, n):
    """n фото по всей галерее (первое, последнее и равномерно между ними):
    повреждения часто не на первом кадре."""
    if len(photos) <= n:
        return list(photos)
    step = (len(photos) - 1) / (n - 1)
    return [photos[round(i * step)] for i in range(n)]


def candidates(rows, details, min_gap):
    """Лоты "одна машина" с оценкой Авто.ру и дисконтом не меньше min_gap%."""
    out = []
    for r in rows:
        if (r.get("lot_kind") or lot_metrics.LOT_CAR) != lot_metrics.LOT_CAR:
            continue
        m = LOT_ID_RE.search(r.get("url") or "")
        if not m:
            continue
        gap = lot_metrics.gap_percent(_num(r.get("price_current")), _num(r.get("autoru_price_low")),
                                      _num(r.get("autoru_price_high")))
        if gap is None or gap < min_gap:
            continue
        d = details.get(m.group(1)) or {}
        gallery = [p for p in d.get("photos") or [] if p.get("full")]
        if not gallery and r.get("photo_url"):
            gallery = [{"full": r["photo_url"], "thumb": r["photo_url"]}]
        picked = pick_photos(gallery, config.DAMAGE_CHECK_PHOTOS)
        brand_model = " ".join(x for x in (r.get("brand"), r.get("name")) if x)
        out.append({
            "lot_id": m.group(1), "url": r["url"], "gap": round(gap, 1),
            "name": f"{brand_model or (r.get('title') or 'Лот')[:60]}{', ' + r['year'] if r.get('year') else ''}",
            "title": r.get("title") or "", "price": _num(r.get("price_current")),
            "trade": "public_offer" if (r.get("bidding_periods") or "").strip() else "auction",
            "photos": [p["full"] for p in picked],                      # уходят в проверку
            "thumbs": [p.get("thumb") or p["full"] for p in picked],   # для страницы - лёгкие превью
        })
    return sorted(out, key=lambda c: -c["gap"])


def is_checked(cache, c):
    """Проверен с теми же фото - повторно не платим."""
    entry = cache.get(c["lot_id"])
    return bool(entry) and entry.get("verdict") in VERDICTS and entry.get("photos") == c["photos"]


def estimate_usd(lots):
    price = config.DAMAGE_CHECK_PRICE_USD
    tokens_in = sum(EST_PROMPT_TOKENS + EST_TOKENS_PER_PHOTO * len(c["photos"]) for c in lots)
    tokens_out = EST_OUTPUT_TOKENS * len(lots)
    return (tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000


# ---------- запрос к Claude ----------

def _image_block(url, session):
    from PIL import Image  # только для настоящего прогона

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def check_lot(client, c, session):
    """-> (запись для кэша, usage). Фото, которые не скачались, пропускаются."""
    images = []
    for url in c["photos"]:
        try:
            images.append(_image_block(url, session))
        except Exception as e:
            print(f"    фото не скачалось: {url} ({e})")
    if not images:
        return {"verdict": "unclear", "signs": [], "comment": "Фото не скачались.", "photos": c["photos"]}, None
    response = client.beta.messages.create(
        model=config.DAMAGE_CHECK_MODEL,
        max_tokens=4000,
        # при отказе фильтров безопасности API сам повторит запрос на запасной модели
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=PROMPT,
        messages=[{"role": "user", "content": images + [
            {"type": "text", "text": f"Лот: {c['title'][:300]}\nФото: {len(images)}."}]}],
    )
    if response.stop_reason == "refusal":
        result = {"verdict": "unclear", "signs": [], "comment": "Модель отказалась отвечать."}
    else:
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = {"verdict": "unclear", "signs": [], "comment": f"Не разобрал ответ: {text[:150]}"}
    result.update(photos=c["photos"], model=response.model,
                  checked_at=datetime.datetime.now().isoformat(timespec="seconds"))
    return result, response.usage


# ---------- страница для просмотра ----------

BADGE = {"total": ("Тотальные повреждения", "#c0392b"), "not_total": ("Не тотальные", "#179a50"),
         "unclear": ("Нельзя сказать", "#8b919b"), None: ("Не проверен", "#8b919b")}


def build_report(lots, cache):
    order = {"total": 0, "unclear": 1, "not_total": 2, None: 3}
    lots = sorted(lots, key=lambda c: (order[(cache.get(c["lot_id"]) or {}).get("verdict")], -c["gap"]))
    counts = {}
    for c in lots:
        v = (cache.get(c["lot_id"]) or {}).get("verdict")
        counts[v] = counts.get(v, 0) + 1
    esc = html.escape
    cards = []
    for c in lots:
        e = cache.get(c["lot_id"]) or {}
        label, color = BADGE[e.get("verdict")]
        imgs = "".join(f"<a href='{esc(u)}' target=_blank><img src='{esc(t)}' loading=lazy></a>"
                       for u, t in zip(c["photos"], c["thumbs"]))
        price = f"{c['price']:,.0f}".replace(",", " ") + " ₽" if c["price"] else "—"
        cards.append(
            f"<div class=card><div class=photos>{imgs or '<div class=nophoto>нет фото</div>'}</div>"
            f"<div class=info><div class=top><b>{esc(c['name'])}</b>"
            f"<span class=badge style='background:{color}'>{label}</span></div>"
            f"<div class=sub>{'старт ' if c['trade'] == 'auction' else ''}{price} · ниже рынка на {c['gap']:.0f}% · "
            f"<a href='{esc(c['url'])}' target=_blank>лот {c['lot_id']}</a></div>"
            + (f"<div class=signs>{esc(', '.join(e.get('signs') or []))}</div>" if e.get("signs") else "")
            + (f"<div class=comment>{esc(e.get('comment', ''))}</div>" if e.get("comment") else "")
            + "</div></div>")
    summary = " · ".join(f"{BADGE[v][0]}: {n}" for v, n in sorted(counts.items(), key=lambda kv: order[kv[0]]))
    page = f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Проверка фото</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#16181d;--hint:#6b7280;--line:#e5e7eb}}
@media (prefers-color-scheme: dark){{:root{{--bg:#0f1115;--card:#181b21;--text:#e8eaee;--hint:#8b919b;--line:#2a2e36}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}} h1{{font-size:22px;margin:0 0 4px}}
.sub,.hint{{color:var(--hint);font-size:13px}} a{{color:inherit}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:12px;overflow:hidden}}
.photos{{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;background:var(--line)}}
.photos img{{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}} .nophoto{{padding:24px;color:var(--hint)}}
.info{{padding:10px 14px 12px}} .top{{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}}
.badge{{color:#fff;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;white-space:nowrap}}
.signs{{margin-top:4px;font-weight:600;font-size:14px}} .comment{{margin-top:4px;font-size:14px}}
@media (max-width:600px){{.photos{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<h1>Проверка фото: подозрительно дешёвые лоты</h1>
<div class=hint>Лоты ниже рынка на {config.DAMAGE_CHECK_MIN_GAP}% и больше: {len(lots)} · {summary} ·
модель {esc(config.DAMAGE_CHECK_MODEL)} · обновлено {datetime.datetime.now():%d.%m.%Y %H:%M}</div>
{''.join(cards)}
</main></body></html>"""
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(page)
    return os.path.abspath(REPORT_FILE)


# ---------- запуск ----------

def run(dry_run=False, report_only=False):
    print(f"Читаю лист {SOURCE_SHEET}...")
    rows = read_sheet()
    details = _load_json(DETAILS_CACHE_FILE)
    cache = _load_json(DAMAGE_CACHE_FILE)
    lots = candidates(rows, details, config.DAMAGE_CHECK_MIN_GAP)
    todo = [c for c in lots if c["photos"] and not is_checked(cache, c)]
    no_photos = sum(1 for c in lots if not c["photos"])
    print(f"Лотов ниже рынка на {config.DAMAGE_CHECK_MIN_GAP}%+: {len(lots)} "
          f"(без фото: {no_photos}, уже проверены: {len(lots) - len(todo) - no_photos}, к проверке: {len(todo)})")
    if report_only or not todo:
        print(f"Страница: {build_report(lots, cache)}")
        return

    to_process = todo[: config.DAMAGE_CHECK_MAX_PER_RUN]
    usd = estimate_usd(to_process)
    print(f"Будет проверено сейчас: {len(to_process)} лотов, {sum(len(c['photos']) for c in to_process)} фото, "
          f"модель {config.DAMAGE_CHECK_MODEL}")
    print(f"Оценка стоимости: ~${usd:.2f} (~{usd * config.USD_RUB:.0f} руб.)")
    if len(todo) > len(to_process):
        print(f"Ещё {len(todo) - len(to_process)} лотов - в следующий запуск (лимит DAMAGE_CHECK_MAX_PER_RUN).")
    if dry_run:
        print(f"--dry-run: запросов к Claude не было. Страница с фото, которые уйдут в проверку: {build_report(lots, cache)}")
        return

    answer = input(f"\nПодтвердите проверку {len(to_process)} лотов через Claude API (платно) (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, запросов не было.")
        return

    import anthropic  # только для настоящего прогона

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else anthropic.Anthropic()
    session = requests.Session()
    tokens_in = tokens_out = checked = 0
    try:
        for i, c in enumerate(to_process, start=1):
            print(f"[{i}/{len(to_process)}] {c['lot_id']} {c['name']} (-{c['gap']:.0f}%, фото {len(c['photos'])})")
            try:
                result, usage = check_lot(client, c, session)
            except anthropic.AuthenticationError:
                print("  Ключ Claude API не подошёл - впишите ANTHROPIC_API_KEY в local_secrets.py. Останавливаюсь.")
                break
            except anthropic.PermissionDeniedError as e:
                print(f"  Доступ запрещён ({e.message}) - возможно, API недоступен из этой сети. Останавливаюсь.")
                break
            except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                print(f"  Ошибка API, лот пропущен (проверится в следующий раз): {e}")
                continue
            if usage is not None:
                tokens_in += usage.input_tokens
                tokens_out += usage.output_tokens
                checked += 1
            cache[c["lot_id"]] = result
            _save_json(DAMAGE_CACHE_FILE, cache)  # после каждого лота - прерванный прогон не теряет оплаченное
            print(f"  -> {result['verdict']}: {', '.join(result.get('signs') or []) or result.get('comment', '')[:80]}")
            time.sleep(0.3)
    finally:
        price = config.DAMAGE_CHECK_PRICE_USD
        spent = (tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000
        if checked:
            try:
                expenses.record("Claude API", "проверка фото лотов", round(spent * config.USD_RUB, 2), qty=checked,
                                note=f"${spent:.2f}, {tokens_in} вх. / {tokens_out} вых. токенов, {config.DAMAGE_CHECK_MODEL}")
            except OSError as e:
                print(f"Учёт расходов: не удалось записать ({e})")
        print(f"\nПроверено: {checked}, потрачено ~${spent:.2f} (~{spent * config.USD_RUB:.0f} руб.)")
        print(f"Страница: {build_report(lots, cache)}")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv, report_only="--report" in sys.argv)
