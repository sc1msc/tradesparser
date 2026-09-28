# -*- coding: utf-8 -*-
r"""
Строит лист "lots_current_month" - срез из "lots_processed", содержащий
только лоты, у которых до дедлайна подачи заявок (applications_end)
осталось не больше месяца (и дедлайн ещё не прошёл - лоты с истёкшим
applications_end в срез не попадают, они уже неактуальны).

"Месяц" здесь - 30 дней от текущего момента (для простоты; если нужен
именно календарный месяц - можно заменить на dateutil.relativedelta).

При каждом запуске "lots_current_month" пересобирается заново из текущего
состояния "lots_processed" (стандартные 15 колонок) - НО с сохранением
"хвостовых" колонок за пределами этих 15 (например, estimated_mileage и
результаты оценки Auto.ru, которые пишет evaluate_autoru_browser.py) -
они переносятся по совпадению VIN из предыдущей версии листа. Без этого
пересборка списка актуальных лотов молча стирала бы уже проделанную
оценочную работу.
"""
import datetime

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SOURCE_SHEET = "lots_processed"
TARGET_SHEET = "lots_current_month"

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
WINDOW_DAYS = 30

# Эти 15 колонок собираются заново каждый раз из lots_processed. Всё, что
# дописано ПОСЛЕ них другими скриптами (по имени колонки в шапке) -
# переносится по VIN, а не пересчитывается здесь.
STANDARD_COLUMNS = [
    "brand", "name", "year", "vin", "plate", "url", "title", "mileage_km",
    "price_start", "price_current", "region", "applications_end",
    "bidding_start", "organizer_phone", "organizer_email", "photo_url",
]


def _read_existing_extra_columns(target):
    """
    Читает текущее состояние листа (до пересборки) и возвращает
    (extra_column_names, {vin: {extra_col_name: value}}) - то, что нужно
    перенести в новую версию листа. Если листа ещё нет или в нём только
    стандартные колонки - возвращает пустые структуры.
    """
    try:
        values = target.get_all_values()
    except gspread.WorksheetNotFound:
        return [], {}
    if not values:
        return [], {}

    header = values[0]
    if len(header) <= len(STANDARD_COLUMNS):
        return [], {}  # хвостовых колонок ещё нет

    extra_names = header[len(STANDARD_COLUMNS):]
    if "vin" not in header:
        return extra_names, {}  # не по чему сопоставлять - переносить нечего
    vin_idx = header.index("vin")

    by_vin = {}
    for row in values[1:]:
        vin = row[vin_idx] if vin_idx < len(row) else ""
        if not vin:
            continue
        extras = {}
        for i, name in enumerate(extra_names):
            col_idx = len(STANDARD_COLUMNS) + i
            extras[name] = row[col_idx] if col_idx < len(row) else ""
        by_vin[vin] = extras
    return extra_names, by_vin


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)

    source = spreadsheet.worksheet(SOURCE_SHEET)
    try:
        target = spreadsheet.worksheet(TARGET_SHEET)
    except gspread.WorksheetNotFound:
        target = spreadsheet.add_worksheet(title=TARGET_SHEET, rows=1000, cols=20)

    values = source.get_all_values()
    if not values:
        print(f"Лист '{SOURCE_SHEET}' пуст.")
        return

    header = values[0]
    data_rows = values[1:]

    if "applications_end" not in header:
        print('В шапке не нашёл колонку "applications_end".')
        return
    idx = header.index("applications_end")

    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(days=WINDOW_DAYS)

    selected_rows = []
    skipped_expired = 0
    skipped_far = 0
    skipped_unparsed = 0
    for row in data_rows:
        value = row[idx] if idx < len(row) else ""
        try:
            end_dt = datetime.datetime.strptime(value, DATE_FORMAT)
        except (ValueError, TypeError):
            skipped_unparsed += 1
            continue
        if end_dt < now:
            skipped_expired += 1
            continue
        if end_dt > deadline:
            skipped_far += 1
            continue
        selected_rows.append(row)

    # Сохраняем то, что дописали поверх стандартных 15 колонок другие
    # скрипты (estimated_mileage, оценка Auto.ru и т.д.) - до очистки листа.
    extra_names, extras_by_vin = _read_existing_extra_columns(target)

    vin_idx = header.index("vin") if "vin" in header else None
    out_header = header + extra_names
    out_rows = [out_header]
    carried_over = 0
    for row in selected_rows:
        vin = row[vin_idx] if vin_idx is not None and vin_idx < len(row) else ""
        extras = extras_by_vin.get(vin, {})
        if extras:
            carried_over += 1
        extra_values = [extras.get(name, "") for name in extra_names]
        out_rows.append(row + extra_values)

    target.clear()
    target.update(range_name="A1", values=out_rows)

    print(f"Готово. Всего строк в '{SOURCE_SHEET}': {len(data_rows)}.")
    print(f"Попало в срез (дедлайн через {WINDOW_DAYS} дн. или меньше, ещё не истёк): {len(selected_rows)}")
    print(f"  пропущено (дедлайн уже прошёл): {skipped_expired}")
    print(f"  пропущено (дедлайн дальше {WINDOW_DAYS} дн.): {skipped_far}")
    print(f"  пропущено (дата не распозналась): {skipped_unparsed}")
    if extra_names:
        print(f"Перенесено «хвостовых» колонок: {extra_names}, для {carried_over} из {len(selected_rows)} строк совпал VIN.")
    print(f"Лист '{TARGET_SHEET}' полностью пересобран.")


if __name__ == "__main__":
    run()
