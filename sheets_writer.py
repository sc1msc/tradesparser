# -*- coding: utf-8 -*-
"""
Запись данных в Google Таблицу через service account.
Использует gspread (pip install gspread google-auth).

ВАЖНО: здесь принципиально НЕ используется append_row() / автоопределение
таблицы Google Sheets API - это давало сдвиг столбцов на каждой новой строке
(известный источник путаницы: append ищет "таблицу" эвристически и может
промахнуться). Вместо этого мы сами считаем номер строки для каждого лота
и пишем явным диапазоном (например "A5") - это однозначно и предсказуемо.
"""
import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Порядок колонок в таблице. Если добавите новое поле - допишите сюда,
# порядок важен (соответствует порядку столбцов в самой таблице).
COLUMNS = [
    "lot_id", "url", "title", "status", "vin", "plate", "mileage_km",
    "price_start", "price_current", "currency", "region",
    "trade_kind", "platform", "applications_start", "applications_end",
    "bidding_start", "organizer_name", "organizer_phone", "organizer_email",
    "manager_name", "manager_sro", "debtor_name",
    "avito_price_low", "avito_price_high", "scraped_at",
    "tronk_price_avg", "tronk_price_min", "tronk_price_max", "tronk_mileage_avg",
    "tronk_status", "tronk_checked_at",
    "avito_year", "avito_owners", "avito_accuracy_note",
    "avito_status", "avito_checked_at",
    "tronk_marka", "tronk_model", "tronk_year",
    "autoru_price_low", "autoru_price_high", "autoru_tradein_low", "autoru_tradein_high",
    "autoru_uncertainty_percent", "autoru_status", "autoru_checked_at",
    "autoru_mark", "autoru_model", "autoru_year", "autoru_owners_count",
    "autoru_accuracy_note",
    "description",
    "final_price_low", "final_price_high", "final_source",
    "photo_url",
    "mileage_probeg_status", "mileage_probeg_date", "mileage_probeg_source",
    "mileage_probeg_checked_at", "mileage_probeg_km",
    "bidding_periods", "status_checked_at",
]

HEADER_ROW = 1
FIRST_DATA_ROW = 2


def _col_letter(n):
    """1 -> 'A', 24 -> 'X', 27 -> 'AA' и т.д."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _safe_update(worksheet, range_name, values):
    """
    В разных версиях gspread аргументы update() шли в разном порядке
    (range_name, values) в старых vs (values, range_name) в новых.
    Пробуем современный вариант с явными keyword-аргументами; если версия
    совсем старая и ругается - откатываемся на позиционный вызов старого стиля.
    """
    try:
        worksheet.update(range_name=range_name, values=values)
    except TypeError:
        worksheet.update(range_name, values)


def connect(service_account_file, spreadsheet_id, worksheet_name):
    creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(
            title=worksheet_name, rows=1000, cols=max(len(COLUMNS), 26)
        )
    ensure_header(worksheet)
    return worksheet


def ensure_header(worksheet):
    """
    Дописывает в шапку недостающие из COLUMNS колонки - СТРОГО в конец,
    не трогая уже существующие ячейки. Раньше при любом расхождении
    функция перезаписывала весь диапазон A1:{последняя_буква}1 - это
    ломало ситуацию, когда на листе после наших колонок дописаны ещё и
    колонки от другого скрипта (autodoc decoder): при добавлении новой
    колонки в COLUMNS диапазон сдвигался и затирал первую из чужих колонок.
    """
    current_header = worksheet.row_values(HEADER_ROW)
    missing = [c for c in COLUMNS if c not in current_header]
    if not missing:
        return
    new_header = current_header + missing
    start_col = len(current_header) + 1
    end_col = len(new_header)
    range_str = f"{_col_letter(start_col)}{HEADER_ROW}:{_col_letter(end_col)}{HEADER_ROW}"
    _safe_update(worksheet, range_str, [missing])


APPLICATIONS_END_FORMAT = "%Y-%m-%d %H:%M:%S"


def remove_expired_lots(worksheet, days):
    """
    Удаляет строки лотов, у которых приём заявок (applications_end)
    закончился `days` дней назад и раньше. Строки с пустой или
    нераспознанной датой не трогает - лучше оставить лишний лот, чем
    случайно снести что-то из-за сбоя парсинга.

    Возвращает количество удалённых строк.
    """
    values = worksheet.get_all_values()
    if not values:
        return 0
    header = values[0]
    if "applications_end" not in header:
        return 0
    end_idx = header.index("applications_end")

    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

    rows_to_delete = []
    for offset, row in enumerate(values[1:]):
        row_num = FIRST_DATA_ROW + offset
        raw = row[end_idx] if end_idx < len(row) else ""
        if not raw:
            continue
        try:
            dt = datetime.datetime.strptime(raw, APPLICATIONS_END_FORMAT)
        except ValueError:
            continue
        if dt <= cutoff:
            rows_to_delete.append(row_num)

    if not rows_to_delete:
        return 0

    # ОДИН запрос на ВСЕ строки сразу. Раньше здесь был цикл с
    # worksheet.delete_rows() на каждую строку - отдельный write-запрос
    # к Sheets API на КАЖДЫЙ просроченный лот, что при заметном их числе
    # быстро упиралось в лимит 60 запросов/мин (429 Quota exceeded).
    # Вместо этого собираем deleteDimension-запросы на все строки и
    # отправляем одним batch_update(). Внутри одного batch Sheets API
    # применяет запросы по порядку и сдвигает индексы после каждого -
    # поэтому порядок СНИЗУ ВВЕРХ (по убыванию номера строки) всё ещё
    # обязателен, просто теперь это один HTTP-вызов, а не N.
    requests_body = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": worksheet.id,
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,  # Sheets API - 0-based, включительно
                    "endIndex": row_num,        # 0-based, НЕ включительно
                }
            }
        }
        for row_num in sorted(rows_to_delete, reverse=True)
    ]
    worksheet.spreadsheet.batch_update({"requests": requests_body})

    return len(rows_to_delete)


class SheetState:
    """
    Держит в памяти соответствие lot_id -> номер строки и следующую
    свободную строку, чтобы не гадать/не спрашивать Google на каждый лот
    заново и не полагаться на автоопределение таблицы.

    ВАЖНО: позиция каждой колонки берётся из РЕАЛЬНОЙ шапки листа (по
    имени), а не по индексу в списке COLUMNS. Раньше upsert() писал
    фиксированный диапазон A:{последняя_буква_по_числу_COLUMNS} - это
    работало, только пока порядок колонок на листе совпадал с порядком в
    COLUMNS. Как только другой скрипт (autodoc decoder) дописал свои
    колонки (brand, name, date, model, market и т.д.) МЕЖДУ последней
    "нашей" колонкой и теми, что мы добавили позже (description,
    final_price_low/high/source, photo_url) - диапазон съехал, и upsert()
    стал затирать decoder-овские колонки, а photo_url писать не туда.
    """

    def __init__(self, worksheet):
        self.worksheet = worksheet
        self.lot_row = {}

        values = worksheet.get_all_values()
        header = values[0] if values else []
        # 1-based позиция каждой "нашей" колонки в РЕАЛЬНОЙ шапке. Колонка
        # может отсутствовать только если ensure_header() почему-то не
        # отработал перед этим - тогда просто не пишем в неё (не падаем).
        self.col_idx = {name: header.index(name) + 1 for name in COLUMNS if name in header}

        data_rows = values[HEADER_ROW:]  # всё, что после заголовка
        for offset, row in enumerate(data_rows):
            row_num = FIRST_DATA_ROW + offset
            if row and row[0]:
                self.lot_row[row[0]] = row_num

        self.next_row = FIRST_DATA_ROW + len(data_rows)

    def __len__(self):
        return len(self.lot_row)

    def upsert(self, data):
        lot_id = str(data.get("lot_id", ""))
        if not lot_id:
            raise ValueError("data['lot_id'] обязателен")

        if lot_id in self.lot_row:
            row_num = self.lot_row[lot_id]
        else:
            row_num = self.next_row
            self.lot_row[lot_id] = row_num
            self.next_row += 1

        # Пишем каждую колонку в её РЕАЛЬНУЮ позицию отдельным элементом
        # batch_update - но одним запросом к API на лот (как и раньше),
        # просто не диапазоном, а списком отдельных ячеек. Колонки, которых
        # нет в текущей шапке (не должно происходить после ensure_header),
        # молча пропускаем - лучше недописать одно поле, чем упасть.
        cell_updates = []
        for col in COLUMNS:
            col_num = self.col_idx.get(col)
            if col_num is None:
                continue
            text = str(data.get(col, "") or "")
            if col in ("price_start", "price_current"):
                text = text.replace(".", ",")
            cell_updates.append({
                "range": f"{_col_letter(col_num)}{row_num}",
                "values": [[text]],
            })

        if cell_updates:
            self.worksheet.batch_update(cell_updates)
        return row_num

    def update_fields(self, lot_id, data):
        """
        Обновляет ТОЛЬКО переданные поля уже занесённого лота - одним
        запросом к API. В отличие от upsert(), который пишет все COLUMNS
        подряд и затёр бы пустыми строками всё, чего нет в data (оценки
        TRONK/Auto.ru, пробег и т.д.). Нужен main.refresh_public_offers():
        у публичных предложений обновляются статус, цена и график.
        Шапку повторно не читаем - позиции колонок уже есть в self.col_idx.
        """
        row_num = self.lot_row.get(str(lot_id))
        if row_num is None:
            return None
        cell_updates = []
        for col, value in data.items():
            col_num = self.col_idx.get(col)
            if col_num is None:
                continue
            text = str(value if value is not None else "")
            if col in ("price_start", "price_current"):
                text = text.replace(".", ",")
            cell_updates.append({
                "range": f"{_col_letter(col_num)}{row_num}",
                "values": [[text]],
            })
        if cell_updates:
            self.worksheet.batch_update(cell_updates)
        return row_num


def col_index(worksheet, name):
    """
    Номер колонки (1-based) по имени - ищем в РЕАЛЬНОЙ шапке листа, а не
    по индексу в списке COLUMNS (см. докстринг SheetState - та же причина).
    """
    header = worksheet.row_values(HEADER_ROW)
    if name not in header:
        raise ValueError(f'Колонка "{name}" не найдена в шапке листа "{worksheet.title}"')
    return header.index(name) + 1


def batch_set_cells(worksheet, row_num, updates):
    """
    Пишет сразу НЕСКОЛЬКО полей одного лота ОДНИМ запросом к Sheets API -
    вместо отдельного set_cell() на каждое поле. Критично для квоты Google
    (60 write-запросов/мин на пользователя): например, evaluate_tronk.py
    раньше делал 9 отдельных запросов на лот подряд без паузы между ними.

    updates: {имя_колонки: значение}. Пустые/None значения пропускаем -
    незачем стирать то, чего не получили, пустой строкой.
    """
    header = worksheet.row_values(HEADER_ROW)
    cell_updates = []
    for name, value in updates.items():
        if value is None:
            continue
        if name not in header:
            raise ValueError(f'Колонка "{name}" не найдена в шапке листа "{worksheet.title}"')
        col_num = header.index(name) + 1
        cell_updates.append({
            "range": f"{_col_letter(col_num)}{row_num}",
            "values": [[value]],
        })
    if cell_updates:
        worksheet.batch_update(cell_updates)


def read_rows(worksheet):
    """
    Читает все строки данных как список словарей {колонка: значение},
    плюс служебный ключ "_row_num" (номер строки в самой таблице).
    Нужно скриптам, которые ДОПОЛНЯЮТ уже существующие строки (например,
    отдельный скрипт оценки TRONK) - в отличие от SheetState, который
    рассчитан на первичную запись лотов.
    """
    values = worksheet.get_all_values()
    if not values:
        return []
    header = values[0]
    rows = []
    for offset, raw_row in enumerate(values[1:]):
        row_num = FIRST_DATA_ROW + offset
        d = {header[i]: (raw_row[i] if i < len(raw_row) else "") for i in range(len(header))}
        d["_row_num"] = row_num
        rows.append(d)
    return rows


if __name__ == "__main__":
    # Быстрая проверка подключения: python sheets_writer.py
    import config
    ws = connect(config.SERVICE_ACCOUNT_FILE, config.SPREADSHEET_ID, config.WORKSHEET_NAME)
    state = SheetState(ws)
    print("Подключение успешно. Заголовки записаны. Текущих лотов в таблице:", len(state))