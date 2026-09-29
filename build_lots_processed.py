# -*- coding: utf-8 -*-
r"""
Строит лист "lots_processed" - чистую производную витрину из листа "lots"
(только нужные колонки + вычисляемый год). Не трогает исходный лист "lots"
и не использует sheets_writer.py (его локальная схема разошлась с реальной
таблицей) - работает с обоими листами напрямую по буквам колонок.

При каждом запуске лист "lots_processed" полностью перезаписывается заново
из текущего состояния "lots" - это чистая проекция/трансформация без
собственного накопленного состояния, пересчитывать с нуля дёшево и надёжнее,
чем поддерживать частичные обновления.

Колонки в lots_processed и откуда они берутся из lots:
    brand              <- AZ
    name               <- BA
    year               <- вычисляется регуляркой из BB (свободный текст даты)
    vin                <- E
    plate              <- F
    url                <- B
    title              <- C
    mileage_km         <- G
    price_start        <- H
    price_current      <- I
    region             <- K
    applications_end   <- O
    bidding_start      <- P
    organizer_phone    <- R
    organizer_email    <- S
    photo_url, status, bidding_periods <- по имени в шапке lots

Цена и дедлайн ТЕКУЩЕГО периода у публичного предложения: если у лота
заполнен bidding_periods (график снижения цены, см. bidding_schedule.py),
то price_current и applications_end здесь НЕ копируются из lots, а
вычисляются на момент сборки - цена и конец приёма заявок периода, который
идёт сейчас. В самом lots applications_end - окончательный дедлайн
(конец последнего периода), и его там менять нельзя: на нём держится
удаление истёкших лотов. Всё, что дальше (lots_current_month с окном в 30
дней, подборки, "% below mkt"), автоматически работает с текущим
периодом. status и bidding_periods едут дальше как есть - первый нужен
build_lots_current_month.py (отсев завершённых/отменённых торгов), второй -
send_digest.py (пересчёт цены на момент отправки).

После сборки строки сортируются по applications_end (конец приёма заявок)
по возрастанию - ближайшие сверху. Это готовит почву для следующего шага:
подборок лотов, которые торгуются в ближайший месяц.
"""
import re
import datetime

import gspread
from google.oauth2.service_account import Credentials

import bidding_schedule
import config
import fill_missing_from_title
import sheets_writer

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SOURCE_SHEET = "lots"
TARGET_SHEET = "lots_processed"
DATE_COL = "BB"  # откуда берём свободный текст даты для вычисления года
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"  # формат дат в листе lots (колонки O, P и т.д.)

YEAR_RE = re.compile(r"\d{4}")


def extract_year(date_str):
    """Единственная группа из 4 подряд идущих цифр - и есть год, независимо
    от формата даты (MM.YYYY / DD.MM.YYYY / DD/MM/YYYY) - день и месяц
    в этих форматах всегда 1-2 цифры, так что разбирать формат не нужно."""
    if not date_str:
        return None
    m = YEAR_RE.search(date_str)
    return m.group(0) if m else None


def col_letter_to_index(letter):
    """'A' -> 0, 'B' -> 1, ..., 'AZ' -> 51, 'BB' -> 53 и т.д. (0-based)."""
    result = 0
    for ch in letter:
        result = result * 26 + (ord(ch.upper()) - ord("A") + 1)
    return result - 1


# Порядок целевых колонок в lots_processed:
# (буква_колонки_в_lots или None для вычисляемого года, имя_в_lots_processed)
COLUMN_MAP = [
    ("AZ", "brand"),
    ("BA", "name"),
    (None, "year"),
    ("E", "vin"),
    ("F", "plate"),
    ("B", "url"),
    ("C", "title"),
    ("G", "mileage_km"),
    ("H", "price_start"),
    ("I", "price_current"),
    ("K", "region"),
    ("O", "applications_end"),
    ("P", "bidding_start"),
    ("R", "organizer_phone"),
    ("S", "organizer_email"),
]


def get_cell(row, letter):
    idx = col_letter_to_index(letter)
    return row[idx] if idx < len(row) else ""


def _date_sort_key(out_row, sort_idx):
    """
    Ключ сортировки по дате (по возрастанию - ближайшие сверху).
    Пустые или нераспознанные значения уходят в конец списка, а не путаются
    где-то посередине (datetime.max как "бесконечно далёкая дата").
    """
    value = out_row[sort_idx]
    try:
        return datetime.datetime.strptime(value, DATE_FORMAT)
    except (ValueError, TypeError):
        return datetime.datetime.max


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)

    source = spreadsheet.worksheet(SOURCE_SHEET)
    try:
        target = spreadsheet.worksheet(TARGET_SHEET)
    except gspread.WorksheetNotFound:
        target = spreadsheet.add_worksheet(title=TARGET_SHEET, rows=1000, cols=len(COLUMN_MAP) + 1)

    values = source.get_all_values()
    if not values:
        print(f"Лист '{SOURCE_SHEET}' пуст.")
        return
    source_header = values[0]
    data_rows = values[1:]  # без заголовка

    # photo_url ищем по ИМЕНИ в реальной шапке, не по букве - её позиция
    # не гарантирована (зависит от того, что ещё дописано в lots другими
    # скриптами); буквы в COLUMN_MAP ниже проверены руками один раз и для
    # старых, стабильных по порядку колонок это ОК, но плодить новые
    # захардкоженные буквы для каждого нового поля - плохая идея.
    photo_idx = source_header.index("photo_url") if "photo_url" in source_header else None
    status_idx = source_header.index("status") if "status" in source_header else None
    periods_idx = source_header.index("bidding_periods") if "bidding_periods" in source_header else None

    header = [name for _, name in COLUMN_MAP] + ["photo_url", "status", "bidding_periods"]
    price_idx = header.index("price_current")
    end_idx = header.index("applications_end")
    out_rows_data = []

    def by_idx(row, idx):
        return row[idx] if idx is not None and idx < len(row) else ""

    now = datetime.datetime.now()
    year_filled = 0
    by_schedule = 0
    for row in data_rows:
        out_row = []
        for letter, name in COLUMN_MAP:
            if letter is None:  # колонка "year"
                year = extract_year(get_cell(row, DATE_COL))
                out_row.append(year or "")
                if year:
                    year_filled += 1
            else:
                out_row.append(get_cell(row, letter))
        periods = by_idx(row, periods_idx)
        out_row += [by_idx(row, photo_idx), by_idx(row, status_idx), periods]
        if periods:
            price, deadline = bidding_schedule.effective_price_and_deadline(
                out_row[price_idx], out_row[end_idx], periods, now
            )
            if deadline != out_row[end_idx] or price != out_row[price_idx]:
                by_schedule += 1
            out_row[price_idx], out_row[end_idx] = price, deadline
        out_rows_data.append(out_row)

    out_rows_data.sort(key=lambda r: _date_sort_key(r, end_idx))

    # Пустые brand/name/year - из текста title, прямо здесь, до записи.
    # Раньше это был отдельный шаг после этого скрипта, и любой отдельный
    # запуск build_lots_processed.py молча стирал его результат.
    fill_stats = fill_missing_from_title.fill_rows(header, out_rows_data)

    # Числа - числами, а не текстом (см. sheets_writer.NUMERIC_COLUMNS).
    sheets_writer.numify_rows(header, out_rows_data)
    out_rows = [header] + out_rows_data

    target.clear()
    target.update(range_name="A1", values=out_rows)

    print(f"Готово. Строк: {len(data_rows)}, год определён для {year_filled} из них.")
    print(f"Цена/дедлайн взяты из текущего периода графика (публичное предложение): {by_schedule}")
    if fill_stats:
        print("Доливка brand/name/year из title:")
        fill_missing_from_title.print_stats(fill_stats)
    print(f"Лист '{TARGET_SHEET}' полностью пересобран.")


if __name__ == "__main__":
    run()
