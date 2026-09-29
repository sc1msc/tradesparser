# -*- coding: utf-8 -*-
"""
Главный скрипт бота:
  1) обходит страницы поиска (parse_search.py)
  2) для каждого нового лота открывает карточку и парсит детали (parse_lot.py)
  3) пишет всё в Google Таблицу (sheets_writer.py)
  4) перечитывает карточки идущих публичных предложений и обновляет их
     статус и график снижения цены (refresh_public_offers, см. ниже)

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
не "завершены/отменены", окончательный дедлайн не прошёл) читаются заново
на каждом запуске и в "lots" обновляются status, price_current,
applications_end и bidding_periods. Сам текущий период (цена и дедлайн)
здесь НЕ пишется - он вычисляется по времени из графика при сборке
lots_processed и отправке дайджеста (см. bidding_schedule.py): иначе
цена в листе снова устаревала бы между запусками. Запросы к сайту
бесплатные, но их десятки-сотни - лимит в config.PUBLIC_OFFER_REFRESH_MAX_PER_RUN.

Запуск:  python main.py
"""
import time
import datetime
import requests

import bidding_schedule
import config
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


def fetch(url, session):
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def _final_deadline_passed(applications_end, now):
    """applications_end в листе "lots" - окончательный дедлайн (конец
    последнего периода). Нераспознанная дата - считаем, что не прошёл:
    лучше лишний раз перечитать карточку, чем пропустить лот."""
    try:
        end_dt = datetime.datetime.strptime(applications_end, bidding_schedule.DATE_FORMAT)
    except (ValueError, TypeError):
        return False
    return end_dt < now


def refresh_public_offers(worksheet, sheet_state, session, skip_lot_ids):
    """
    Перечитывает карточки идущих публичных предложений и обновляет в
    "lots" статус, текущую цену сайта, окончательный дедлайн и график.
    skip_lot_ids - лоты, только что занесённые в этом же запуске (их
    карточка уже свежая). Возвращает (проверено, закрылось).
    """
    now = datetime.datetime.now()
    candidates = []
    for r in sheets_writer.read_rows(worksheet):
        lot_id = r.get("lot_id")
        if not lot_id or lot_id in skip_lot_ids or not r.get("url"):
            continue
        if not bidding_schedule.is_public_offer(r.get("trade_kind")):
            continue
        if bidding_schedule.is_closed_status(r.get("status")):
            continue  # торги уже закрыты - статус больше не поменяется
        if _final_deadline_passed(r.get("applications_end"), now):
            continue  # график кончился - лот скоро удалит remove_expired_lots
        candidates.append(r)

    limit = config.PUBLIC_OFFER_REFRESH_MAX_PER_RUN
    print(f"Идущих публичных предложений в таблице: {len(candidates)}")
    if len(candidates) > limit:
        # Первыми - те, у кого самые давние проверки (пустая дата - самые первые).
        candidates.sort(key=lambda r: r.get("status_checked_at") or "")
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

    print("\nОбновляю статус и график публичных предложений...")
    checked, closed = refresh_public_offers(worksheet, sheet_state, session, new_lot_ids)
    print(f"  проверено: {checked}, из них торги закрыты/отменены: {closed}")

    print("\nГотово.")


if __name__ == "__main__":
    run()
