# -*- coding: utf-8 -*-
r"""
Сервер сам собирает новые лоты с площадок (ЭТП), вместе с агрегатором
(решение владельца 16.10.2026). Разбор площадок - etp_lots.py в корне
репозитория (общий с ПК), почему так и как устроен номер лота - там же.

Что делает. Фоновый поток в процессе api (как status_refresh.py) в часы
RUN_HOURS по Москве проходит по площадкам из etp_lots.COLLECTORS:
  - читает список лотов площадки (Москва и область, торги объявлены или идёт
    приём заявок; только машины - etp_lots.is_vehicle, а у площадок с категорией
    «легковой» (МЭТС, ЦДТ, Lot-online; cars_only) - по категории самой площадки);
  - лот, который уже есть в витрине от агрегатора (тот же адрес лота на ЭТП),
    не читает: ПК его всё равно не добавит, а статус ему проверяет
    status_refresh.py (16.10.2026 таких на ТоргГрупп было 316 из 504, на
    МЭТС - 218 из 313, 19.10.2026 на ЦДТ - 197 из 355);
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

Фото (photo_pass, после сбора): лотам ленты от агрегатора, у которых есть ссылка на лот на
площадке из etp_lots.PHOTO_KIND, фото берутся прямо со страницы площадки (у агрегатора поверх
его водяной знак) - не больше PHOTO_MAX_PER_PASS страниц за проход, повтор раз в PHOTO_RECHECK_DAYS.
Мини-апп показывает их вместо фото агрегатора (lots.py). Добор вручную, без ограничения:
  docker compose exec api python -m app.etp_collect --photos

Выключить: HONESTLOT_ETP_COLLECT=0 в .env (так при локальном запуске,
miniapp/run_local.py). Один проход вручную, на сервере:
  docker compose exec api python -m app.etp_collect
"""
import datetime
import json
import os
import re
import threading
import time

import etp_lots

from . import db, docphotos, imgproxy, lots, status_refresh

MSK = status_refresh.MSK
RUN_HOURS = (6, 14, 20)   # проходы по Москве; проверка статусов - в 5, 11, 16, 21
DELAY_SECONDS = 2.0       # пауза между запросами к площадке
REREAD_DAYS = 3           # прочитанный лот перечитывается целиком не чаще (цена, график, фото)
KEEP_DAYS = 30            # лот хранится столько дней после окончания приёма заявок
ALERT_REPEAT_HOURS = 24
PHOTO_MAX_PER_PASS = 300  # страниц площадок за проход (по PHOTO_DELAY_SECONDS) - около 15 минут
PHOTO_DELAY_SECONDS = 3.0  # добор фото медленнее остального: 16.10.2026 МЭТС закрыла доступ во время добора
PHOTO_RECHECK_DAYS = 14   # фото лота перечитываются не чаще (фото у лота почти не меняются)

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


def _stale(read_at, now, days=REREAD_DAYS):
    try:
        read = datetime.datetime.fromisoformat(read_at).replace(tzinfo=MSK)
    except (TypeError, ValueError):
        return True
    return now - read >= datetime.timedelta(days=days)


def _complete(lot):
    return bool(lot.get("title") and lot.get("price_start") and lot.get("applications_end"))


def _feed_lots_by_key():
    """Ключ адреса на ЭТП (etp_lots.listing_key) -> номера лотов витрины с этим адресом."""
    out = {}
    for r in db.conn().execute("SELECT lot_id, etp_url FROM lots WHERE in_source = 1 AND etp_url IS NOT NULL "
                               "AND etp_url != ''"):
        out.setdefault(etp_lots.listing_key(r["etp_url"]), []).append(r["lot_id"])
    return out


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
    feed_lots = None
    for stub in stubs:
        read_at = known.get(stub["key"])
        if not read_at and stub["key"] in in_feed:
            st["in_feed"] += 1
            # Лот уже пришёл от агрегатора (с его водяным знаком или без фото): фото площадки, которые список
            # уже дал (Lot-online - карточка каталога), - ему, как фото со страницы (lots._photo_sets).
            if stub.get("photos"):
                if feed_lots is None:
                    feed_lots = _feed_lots_by_key()
                for lot_id in feed_lots.get(stub["key"], []):
                    db.save_live(lot_id, {"etp_photos": json.dumps(stub["photos"], ensure_ascii=False),
                                          "etp_photos_at": _stamp()})
                    st["feed_photos"] = st.get("feed_photos", 0) + 1
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
        if not getattr(collector, "cars_only", False) and not etp_lots.is_vehicle(lot["title"], lot.get("description")):
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


def photo_candidates(now):
    """Лоты ленты от агрегатора со ссылкой на площадку, где фото берём сами, ещё не проверенные
    (или проверенные давно), - сначала никогда не проверенные."""
    out = []
    for r in db.conn().execute("SELECT lot_id, etp_url, etp_photos_at, photos FROM lots WHERE in_source = 1 "
                               "AND etp_url IS NOT NULL AND etp_url != ''"):
        host = etp_lots.etp_status.host(r["etp_url"])
        if host not in etp_lots.REPLACE_PHOTO_HOSTS and host not in etp_lots.DOC_PHOTO_HOSTS:
            continue
        # лоты, собранные с площадок, - свои фото у них уже есть; кроме ЦДТ без фото (документы, docphotos)
        if etp_lots.is_etp_lot_id(r["lot_id"]) and not (host == CDT_HOST and (r["photos"] or "[]") == "[]"):
            continue
        if r["etp_photos_at"] and not _stale(r["etp_photos_at"], now, PHOTO_RECHECK_DAYS):
            continue
        out.append((r["etp_photos_at"] or "", r["lot_id"], r["etp_url"]))
    return [(lot_id, url) for _, lot_id, url in sorted(out)]


CDT_HOST = "torgi.cdtrf.ru"
_CDT_TRADE_RE = re.compile(r"/trades/(\d+)")


def _cdt_doc_photos(url):
    """ЦДТ: на странице торгов фото нет - из документов торгов («Фото ТС», docphotos.py); None - не вышло."""
    m = _CDT_TRADE_RE.search(url or "")
    if not m:
        return None
    try:
        return docphotos.cdt_photos(m.group(1)) or None
    except status_refresh.HostPaused:
        raise
    except Exception as e:
        print(f"[фото с площадок] ЦДТ {m.group(1)}: документы не разобрались ({type(e).__name__}: {str(e)[:100]})",
              flush=True)
        return None


def _doc_photos(url, html):
    """Фото, которые сервер сохраняет у себя (docphotos): ЦДТ - документы торгов, НИС - уменьшенные оригиналы со
    страницы, Центр реализации - PDF «ФОТО» в документах лота. None - не вышло или не наша площадка."""
    host = etp_lots.etp_status.host(url)
    try:
        if host == CDT_HOST:
            return _cdt_doc_photos(url)
        if host == "nistp.ru":
            urls = etp_lots.nis_image_urls(url, html)
            return docphotos.remote_photos(urls) or None if urls else None
        if host == "bankrupt.centerr.ru":
            return docphotos.attachment_photos(etp_lots.centerr_attachments(html)) or None
    except status_refresh.HostPaused:
        raise
    except Exception as e:
        print(f"[фото с площадок] {host}: фото не сохранились ({type(e).__name__}: {str(e)[:100]})", flush=True)
    return None


def photo_pass(now=None, get=status_refresh.fetch, sleep=time.sleep, limit=PHOTO_MAX_PER_PASS):
    """Фото со страниц площадок для лотов ленты -> etp_photos. -> сводка."""
    now = now or datetime.datetime.now(MSK)
    todo = photo_candidates(now)[:limit] if limit else photo_candidates(now)
    st = {"pages": len(todo), "with_photos": 0, "photos": 0, "empty": 0, "skipped": 0, "fail": 0}
    for lot_id, url in todo:
        try:
            html = get(url)
            photos = etp_lots.page_photos(url, html)
            if not photos:
                photos = _doc_photos(url, html)
        except status_refresh.HostPaused:  # площадка закрыла доступ - её лоты в следующий раз
            st["fail"] += 1
            continue
        except Exception:  # сеть, 403 - попробуем в следующий проход
            st["fail"] += 1
            sleep(PHOTO_DELAY_SECONDS)
            continue
        if photos is None:
            st["skipped"] += 1
            photos = []  # несколько лотов на странице - чьи фото, не понять; отмечаем, что смотрели
        st["with_photos" if photos else "empty"] += 1
        st["photos"] += len(photos)
        db.save_live(lot_id, {"etp_photos": json.dumps(photos, ensure_ascii=False), "etp_photos_at": _stamp()})
        sleep(PHOTO_DELAY_SECONDS)
    lots.invalidate()
    print(f"[фото с площадок] страниц {st['pages']}: с фото {st['with_photos']} ({st['photos']} фото), без фото "
          f"{st['empty']}, не разобрано {st['skipped']}, сбоев {st['fail']}", flush=True)
    return st


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
        try:
            photo_pass()
            imgproxy.cleanup()
        except Exception as e:
            print(f"[фото с площадок] проход упал: {type(e).__name__}: {e}", flush=True)


def start():
    if enabled():
        threading.Thread(target=_loop, name="etp-collect", daemon=True).start()


if __name__ == "__main__":
    import sys
    if "--photos" in sys.argv:  # только добор фото, без ограничения числа страниц
        print(photo_pass(limit=None))
    else:
        for host, s in run_pass().items():
            print(host, s)
