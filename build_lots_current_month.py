# -*- coding: utf-8 -*-
r"""
Строит лист "lots_current_month" - срез из "lots_processed", содержащий
только лоты, у которых до дедлайна подачи заявок (applications_end)
осталось не больше месяца (и дедлайн ещё не прошёл - лоты с истёкшим
applications_end в срез не попадают, они уже неактуальны).

Для публичного предложения applications_end в lots_processed - уже
конец приёма заявок ТЕКУЩЕГО периода графика, а не окончание торгов
целиком (см. build_lots_processed.py / bidding_schedule.py). Поэтому в
срез попадают и лоты с длинным графиком, если их текущий период
заканчивается в пределах окна. Лоты, у которых торги уже завершены,
отменены или приостановлены (status, обновляется в main.py), в срез не
попадают, даже если по графику приём заявок ещё идёт.

"Месяц" здесь - 30 дней от текущего момента (для простоты; если нужен
именно календарный месяц - можно заменить на dateutil.relativedelta).

При каждом запуске "lots_current_month" пересобирается заново из текущего
состояния "lots_processed" (стандартные колонки, STANDARD_COLUMNS) - НО с сохранением
"хвостовых" колонок за пределами этих 15 (например, estimated_mileage и
результаты оценки Auto.ru, которые пишет evaluate_autoru_browser.py) -
они переносятся по совпадению VIN из предыдущей версии листа. Без этого
пересборка списка актуальных лотов молча стирала бы уже проделанную
оценочную работу.
"""
import datetime

import gspread
from google.oauth2.service_account import Credentials

import bidding_schedule
import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SOURCE_SHEET = "lots_processed"
TARGET_SHEET = "lots_current_month"

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
WINDOW_DAYS = 30

# Эти колонки собираются заново каждый раз из lots_processed (должны
# совпадать с его шапкой). Всё остальное, что дописано в лист другими
# скриптами (по имени колонки в шапке) - переносится по VIN, а не
# пересчитывается здесь.
STANDARD_COLUMNS = [
    "brand", "name", "year", "vin", "plate", "url", "title", "mileage_km",
    "price_start", "price_current", "region", "applications_end",
    "bidding_start", "organizer_phone", "organizer_email", "photo_url",
    "status", "bidding_periods",
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
    # Хвостовые колонки ищем по ИМЕНИ, а не "всё правее N-й": когда в
    # STANDARD_COLUMNS добавили status/bidding_periods, срез по позиции
    # принял бы первые две оценочные колонки старого листа за стандартные
    # и молча их потерял.
    extra_positions = [(i, name) for i, name in enumerate(header)
                       if name and name not in STANDARD_COLUMNS]
    extra_names = [name for _, name in extra_positions]
    if not extra_names:
        return [], {}  # хвостовых колонок ещё нет
    if "vin" not in header:
        return extra_names, {}  # не по чему сопоставлять - переносить нечего
    vin_idx = header.index("vin")

    by_vin = {}
    for row in values[1:]:
        vin = row[vin_idx] if vin_idx < len(row) else ""
        if not vin:
            continue
        extras = {}
        for col_idx, name in extra_positions:
            extras[name] = row[col_idx] if col_idx < len(row) else ""
        by_vin[vin] = extras
    return extra_names, by_vin


def _overwrite_sheet(target, out_rows):
    """
    Перезаписывает лист БЕЗ промежуточного "пустого" состояния. Раньше
    было clear() + update(): если второй запрос падал (сеть, 429 от
    Google), лист оставался пустым - а вместе с ним пропадали и
    autoru_*-колонки, которые берутся ТОЛЬКО из этого же листа (см.
    _read_existing_extra_columns) и восстанавливаются лишь повторным
    прогоном браузера по всем лотам.

    Теперь порядок обратный: сначала одним запросом пишем новые данные
    поверх старых, и только потом стираем то, что осталось от прошлой
    версии ниже/правее. Если упадёт первый запрос - на листе остаются
    старые данные целиком; если второй - лишние старые строки внизу, но
    ничего не потеряно, следующий запуск их дочистит.
    """
    target.update(range_name="A1", values=out_rows)

    n_rows = len(out_rows)
    n_cols = max(len(r) for r in out_rows)
    last = gspread.utils.rowcol_to_a1(target.row_count, target.col_count)
    ranges = []
    if n_rows < target.row_count:
        ranges.append(f"A{n_rows + 1}:{last}")  # старые строки ниже новых
    if n_cols < target.col_count:
        first = gspread.utils.rowcol_to_a1(1, n_cols + 1)
        ranges.append(f"{first}:{last}")        # старые колонки правее новых
    if ranges:
        target.batch_clear(ranges)


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
    status_idx = header.index("status") if "status" in header else None

    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(days=WINDOW_DAYS)

    selected_rows = []
    skipped_expired = 0
    skipped_far = 0
    skipped_unparsed = 0
    skipped_closed = 0
    for row in data_rows:
        status = row[status_idx] if status_idx is not None and status_idx < len(row) else ""
        if bidding_schedule.is_closed_status(status):
            skipped_closed += 1
            continue
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

    # Сохраняем то, что дописали поверх стандартных колонок другие
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

    _overwrite_sheet(target, out_rows)

    print(f"Готово. Всего строк в '{SOURCE_SHEET}': {len(data_rows)}.")
    print(f"Попало в срез (дедлайн через {WINDOW_DAYS} дн. или меньше, ещё не истёк): {len(selected_rows)}")
    print(f"  пропущено (дедлайн уже прошёл): {skipped_expired}")
    print(f"  пропущено (дедлайн дальше {WINDOW_DAYS} дн.): {skipped_far}")
    print(f"  пропущено (дата не распозналась): {skipped_unparsed}")
    print(f"  пропущено (торги завершены/отменены/приостановлены): {skipped_closed}")
    if extra_names:
        print(f"Перенесено «хвостовых» колонок: {extra_names}, для {carried_over} из {len(selected_rows)} строк совпал VIN.")
    print(f"Лист '{TARGET_SHEET}' полностью пересобран.")


if __name__ == "__main__":
    run()
