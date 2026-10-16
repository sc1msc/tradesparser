# -*- coding: utf-8 -*-
r"""
Сервер сам собирает новые лоты с площадок (ЭТП), вместе с агрегатором
(решение владельца 16.10.2026). Разбор площадок - etp_lots.py в корне
репозитория (общий с ПК), почему так и как устроен номер лота - там же.

Что делает. Фоновый поток в процессе api (как status_refresh.py) в часы
RUN_HOURS по Москве проходит по площадкам из etp_lots.COLLECTORS:
  - читает список лотов площадки (Москва и область, торги объявлены или идёт
    приём заявок; только машины - etp_lots.is_vehicle);
  - лот, который уже есть в витрине от агрегатора (тот же адрес лота на ЭТП),
    не читает: ПК его всё равно не добавит, а статус ему проверяет
    status_refresh.py (16.10.2026 таких на ТоргГрупп было 316 из 504);
  - новый лот, или прочитанный больше REREAD_DAYS дней назад, - читает
    целиком (страница лота и страница торгов) и сохраняет в таблицу etp_lots;
  - остальным отмечает, что лот всё ещё в списке.
Проход в 06:00 - до прогона на ПК в 07:00: ПК забирает лоты одним запросом
(GET /api/etp-lots, main.pull_etp_lots) и дописывает в лист lots то, чего там
нет (повторы с агрегатором отсекает etp_lots.Dedup). В таблицу пишет только ПК.
Статус уже выгруженных лотов с площадок проверяет status_refresh.py (страница
лота на площадке вместо карточки агрегатора).

Сообщения администратору (HONESTLOT_ADMIN_CHAT_ID, бот @honestlot_bot), не
чаще раза в ALERT_REPEAT_HOURS на площадку:
  - список лотов площадки не читается (ошибка) или пуст - площадка закрыла
    доступ серверу или сменила адреса;
  - не прочиталась треть и больше страниц лотов - площадка сбоит;
  - у половины и больше прочитанных лотов нет названия, цены или срока -
    поменялась вёрстка, нужна правка etp_lots.py.
Состояние (что уже сообщали, итог прохода) - в STATE_FILE рядом с базой.

Выключить: HONESTLOT_ETP_COLLECT=0 в .env (так при локальном запуске,
miniapp/run_local.py). Один проход вручную, на сервере:
  docker compose exec api python -m app.etp_collect
"""
import datetime
import json
import os
import threading
import time

import etp_lots

from . import db, status_refresh

MSK = status_refresh.MSK
RUN_HOURS = (6, 14, 20)   # проходы по Москве; проверка статусов - в 5, 11, 16, 21
DELAY_SECONDS = 2.0       # пауза между запросами к площадке
REREAD_DAYS = 3           # прочитанный лот перечитывается целиком не чаще (цена, график, фото)
KEEP_DAYS = 30            # лот хранится столько дней после окончания приёма заявок
ALERT_REPEAT_HOURS = 24

_lock = threading.Lock()  # проход из потока и вручную не идут одновременно


def enabled():
    return os.environ.get("HONESTLOT_ETP_COLLECT", "1") != "0"


def state_file():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "etp_collect_state.json")


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


def _stamp():
    # Москва без пояса - как пишет ПК и status_refresh
    return datetime.datetime.now(MSK).replace(tzinfo=None).isoformat(timespec="seconds")


def _stale(read_at, now):
    try:
        read = datetime.datetime.fromisoformat(read_at).replace(tzinfo=MSK)
    except (TypeError, ValueError):
        return True
    return now - read >= datetime.timedelta(days=REREAD_DAYS)


def _complete(lot):
    return bool(lot.get("title") and lot.get("price_start") and lot.get("applications_end"))


def collect(collector, now, get, sleep):
    """Один проход по площадке -> сводка (dict)."""
    st = {"listed": 0, "new": 0, "reread": 0, "kept": 0, "in_feed": 0, "fail": 0, "bad": 0, "not_car": 0,
          "error": "", "list_error": ""}
    try:
        stubs = collector.list_lots(get, sleep=lambda: sleep(DELAY_SECONDS))
    except Exception as e:  # сеть, 4xx/5xx
        st["list_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return st
    st["listed"] = len(stubs)
    known = db.etp_known(collector.host)
    in_feed = {etp_lots.listing_key(u) for u in db.lot_etp_urls()}
    for stub in stubs:
        read_at = known.get(stub["key"])
        if not read_at and stub["key"] in in_feed:
            st["in_feed"] += 1
            continue
        if read_at and not _stale(read_at, now):
            db.etp_touch(stub["key"], stub["list_status"], _stamp())
            st["kept"] += 1
            continue
        try:
            lot = collector.read_lot(get, stub["url"])
        except Exception as e:
            st["fail"] += 1
            st["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            sleep(DELAY_SECONDS)
            continue
        sleep(DELAY_SECONDS * 2)  # страница лота и страница торгов
        if lot.get("parse_error") or not lot.get("lot_id") or not _complete(lot):
            st["bad"] += 1
            st["error"] = lot.get("parse_error") or "нет названия, цены или срока приёма заявок"
            continue
        if not etp_lots.is_vehicle(lot["title"], lot.get("description")):
            st["not_car"] += 1
            continue
        if lot.get("region") not in etp_lots.REGIONS.values():
            lot["region"] = stub.get("region") or lot.get("region")
        db.etp_save(stub["key"], lot, collector.host, stub["list_status"], _stamp())
        st["reread" if read_at else "new"] += 1
    return st


def run_pass(now=None, get=status_refresh.fetch, sleep=time.sleep, send=None):
    """Один проход по всем площадкам. -> {host: сводка}. get/sleep/send подменяются в проверках."""
    now = now or datetime.datetime.now(MSK)
    with _lock:
        stats = {c.host: collect(c, now, get, sleep) for c in etp_lots.COLLECTORS}
        cutoff = (now - datetime.timedelta(days=KEEP_DAYS)).strftime(etp_lots.DATE_FORMAT)
        pruned = db.etp_prune(cutoff)
        _report(stats, now, send)
    print(f"[лоты с ЭТП] проход {now:%d.%m %H:%M}: " + "; ".join(
        f"{h}: в списке {s['listed']}, уже в витрине {s['in_feed']}, новых {s['new']}, перечитано {s['reread']}, "
        f"сбоев {s['fail'] + s['bad']}"
        + (f", список не прочитался ({s['list_error']})" if s["list_error"] else "") for h, s in stats.items())
        + (f"; удалено старых {pruned}" if pruned else ""), flush=True)
    return stats


def _report(stats, now, send=None):
    state = load_state()
    for h, s in stats.items():
        if s["list_error"] or not s["listed"]:
            why = f"ошибка: {s['list_error']}" if s["list_error"] else "список пуст"
            status_refresh._alert(state, f"etp_list:{h}", f"HonestLot, сбор лотов с площадок: не читается список "
                                  f"лотов на {h} ({why}). Площадка закрыла доступ серверу или сменила адреса; "
                                  f"новые лоты с неё пока только через агрегатор. Разбор - etp_lots.py.",
                                  now, repeat_hours=ALERT_REPEAT_HOURS, send=send)
            continue
        attempts = s["new"] + s["reread"] + s["fail"] + s["bad"] + s["not_car"]
        if attempts >= 5 and s["fail"] * 3 >= attempts:
            status_refresh._alert(state, f"etp_read:{h}", f"HonestLot, сбор лотов с площадок: на {h} не открылись "
                                  f"{s['fail']} из {attempts} страниц лотов ({s['error']}). Площадка сбоит.",
                                  now, repeat_hours=ALERT_REPEAT_HOURS, send=send)
        elif attempts >= 5 and s["bad"] * 2 >= attempts:
            status_refresh._alert(state, f"etp_parse:{h}", f"HonestLot, сбор лотов с площадок: на {h} у {s['bad']} "
                                  f"из {attempts} лотов не разобрались название, цена или срок ({s['error']}) - "
                                  f"поменялась вёрстка, нужна правка etp_lots.py.",
                                  now, repeat_hours=ALERT_REPEAT_HOURS, send=send)
    state["last_pass"] = {"at": now.isoformat(timespec="seconds"),
                          **{h: {k: v for k, v in s.items() if k not in ("error",)} for h, s in stats.items()}}
    save_state(state)


def export(now=None):
    """Для ПК (GET /api/etp-lots): лоты с площадок, приём заявок по которым ещё идёт
    (или кончился не больше суток назад - ПК сам отбросит закончившиеся)."""
    now = now or datetime.datetime.now(MSK)
    since = (now - datetime.timedelta(days=1)).strftime(etp_lots.DATE_FORMAT)
    return db.etp_rows(since)


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
            print(f"[лоты с ЭТП] проход упал: {type(e).__name__}: {e}", flush=True)


def start():
    if enabled():
        threading.Thread(target=_loop, name="etp-collect", daemon=True).start()


if __name__ == "__main__":
    for host, s in run_pass().items():
        print(host, s)
