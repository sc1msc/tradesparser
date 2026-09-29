# -*- coding: utf-8 -*-
r"""
Разовая починка: переводит в числа те ячейки числовых колонок
(sheets_writer.NUMERIC_COLUMNS), где число лежит ТЕКСТОМ ('450000',
'355674,6'). Без пересборки листов и без повторной оценки Auto.ru - меняет
только сами эти ячейки, на месте.

Откуда текст взялся: до исправления все пересборки читали лист строками
(get_all_values) и писали обратно с valueInputOption=RAW - строка ложилась
в ячейку текстом (подробно - в sheets_writer.py у NUMERIC_COLUMNS). Теперь
скрипты сами пишут числа числами, а этот скрипт чинит то, что уже
накопилось.

Что трогает:
  - листы lots, lots_processed, lots_current_month и все листы подборок
    (selections.SELECTIONS);
  - только колонки из NUMERIC_COLUMNS (ищутся по имени в шапке);
  - только ячейки, где лежит ТЕКСТ, который целиком является числом.
    Числа, пустые ячейки, формулы и нечисловой текст ('10%', 'нет данных')
    не меняются.

Сначала печатает, сколько ячеек и где будет исправлено, и спрашивает
подтверждение. Не запускайте одновременно с run_pipeline.py: пересборка
листа посреди починки перепишет его заново (не страшно - просто
запустите починку ещё раз).

Запуск:  python fix_numeric_cells.py
"""
import gspread
from google.oauth2.service_account import Credentials

import config
import selections
import sheets_writer

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
BASE_SHEETS = ["lots", "lots_processed", "lots_current_month"]
CHUNK = 2000  # ячеек на один запрос записи


def _collect(worksheet):
    """[(a1, число)] для текстовых ячеек-чисел + счётчик по колонкам."""
    # FORMULA, а не значения: так видно, где число, где текст, а где
    # формула (её не трогаем - иначе затёрли бы формулу её результатом).
    values = worksheet.get_all_values(value_render_option="FORMULA")
    if not values:
        return [], {}
    header = values[0]
    cols = [(i, name) for i, name in enumerate(header) if name in sheets_writer.NUMERIC_COLUMNS]
    updates, per_col = [], {}
    for row_offset, row in enumerate(values[1:]):
        for i, name in cols:
            if i >= len(row):
                continue
            value = row[i]
            if not isinstance(value, str) or not value.strip() or value.startswith("="):
                continue
            number = sheets_writer.to_number(value)
            if isinstance(number, (int, float)):
                a1 = gspread.utils.rowcol_to_a1(sheets_writer.FIRST_DATA_ROW + row_offset, i + 1)
                updates.append({"range": a1, "values": [[number]]})
                per_col[name] = per_col.get(name, 0) + 1
    return updates, per_col


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    spreadsheet = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)

    sheet_names = BASE_SHEETS + [item["sheet"] for item in selections.SELECTIONS]
    plan = []
    for name in sheet_names:
        try:
            worksheet = spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            print(f"{name}: листа нет - пропускаю")
            continue
        updates, per_col = _collect(worksheet)
        print(f"{name}: исправить {len(updates)} ячеек" + (f" - {per_col}" if per_col else ""))
        if updates:
            plan.append((worksheet, updates))

    total = sum(len(u) for _, u in plan)
    if not total:
        print("\nТекстовых чисел не найдено, чинить нечего.")
        return

    answer = input(f"\nПеревести в числа {total} ячеек? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, ничего не записано.")
        return

    for worksheet, updates in plan:
        for start in range(0, len(updates), CHUNK):
            worksheet.batch_update(updates[start:start + CHUNK])  # raw=True: число ляжет числом
        print(f"  {worksheet.title}: готово ({len(updates)})")
    print("\nГотово.")


if __name__ == "__main__":
    run()
