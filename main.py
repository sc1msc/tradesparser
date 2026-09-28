# -*- coding: utf-8 -*-
"""
Главный скрипт бота:
  1) обходит страницы поиска (parse_search.py)
  2) для каждого нового лота открывает карточку и парсит детали (parse_lot.py)
  3) пишет всё в Google Таблицу (sheets_writer.py)

Раньше здесь же (шаг 3) была оценка через Авито по requests
(avito_valuation.make_session/resolve_vin/get_price) - убрана: при 429 от
Авито ретраи там растягиваются до ~4 минут НА ЛОТ (backoff 8s x 2^n x 5
попыток), а колонки avito_price_low/high, которые этот путь писал, нигде
дальше по пайплайну не читаются (реальная рыночная оценка идёт через
autoru_price_low/high - см. evaluate_autoru_browser.py). Если оценка на
Авито снова понадобится - для этого уже есть evaluate_avito_browser.py
(эмуляция браузера, устойчивее к антиботу Qrator).

Запуск:  python main.py
"""
import time
import datetime
import requests

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

            sheet_state.upsert(row)
            total_new += 1

        if not result["has_next"]:
            print("\nБольше страниц нет, останавливаюсь.")
            break

        page += 1
        time.sleep(config.DELAY_BETWEEN_SEARCH_PAGES)

    print(f"\nГотово. Добавлено/обновлено лотов: {total_new}")


if __name__ == "__main__":
    run()
