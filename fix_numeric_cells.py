# -*- coding: utf-8 -*-
r"""
Разовая починка числовых колонок (sheets_writer.NUMERIC_COLUMNS): переводит
в числа ячейки, где число лежит ТЕКСТОМ ('450000', '355674,6', '30000000%'),
и снимает процентный формат с ячеек, которым он не положен. Без пересборки
листов и без повторной оценки Auto.ru - меняет только сами эти ячейки, на
месте.

Откуда текст взялся: до исправления все пересборки читали лист строками
(get_all_values) и писали обратно с valueInputOption=RAW - строка ложилась
в ячейку текстом (подробно - в sheets_writer.py у NUMERIC_COLUMNS). Теперь
скрипты сами пишут числа числами, а этот скрипт чинит то, что уже
накопилось.

Откуда процентный формат: ячейка помнит формат, даже когда пересборка
кладёт в неё другое значение. У части ячеек estimated_mileage в
lots_current_month остался процентный формат от старых ручных "% below
mkt" - пробег 300000 показывался как "30000000%", так и читался, а перенос
vin_cache.py --backfill (01.10.2026) записал этот текст в справочник у 57
VIN (см. sheets_writer.to_number). Формат снимаем ("автоматический"), иначе
число в такой ячейке снова читалось бы с "%" - и мини-апп не видел бы
пробега. Колонку "% below mkt" не трогаем: её формат ставит
build_lot_selections.py.

Что трогает:
  - листы lots, lots_processed, lots_current_month, все листы подборок
    (selections.SELECTIONS) и справочник vin_cache;
  - только колонки из NUMERIC_COLUMNS (ищутся по имени в шапке);
  - только ячейки, где лежит ТЕКСТ, который целиком является числом (в том
    числе "30000000%" -> 300000), и ячейки с процентным форматом.
    Числа, пустые ячейки, формулы и нечисловой текст ('нет данных') не
    меняются.

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
import vin_cache

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
BASE_SHEETS = ["lots", "lots_processed", "lots_current_month"]
CHUNK = 2000  # ячеек на один запрос записи
# Свой формат (число с одним знаком) ставит build_lot_selections.py.
KEEP_FORMAT_COLUMNS = {"% below mkt"}


def _collect(worksheet):
    """(header, [{"range", "values"}] для текстовых ячеек-чисел, счётчик по колонкам)."""
    # FORMULA, а не значения: так видно, где число, где текст, а где
    # формула (её не трогаем - иначе затёрли бы формулу её результатом).
    values = worksheet.get_all_values(value_render_option="FORMULA")
    if not values:
        return [], [], {}
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
    return header, updates, per_col


def _percent_cells(spreadsheet, worksheet, header):
    """([(строка, колонка)] 0-based ячеек данных числовых колонок с процентным
    форматом, счётчик по колонкам). Формат читаем из метаданных - видно и
    пустые ячейки, куда пробег ляжет при следующей оценке."""
    cols = {i: name for i, name in enumerate(header)
            if name in sheets_writer.NUMERIC_COLUMNS and name not in KEEP_FORMAT_COLUMNS}
    if not cols:
        return [], {}
    meta = spreadsheet.fetch_sheet_metadata(params={
        "includeGridData": "true",
        "ranges": gspread.utils.absolute_range_name(worksheet.title),
        "fields": "sheets(data(startRow,startColumn,rowData(values(userEnteredFormat(numberFormat(type))))))",
    })
    cells, per_col = [], {}
    for grid in meta["sheets"][0].get("data", []):
        row0, col0 = grid.get("startRow", 0), grid.get("startColumn", 0)
        for r, row_data in enumerate(grid.get("rowData", []), start=row0):
            if r == 0:  # шапка
                continue
            for c, cell in enumerate(row_data.get("values", []), start=col0):
                fmt = cell.get("userEnteredFormat", {}).get("numberFormat", {})
                if c in cols and fmt.get("type") == "PERCENT":
                    cells.append((r, c))
                    per_col[cols[c]] = per_col.get(cols[c], 0) + 1
    return cells, per_col


def _clear_format_requests(worksheet, cells):
    """repeatCell на каждый столбик подряд идущих ячеек: формат числа -
    "автоматический" (поле в маске fields, которого нет в cell, очищается)."""
    requests = []
    for c in sorted({c for _, c in cells}):
        rows = sorted(r for r, cc in cells if cc == c)
        start = prev = rows[0]
        for r in rows[1:] + [None]:
            if r is not None and r == prev + 1:
                prev = r
                continue
            requests.append({"repeatCell": {
                "range": {"sheetId": worksheet.id, "startRowIndex": start, "endRowIndex": prev + 1,
                          "startColumnIndex": c, "endColumnIndex": c + 1},
                "cell": {"userEnteredFormat": {}},
                "fields": "userEnteredFormat.numberFormat",
            }})
            start = prev = r
    return requests


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    spreadsheet = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)

    sheet_names = BASE_SHEETS + [item["sheet"] for item in selections.SELECTIONS] + [vin_cache.SHEET_NAME]
    plan = []
    for name in sheet_names:
        try:
            worksheet = spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            print(f"{name}: листа нет - пропускаю")
            continue
        header, updates, per_col = _collect(worksheet)
        cells, pct_per_col = _percent_cells(spreadsheet, worksheet, header)
        print(f"{name}: текст -> число {len(updates)} ячеек" + (f" {per_col}" if per_col else "")
              + f"; снять процентный формат: {len(cells)}" + (f" {pct_per_col}" if pct_per_col else ""))
        if updates or cells:
            plan.append((worksheet, updates, cells))

    total = sum(len(u) + len(c) for _, u, c in plan)
    if not total:
        print("\nЧинить нечего.")
        return

    answer = input(f"\nИсправить {total} ячеек? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, ничего не записано.")
        return

    for worksheet, updates, cells in plan:
        # сначала формат: число, записанное в процентную ячейку, снова
        # читалось бы с "%"
        if cells:
            spreadsheet.batch_update({"requests": _clear_format_requests(worksheet, cells)})
        for start in range(0, len(updates), CHUNK):
            worksheet.batch_update(updates[start:start + CHUNK])  # raw=True: число ляжет числом
        print(f"  {worksheet.title}: готово (значений {len(updates)}, формат {len(cells)})")
    print("\nГотово.")


if __name__ == "__main__":
    run()
