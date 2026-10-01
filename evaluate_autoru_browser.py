# -*- coding: utf-8 -*-
r"""
Массовая оценка лотов через форму Авто.ру (эмуляция браузера,
см. autoru_valuation.py) - ТОЛЬКО для актуальных лотов из листа
"lots_current_month" (не всей базы "lots"/"lots_processed" - незачем
считать оценку для лотов, торги по которым ещё нескоро или уже прошли).

Работает с листом напрямую через gspread (та же схема доступа, что у
build_lots_processed.py/build_lots_current_month.py) - НЕ через
sheets_writer.py, его локальная схема колонок разошлась с реальной
таблицей. Сам добавляет недостающие колонки в шапку при первом запуске:
    estimated_mileage (колонка P)                        - см. ниже
    autoru_price_low, autoru_price_high,
    autoru_tradein_low, autoru_tradein_high,
    autoru_uncertainty_percent, autoru_mark, autoru_model,
    autoru_year, autoru_owners_count, autoru_accuracy_note,
    autoru_status, autoru_checked_at

Пробег для запроса к Авто.ру берётся из mileage_km (там либо пробег с
карточки лота, либо показание TRONK, пересчитанное на сегодня - см.
fill_missing_mileage.py); только если он пуст или неправдоподобен (больше
lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM) - из estimated_mileage,
который сам же и считает по формуле (как для Avito):
(текущий_год - year) * config.ANNUAL_MILEAGE_KM. Если и year пуст -
пробег взять неоткуда, лот помечается "no_mileage" и пропускается.

ВАЖНО: build_lots_current_month.py при пересборке списка актуальных
лотов сохраняет все эти колонки по совпадению VIN - можно спокойно
перезапускать оба скрипта в любом порядке, уже сделанная работа не
потеряется (см. правки в build_lots_current_month.py).

Как и у Avito - Авто.ру сам резолвит марку/модель/год по VIN в том же
ответе, где отдаёт вилку цены. Если need_info_for_evaluation==true -
однозначно определить авто не удалось, цифрам доверять не стоит - статус
"ambiguous", а не "ok".
"""
import re
import time
import random
import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

import config
import lot_metrics
import autoru_valuation
import vin_cache

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "lots_current_month"
CURRENT_YEAR = datetime.datetime.now().year

# Колонки, которые скрипт сам добавляет в шапку, если их ещё нет -
# именно в этом порядке (дописываются в конец листа).
NEW_COLUMNS = [
    "estimated_mileage",
    "autoru_price_low", "autoru_price_high",
    "autoru_tradein_low", "autoru_tradein_high",
    "autoru_uncertainty_percent", "autoru_mark", "autoru_model",
    "autoru_year", "autoru_owners_count", "autoru_accuracy_note",
    "autoru_status", "autoru_checked_at",
]


def _clean_mileage(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def _estimate_mileage(year_str):
    if not year_str:
        return None
    try:
        year = int(year_str)
    except ValueError:
        return None
    return max((CURRENT_YEAR - year) * config.ANNUAL_MILEAGE_KM, 0)


def _ensure_columns(worksheet, header):
    """Дописывает в шапку недостающие колонки из NEW_COLUMNS. Возвращает
    обновлённый header (список имён)."""
    missing = [c for c in NEW_COLUMNS if c not in header]
    if not missing:
        return header
    new_header = header + missing
    worksheet.update(range_name="A1", values=[new_header])
    print(f"Добавил в шапку колонки: {missing}")
    return new_header


def _batch_write(worksheet, row_num, col, updates):
    """
    Пишет все ячейки одного лота ОДНИМ запросом к Sheets API вместо
    отдельного update_cell() на каждое поле. Критично для квоты Google
    (60 write-запросов/мин на пользователя) - раньше на один лот уходило
    до 13 отдельных запросов подряд без паузы между ними, чего хватало,
    чтобы упереться в лимит даже при небольшом числе лотов за прогон.

    updates: {имя_колонки: значение}. Пустые/None значения не пишем -
    нечего записывать нулём поверх того, чего не получили.
    """
    data = []
    for name, value in updates.items():
        if value is None:
            continue
        cell = gspread.utils.rowcol_to_a1(row_num, col[name] + 1)
        data.append({"range": cell, "values": [[value]]})
    if data:
        worksheet.batch_update(data)


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    values = worksheet.get_all_values()
    if not values:
        print(f"Лист '{SHEET_NAME}' пуст.")
        return

    header = _ensure_columns(worksheet, values[0])
    col = {name: idx for idx, name in enumerate(header)}  # 0-based индекс по имени

    for field in ("vin", "year", "mileage_km"):
        if field not in col:
            print(f'В шапке не нашёл колонку "{field}".')
            return

    data_rows = values[1:]

    candidates = []  # (row_num, row_list)
    for i, row in enumerate(data_rows):
        while len(row) < len(header):
            row.append("")
        status = row[col["autoru_status"]].strip()
        vin = row[col["vin"]].strip()
        if not vin or status in ("ok", "ambiguous"):
            continue
        # Мультилот (несколько машин одним лотом) не оцениваем: вилка одной
        # машины к цене всего лота отношения не имеет (lot_metrics.lot_kind).
        if "lot_kind" in col and row[col["lot_kind"]].strip() == lot_metrics.LOT_MULTILOT:
            continue
        candidates.append((i + 2, row))  # 1-based номер строки (шапка - строка 1)

    print(f"Кандидатов на оценку (есть VIN, ещё не оценены, лот актуален): {len(candidates)}")
    if not candidates:
        print("Нечего оценивать, выхожу.")
        return

    to_process = candidates[: config.AUTORU_MAX_PER_RUN]
    skipped = len(candidates) - len(to_process)
    print(f"Лимит за запуск: {config.AUTORU_MAX_PER_RUN}. Будет обработано сейчас: {len(to_process)}")
    if skipped:
        print(f"Ещё {skipped} лотов дождутся следующего запуска.")
    for row_num, row in to_process:
        title_preview = row[col["title"]][:60] if "title" in col else ""
        print(f"  - vin={row[col['vin']]} | {title_preview}")

    answer = input("\nЗапустить браузер и начать оценку? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено.")
        return

    processed = 0
    ok_count = 0
    # Готовые оценки - ещё и в справочник по VIN: переживут выпадение лота
    # из среза и пригодятся, если машину выставят снова (vin_cache.py).
    cache = vin_cache.VinCache(spreadsheet)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.AUTORU_HEADLESS)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        for row_num, row in to_process:
            vin = row[col["vin"]].strip().upper()
            raw_mileage = _clean_mileage(row[col["mileage_km"]])
            # Больше lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM - ошибка источника
            # (TRONK/текст лота): считаем, что пробега нет, и оцениваем по году.
            mileage = lot_metrics.plausible_mileage(raw_mileage)
            mileage_source = "mileage_km"
            if raw_mileage is not None and mileage is None:
                print(f"  Пробег {raw_mileage} км неправдоподобен - считаю по году выпуска")
            updates = {}  # копим все поля этого лота, пишем одним batch_update в конце

            if mileage is None:
                mileage = _estimate_mileage(row[col["year"]])
                mileage_source = "estimated_mileage"
                if mileage is not None:
                    updates["estimated_mileage"] = mileage

            print(f"\n[{vin}] пробег={mileage} (источник: {mileage_source}) ...")

            if mileage is None:
                print("  Ни пробега, ни года - взять пробег неоткуда, пропускаю")
                updates["autoru_status"] = "no_mileage"
                updates["autoru_checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                _batch_write(worksheet, row_num, col, updates)
                processed += 1
                continue

            try:
                result = autoru_valuation.evaluate_by_vin(page, vin, mileage)

                updates["autoru_price_low"] = result["price_low"]
                updates["autoru_price_high"] = result["price_high"]
                updates["autoru_tradein_low"] = result["tradein_low"]
                updates["autoru_tradein_high"] = result["tradein_high"]
                updates["autoru_uncertainty_percent"] = result["uncertainty_percent"]
                updates["autoru_mark"] = result["mark"]
                updates["autoru_model"] = result["model"]
                updates["autoru_year"] = result["year"]
                updates["autoru_owners_count"] = result["owners_count"]

                if result["need_info_for_evaluation"]:
                    status = "ambiguous"
                    updates["autoru_accuracy_note"] = "Оценка может быть неточной"
                    print("  -> ВНИМАНИЕ: Авто.ру не смог однозначно определить авто по VIN")
                else:
                    status = "ok"
                    ok_count += 1

                updates["autoru_status"] = status
                print(
                    f"  -> цена={result['price_low']}-{result['price_high']} "
                    f"({result['mark']} {result['model']}, {result['year']} г.)"
                )
            except Exception as e:
                print(f"  Ошибка: {e}")
                updates["autoru_status"] = f"error: {e}"[:200]

            updates["autoru_checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _batch_write(worksheet, row_num, col, updates)
            if updates.get("autoru_status") in vin_cache.AUTORU_FINAL:
                cache.update(vin, updates)
            processed += 1
            time.sleep(config.DELAY_BETWEEN_AUTORU_REQUESTS + random.uniform(0, 2))

        browser.close()
    cache.flush()

    print(f"\nГотово. Обработано: {processed}, успешно: {ok_count}.")


if __name__ == "__main__":
    run()