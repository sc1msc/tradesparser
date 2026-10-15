# -*- coding: utf-8 -*-
r"""
Сервер сам перепроверяет статус торгов: карточку агрегатора и страницу лота
на ЭТП (решение владельца 15.10.2026).

Зачем. Статус агрегатора отстаёт: публичное предложение заканчивается
досрочно, как только кто-то подал заявку, а агрегатор ещё дни пишет «Идёт
приём заявок» (лот 7190620: на ЦДТ торги завершены, протокол опубликован).
Раньше перепроверка публичных предложений шла раз в сутки на ПК (шаг 1,
около 650 карточек) и только через агрегатор.

Что делает. Фоновый поток в процессе api (как backup.py и watchdog.py) в
часы RUN_HOURS по Москве проходит по лотам:
  - открытые публичные предложения из ленты;
  - лоты из избранного, чей итог ещё не известен (как lots.watchlist).
У каждого читает карточку агрегатора (parse_lot.py - тот же разбор, что на
ПК): статус, цену, график, дедлайн и ссылку на ЭТП -> live_* в базе. Затем
страницу лота на ЭТП (etp_status.py) -> etp_*. Итог на ЭТП важнее статуса
агрегатора (lots._apply_live). В проход в FULL_HOUR (после ночного
обновления агрегатора около 04:00 и до прогона на ПК в 07:00) читаются все
карточки агрегатора; в остальные - только лоты на площадках, которые мы не
разбираем, а у остальных - ЭТП: так агрегатор получает не в 4 раза больше
запросов, чем раньше от ПК.

ПК забирает результат одним запросом (GET /api/lot-statuses, main.py) в шаге 1
прогона и пишет в лист lots - подборки и дайджест видят те же статусы, а свою
перепроверку ПК делает только для лотов, которые сервер не проверил.

Сообщения администратору (HONESTLOT_ADMIN_CHAT_ID, бот @honestlot_bot, как у
watchdog.py):
  - карточки агрегатора не читаются (треть и больше за проход) - раз в
    ALERT_REPEAT_HOURS;
  - разбор площадки перестал узнавать статус (половина и больше её лотов, или
    площадка отвечает ошибкой - например, закрыла доступ серверу) - раз в сутки
    на площадку;
  - раз в сутки (первый проход после REPORT_HOUR) - площадки, которые мы не
    разбираем, с числом лотов, если появилась новая или лотов заметно прибавилось:
    пора дописать разбор в etp_status.py.
Состояние (что уже сообщали) - в STATE_FILE рядом с базой.

Выключить: HONESTLOT_STATUS_REFRESH=0 в .env (так при локальном запуске,
miniapp/run_local.py).
"""
import datetime
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request


import etp_status
import parse_lot

from . import db, lots, watchdog

MSK = datetime.timezone(datetime.timedelta(hours=3))
RUN_HOURS = (5, 11, 16, 21)     # проходы по Москве
FULL_HOUR = 5                   # проход, в котором перечитываются все карточки агрегатора
REPORT_HOUR = 9                 # с какого часа можно слать суточный отчёт о площадках без разбора
DELAY_SECONDS = 2.0             # пауза между запросами (как у ПК)
FETCH_TIMEOUT = 30
ALERT_REPEAT_HOURS = 12
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"

_state_lock = threading.Lock()


def enabled():
    return os.environ.get("HONESTLOT_STATUS_REFRESH", "1") != "0"


def state_file():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "status_refresh_state.json")


def load_state():
    try:
        with open(state_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = state_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, state_file())


def fetch(url):
    """Страница как текст. HTTP-ошибка (403 - площадка не пускает) - urllib.error.HTTPError.
    Часть ЭТП подписана российским корневым сертификатом (Минцифры), которого нет в наборе
    сертификатов образа: для них повтор без проверки сертификата - страницу мы только читаем,
    ничего не отправляем."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"})
    try:
        return _read(urllib.request.urlopen(req, timeout=FETCH_TIMEOUT))
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    return _read(urllib.request.urlopen(req, timeout=FETCH_TIMEOUT, context=ssl._create_unverified_context()))


def _read(resp):
    with resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset()
    for enc in (charset, "utf-8", "cp1251"):
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def candidates(now):
    """Лоты для проверки: открытые публичные предложения ленты и лоты избранного без итога."""
    favs = lots.Favs(db.all_favorite_rows())
    out = []
    for lot in lots.load():
        if not lot.get("url") or lot["_closed_status"]:
            continue
        state = lots.current_state(lot, now)
        is_offer = lot["trade"] == lots.TRADE_PUBLIC_OFFER and bool(lot.get("in_source"))
        open_now = state["deadline"] is not None and state["deadline"] > now
        if is_offer and (open_now or lot.get("_etp_pending")):
            out.append(lot)
            continue
        if favs.has(lot) and lots.outcome(lot, state, now) not in lots.FINAL_OUTCOMES:
            end = lot["_final_deadline"] or state["deadline"]
            if end is None or now - end <= datetime.timedelta(days=lots.WATCH_DAYS):
                out.append(lot)
    return out


def _alert(state, key, text, now, repeat_hours=ALERT_REPEAT_HOURS, send=None):
    """Сообщение администратору не чаще раза в repeat_hours по ключу. -> отправлено ли."""
    chat_id = watchdog.admin_chat_id()
    if not chat_id:
        print(f"[статусы] (нет HONESTLOT_ADMIN_CHAT_ID) {text}", flush=True)
        return False
    last = (state.setdefault("alerts", {})).get(key)
    if last:
        try:
            if now - datetime.datetime.fromisoformat(last) < datetime.timedelta(hours=repeat_hours):
                return False
        except ValueError:
            pass
    try:
        (send or watchdog._send)(chat_id, text)
    except Exception as e:  # релей/Telegram недоступен - попробуем в следующий проход
        print(f"[статусы] не отправилось сообщение: {e}", flush=True)
        return False
    state["alerts"][key] = now.isoformat(timespec="seconds")
    return True


def run_pass(now=None, full=None, get=fetch, sleep=time.sleep, send=None):
    """Один проход. -> сводка (dict). get/sleep/send подменяются в проверках."""
    now = now or datetime.datetime.now(MSK)
    full = (now.hour == FULL_HOUR) if full is None else full
    todo = candidates(now)
    stats = {"lots": len(todo), "agg_ok": 0, "agg_fail": 0, "agg_error": "", "etp": {}, "unsupported": {},
             "off_etp": 0, "closed": 0, "pending": 0}
    for lot in todo:
        # Москва без пояса - как пишет ПК (main._status_is_fresh сравнивает с наивным временем)
        stamp = datetime.datetime.now(MSK).replace(tzinfo=None).isoformat(timespec="seconds")
        etp_url = lot.get("etp_url")
        engine = etp_status.engine(etp_url) if etp_url else None
        live = {}
        if full or not engine:
            try:
                data = parse_lot.parse_lot_html(get(lot["url"]), url=lot["url"])
                if data.get("lot_id") is None:
                    raise ValueError("в карточке не нашёлся JSON лота")
            except Exception as e:  # сеть, 4xx/5xx, вёрстка
                stats["agg_fail"] += 1
                stats["agg_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            else:
                stats["agg_ok"] += 1
                live = {"live_status": data.get("status"), "live_price": _int(data.get("price_current")),
                        "live_periods": data.get("bidding_periods") or None,
                        "live_end": data.get("applications_end") or None, "live_checked_at": stamp}
                etp_url = data.get("etp_url") or etp_url
                engine = etp_status.engine(etp_url) if etp_url else None
                if etp_url:
                    live["etp_url"] = etp_url
            sleep(DELAY_SECONDS)
        if not etp_url:
            stats["off_etp"] += 1
        elif not engine:
            h = etp_status.host(etp_url)
            stats["unsupported"][h] = stats["unsupported"].get(h, 0) + 1
        else:
            h = etp_status.host(etp_url)
            st = stats["etp"].setdefault(h, {"ok": 0, "unknown": 0, "error": ""})
            try:
                res = etp_status.parse(etp_url, get(etp_url), {"vin": lot.get("vin"), "plate": lot.get("plate")})
            except urllib.error.HTTPError as e:
                res = etp_status.UNKNOWN
                st["error"] = f"HTTP {e.code}"
            except Exception as e:
                res = etp_status.UNKNOWN
                st["error"] = f"{type(e).__name__}: {str(e)[:100]}"
            if res.state == "unknown":
                st["unknown"] += 1
            else:
                st["ok"] += 1
                live.update({"etp_state": res.state, "etp_text": res.text, "etp_outcome": res.outcome,
                             "etp_checked_at": stamp})
                stats["closed"] += res.state == "closed"
                stats["pending"] += res.state == "pending"
            sleep(DELAY_SECONDS)
        db.save_live(lot["lot_id"], live)
    lots.invalidate()
    _report(stats, now, send)
    return stats


def _int(value):
    try:
        return int(round(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        return None


def _report(stats, now, send=None):
    with _state_lock:
        state = load_state()
        attempts = stats["agg_ok"] + stats["agg_fail"]
        if attempts >= 10 and stats["agg_fail"] * 3 >= attempts:
            _alert(state, "aggregator", f"HonestLot, проверка статусов на сервере: не прочитались {stats['agg_fail']} из "
                   f"{attempts} карточек агрегатора (последняя ошибка: {stats['agg_error']}). Агрегатор сбоит или "
                   f"закрыл доступ серверу; статусы в мини-аппе пока по выгрузке с ПК.", now, send=send)
        for h, st in stats["etp"].items():
            total = st["ok"] + st["unknown"]
            if total >= 5 and st["unknown"] * 2 >= total:
                why = f"площадка отвечает ошибкой ({st['error']})" if st["error"] else "поменялась вёрстка страницы"
                _alert(state, f"etp:{h}", f"HonestLot, проверка статусов на ЭТП: на {h} статус не распознан у "
                       f"{st['unknown']} из {total} лотов - {why}. Для этих лотов пока статус агрегатора; "
                       f"нужна правка etp_status.py.", now, repeat_hours=24, send=send)
        # суточный отчёт о площадках без разбора: новая площадка или лотов стало заметно больше
        if now.hour >= REPORT_HOUR and state.get("report_date") != now.date().isoformat() and stats["unsupported"]:
            reported = state.get("unsupported", {})
            grew = [h for h, n in stats["unsupported"].items()
                    if h not in reported or n >= max(reported[h] + 5, reported[h] * 1.5)]
            if grew:
                lines = "\n".join(f"- {h}: {n}" + (" (новая)" if h not in reported else "")
                                  for h, n in sorted(stats["unsupported"].items(), key=lambda x: -x[1]))
                if _alert(state, "unsupported", "HonestLot: лоты на площадках, где статус торгов мы пока не "
                          f"разбираем (берём статус агрегатора):\n{lines}\n\nТоргов вне ЭТП: {stats['off_etp']}. "
                          "Разбор новой площадки - в etp_status.py.", now, repeat_hours=20, send=send):
                    state["unsupported"] = dict(stats["unsupported"])
            state["report_date"] = now.date().isoformat()
        state["last_pass"] = {"at": now.isoformat(timespec="seconds"), **{k: stats[k] for k in
                              ("lots", "agg_ok", "agg_fail", "off_etp", "closed", "pending")},
                              "unsupported": stats["unsupported"],
                              "etp": {h: {"ok": v["ok"], "unknown": v["unknown"]} for h, v in stats["etp"].items()}}
        save_state(state)
    print(f"[статусы] проход {now:%d.%m %H:%M}: лотов {stats['lots']}, агрегатор {stats['agg_ok']}/"
          f"{stats['agg_ok'] + stats['agg_fail']}, на ЭТП закрыто {stats['closed']}, итоги подводятся "
          f"{stats['pending']}, площадок без разбора {len(stats['unsupported'])}", flush=True)


def statuses(now=None):
    """Для ПК (GET /api/lot-statuses): что сервер узнал о лотах за последние LIVE_MAX_AGE_HOURS.
    status - итог ЭТП, если он есть, иначе статус агрегатора; etp_status - что написано на ЭТП."""
    now = now or datetime.datetime.now(MSK)
    out = []
    for r in db.conn().execute("SELECT lot_id, live_status, live_price, live_periods, live_end, live_checked_at, "
                               "etp_url, etp_state, etp_text, etp_outcome, etp_checked_at FROM lots "
                               "WHERE live_checked_at IS NOT NULL OR etp_checked_at IS NOT NULL"):
        live_fresh = lots._fresh(r["live_checked_at"], now)
        etp_fresh = lots._fresh(r["etp_checked_at"], now)
        if not (live_fresh or etp_fresh):
            continue
        status = r["live_status"] if live_fresh else None
        if etp_fresh and r["etp_state"] == "closed" and r["etp_outcome"] in etp_status.OUTCOME_TEXT:
            status = etp_status.OUTCOME_TEXT[r["etp_outcome"]]
        item = {"lot_id": r["lot_id"], "status": status, "etp_url": r["etp_url"]}
        if live_fresh:
            item.update({"price_current": r["live_price"], "bidding_periods": r["live_periods"] or "",
                         "applications_end": r["live_end"], "status_checked_at": r["live_checked_at"]})
        if etp_fresh:
            item.update({"etp_status": r["etp_text"], "etp_checked_at": r["etp_checked_at"]})
        out.append(item)
    return out


def _next_run(now):
    for add_days in (0, 1):
        day = (now + datetime.timedelta(days=add_days)).date()
        for hour in RUN_HOURS:
            at = datetime.datetime(day.year, day.month, day.day, hour, 0, tzinfo=MSK)
            if at > now:
                return at
    return now + datetime.timedelta(hours=6)


def _loop():
    while True:
        now = datetime.datetime.now(MSK)
        time.sleep(max(1.0, (_next_run(now) - now).total_seconds()))
        try:
            run_pass()
        except Exception as e:  # поток не должен умирать из-за одного прохода
            print(f"[статусы] проход упал: {type(e).__name__}: {e}", flush=True)


def start():
    if enabled():
        threading.Thread(target=_loop, name="status-refresh", daemon=True).start()
