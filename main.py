# -*- coding: utf-8 -*-
"""
Главный скрипт бота:
  1) обходит страницы поиска (parse_search.py)
  2) для каждого нового лота открывает карточку и парсит детали (parse_lot.py)
  3) пишет всё в Google Таблицу (sheets_writer.py)
  4) перечитывает карточки идущих публичных предложений и обновляет их
     статус и график снижения цены (refresh_public_offers, см. ниже)

Новый лот, у которого приём заявок уже закончился, в таблицу не
заносится: сайт держит часть таких лотов в "активной" выдаче неделями
(лот 7215092 - дедлайн 22.09, а в выдаче "Торги объявлены"), и они
крутились по кругу: remove_expired_lots удалял, следующий же обход
поиска заносил заново.

Раньше здесь же (шаг 3) была оценка через Авито по requests
(avito_valuation.make_session/resolve_vin/get_price) - убрана: при 429 от
Авито ретраи там растягиваются до ~4 минут НА ЛОТ (backoff 8s x 2^n x 5
попыток), а колонки avito_price_low/high, которые этот путь писал, нигде
дальше по пайплайну не читаются (реальная рыночная оценка идёт через
autoru_price_low/high - см. evaluate_autoru_browser.py). Если оценка на
Авито снова понадобится - для этого уже есть evaluate_avito_browser.py
(эмуляция браузера, устойчивее к антиботу Qrator).

Про шаг 4: уже занесённые лоты main.py пропускает -
и для аукциона этого достаточно (статус у него меняется только после
торгов, когда лот уже неактуален; перепроверку отменённых аукционов
пока сознательно не делаем, см. TODO.md). А у "публичного предложения"
торги могут закончиться в любом периоде графика - как только пришла
заявка. Поэтому карточки ИДУЩИХ публичных предложений (статус в листе ещё
не "завершены/отменены", окончательный дедлайн не прошёл) перечитываются
и в "lots" обновляются status, price_current,
applications_end и bidding_periods. Сам текущий период (цена и дедлайн)
здесь НЕ пишется - он вычисляется по времени из графика при сборке
lots_processed и отправке дайджеста (см. bidding_schedule.py): иначе
цена в листе снова устаревала бы между запусками. Запросы к сайту
бесплатные, но их десятки-сотни - поэтому недавно проверенные лоты
пропускаются (см. _status_is_fresh: после ночного обновления агрегатора
или раз в config.PUBLIC_OFFER_REFRESH_HOURS часов), а за один запуск -
не больше config.PUBLIC_OFFER_REFRESH_MAX_PER_RUN.

Тем же шагом перечитываются карточки лотов (любой формы торгов), у которых
вместо названия или описания в листе лежит ссылка вида "$7c" - так их
записывал parse_lot.py до того, как научился разворачивать длинные тексты
(nextjs_json.resolve_text_ref). У них обновляются ещё title и description.

Запуск:  python main.py
"""
import time
import datetime
import requests

import automation
import bidding_schedule
import config
import nextjs_json
import parse_search
import parse_lot
import sheets_writer


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


# Сайт периодически не отвечает вовремя ("Read timed out") - обычно это
# разовый сбой, и повтор через несколько секунд проходит. Повторяем только
# сетевые сбои и ответы 429/5xx; 404 и прочие 4xx - сразу ошибка (повтор
# ничего не изменит). Таймаут раздельный: (подключение, чтение).
FETCH_TIMEOUT = (10, 20)
FETCH_RETRY_PAUSES = (5, 15)  # паузы перед 2-й и 3-й попыткой, секунд


def fetch(url, session):
    for attempt in range(len(FETCH_RETRY_PAUSES) + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.raise_for_status()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == len(FETCH_RETRY_PAUSES):
                raise
            pause = FETCH_RETRY_PAUSES[attempt]
            print(f"    сбой загрузки ({type(e).__name__}), повтор через {pause} с...")
            time.sleep(pause)
            continue
        resp.raise_for_status()
        return resp.text


def _final_deadline_passed(applications_end, periods_text, now):
    """Окончательный дедлайн - позднейшее из applications_end и конца
    графика (bidding_schedule.final_deadline). Нераспознанная дата -
    считаем, что не прошёл: лучше лишний раз перечитать карточку, чем
    пропустить лот."""
    try:
        end_dt = datetime.datetime.strptime(
            bidding_schedule.final_deadline(applications_end, periods_text), bidding_schedule.DATE_FORMAT)
    except (ValueError, TypeError):
        return False
    return end_dt < now


def _last_aggregator_update(now):
    """Момент последнего ночного обновления агрегатора (сегодня или вчера
    в config.AGGREGATOR_NIGHTLY_UPDATE)."""
    hh, mm = map(int, config.AGGREGATOR_NIGHTLY_UPDATE.split(":"))
    today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return today if today <= now else today - datetime.timedelta(days=1)


def _status_is_fresh(status_checked_at, now):
    """
    Карточку можно не перечитывать, если после прошлой проверки агрегатор
    ещё не делал ночного обновления И прошло меньше
    config.PUBLIC_OFFER_REFRESH_HOURS часов.

    Почему так: по выборке карточек (поле updated_at) агрегатор обновляет
    лоты в основном одной ночной пачкой около 04:00-04:20, а днём - лишь
    отдельные лоты (как раз закрывшиеся торги). Значит, первый запуск
    после ночи должен перечитать всё, а повторные запуски в тот же день -
    только если с прошлой проверки прошло много часов (ловим дневные
    закрытия). Пустая/нераспознанная дата - не свежая.
    """
    try:
        checked = datetime.datetime.fromisoformat(status_checked_at)
    except (ValueError, TypeError):
        return False
    if checked < _last_aggregator_update(now):
        return False
    return now - checked < datetime.timedelta(hours=config.PUBLIC_OFFER_REFRESH_HOURS)


def refresh_public_offers(worksheet, sheet_state, session, skip_lot_ids):
    """
    Перечитывает карточки идущих публичных предложений и обновляет в
    "lots" статус, текущую цену сайта, окончательный дедлайн и график.
    Заодно - карточки лотов со ссылкой "$7c" вместо названия/описания
    (см. докстринг модуля): им обновляет и title/description.
    skip_lot_ids - лоты, только что занесённые в этом же запуске (их
    карточка уже свежая). Возвращает (проверено, закрылось).
    """
    now = datetime.datetime.now()
    candidates = []
    fresh = 0
    for r in sheets_writer.read_rows(worksheet):
        lot_id = r.get("lot_id")
        if not lot_id or lot_id in skip_lot_ids or not r.get("url"):
            continue
        r["_broken_text"] = nextjs_json.is_text_ref(r.get("title")) or nextjs_json.is_text_ref(r.get("description"))
        if not (r["_broken_text"] or bidding_schedule.is_public_offer(r.get("trade_kind"))):
            continue
        if bidding_schedule.is_closed_status(r.get("status")):
            continue  # торги уже закрыты - статус больше не поменяется
        if _final_deadline_passed(r.get("applications_end"), r.get("bidding_periods"), now):
            continue  # график кончился - лот скоро удалит remove_expired_lots
        if not r["_broken_text"] and _status_is_fresh(r.get("status_checked_at"), now):
            fresh += 1
            continue
        candidates.append(r)

    limit = config.PUBLIC_OFFER_REFRESH_MAX_PER_RUN
    broken = sum(1 for r in candidates if r["_broken_text"])
    print(f"Лотов к проверке: {len(candidates)}, из них со ссылкой вместо названия: {broken} "
          f"(ещё {fresh} публичных проверены недавно - пропускаю)")
    # Первыми - лоты со ссылкой вместо названия, затем те, у кого самые
    # давние проверки (пустая дата - самые первые).
    candidates.sort(key=lambda r: (not r["_broken_text"], r.get("status_checked_at") or ""))
    if len(candidates) > limit:
        print(f"  проверю {limit} (config.PUBLIC_OFFER_REFRESH_MAX_PER_RUN), "
              f"остальные {len(candidates) - limit} - в следующий запуск")
        candidates = candidates[:limit]

    checked = 0
    closed = 0
    for r in candidates:
        lot_id = r["lot_id"]
        time.sleep(config.DELAY_BETWEEN_LOT_REQUESTS)
        try:
            lot_html = fetch(r["url"], session)
        except requests.RequestException as e:
            print(f"  {lot_id}: не удалось загрузить карточку: {e}")
            continue

        lot_data = parse_lot.parse_lot_html(lot_html, url=r["url"])
        if lot_data.get("lot_id") is None:
            print(f"  {lot_id}: в карточке не нашёлся JSON лота - пропускаю")
            continue

        updates = {
            "status": lot_data.get("status"),
            "price_current": lot_data.get("price_current"),
            "bidding_periods": lot_data.get("bidding_periods"),
            "status_checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        # Пустой дедлайн с сайта не затирает известный.
        if lot_data.get("applications_end"):
            updates["applications_end"] = lot_data["applications_end"]
        if r["_broken_text"]:
            updates["title"] = lot_data.get("title")
            updates["description"] = lot_data.get("description")
        sheet_state.update_fields(lot_id, updates)
        checked += 1

        if bidding_schedule.is_closed_status(lot_data.get("status")):
            closed += 1
            print(f"  {lot_id}: {lot_data.get('status')} - {r.get('title', '')[:60]}")

    return checked, closed


def run():
    session = requests.Session()

    print("Подключаюсь к Google Таблице...")
    worksheet = sheets_writer.connect(
        config.SERVICE_ACCOUNT_FILE, config.SPREADSHEET_ID, config.WORKSHEET_NAME
    )

    print(f"Удаляю лоты с приёмом заявок, закончившимся {config.EXPIRED_LOT_DAYS}+ дн. назад...")
    removed = sheets_writer.remove_expired_lots(worksheet, config.EXPIRED_LOT_DAYS)
    print(f"  удалено: {removed}")

    sheet_state = sheets_writer.SheetState(worksheet)
    print(f"Уже в таблице: {len(sheet_state)} лотов")

    page = 1
    total_new = 0
    new_lot_ids = set()
    search_broken = False
    while page <= config.MAX_PAGES:
        url = parse_search.build_search_url(page=page, params=config.SEARCH_PARAMS)
        print(f"\nСтраница поиска {page}: {url}")

        try:
            html = fetch(url, session)
        except requests.RequestException as e:
            print(f"  Ошибка загрузки страницы поиска: {e}")
            break

        result = parse_search.parse_search_html(html)
        print(f"  Найдено лотов на странице: {len(result['lots'])}")
        if page == 1 and not result["lots"]:
            # Первая страница выдачи пустой не бывает. 01.10.2026 агрегатор
            # отдавал на поиск с фильтром категории страницу ошибки с кодом
            # 200 - без этой проверки прогон молча собирал 0 лотов.
            search_broken = True
            print("  " + "!" * 70)
            print("  ВНИМАНИЕ: первая страница поиска пустая - сбой на сайте агрегатора или")
            print("  изменилась вёрстка страницы поиска. Новые лоты в этом прогоне НЕ собраны.")
            print("  Откройте ссылку выше в браузере. Если там лоты есть - нужна правка parse_search.py.")
            print("  " + "!" * 70)

        for lot_stub in result["lots"]:
            lot_id = lot_stub["lot_id"]
            if lot_id in sheet_state.lot_row:
                continue  # уже занесён раньше - пропускаем, не тратим лишние запросы

            print(f"  Новый лот {lot_id}: {lot_stub['title']}")
            time.sleep(config.DELAY_BETWEEN_LOT_REQUESTS)

            try:
                lot_html = fetch(lot_stub["url"], session)
            except requests.RequestException as e:
                print(f"    Не удалось загрузить карточку лота: {e}")
                continue

            lot_data = parse_lot.parse_lot_html(lot_html, url=lot_stub["url"])
            if lot_data.get("parse_error"):
                # Нет данных лота: страница-призрак (агрегатор создал и удалил лот -
                # 01.10.2026 так было с лотом 7159530) или сбой сайта. Пустую строку
                # в таблицу не заносим; если лот настоящий - занесётся в следующий раз.
                print(f"    на странице нет данных лота ({lot_data['parse_error']}) - не заношу")
                continue
            if _final_deadline_passed(lot_data.get("applications_end"), lot_data.get("bidding_periods"),
                                      datetime.datetime.now()):
                print(f"    приём заявок закончился {lot_data.get('applications_end')} - не заношу")
                continue

            # пробег: сначала то, что нашли в самой карточке лота,
            # иначе - то, что удалось вытащить из заголовка/описания на странице поиска
            mileage = lot_data.get("mileage_km") or lot_stub.get("mileage_km")

            row = dict(lot_data)
            row["mileage_km"] = mileage
            row["scraped_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            row["status_checked_at"] = row["scraped_at"]

            sheet_state.upsert(row)
            new_lot_ids.add(lot_id)
            total_new += 1

        if not result["has_next"]:
            print("\nБольше страниц нет, останавливаюсь.")
            break

        page += 1
        time.sleep(config.DELAY_BETWEEN_SEARCH_PAGES)

    print(f"\nДобавлено новых лотов: {total_new}")
    if search_broken:
        automation.alert("Поиск на сайте агрегатора не отдал лоты (пустая первая страница) - новых лотов "
                         "за этот прогон нет не потому, что их нет. Если повторится завтра - смотреть сайт.")

    print("\nОбновляю статус и график публичных предложений...")
    checked, closed = refresh_public_offers(worksheet, sheet_state, session, new_lot_ids)
    print(f"  проверено: {checked}, из них торги закрыты/отменены: {closed}")

    print("\nГотово.")


if __name__ == "__main__":
    run()
