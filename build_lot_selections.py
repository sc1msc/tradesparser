# -*- coding: utf-8 -*-
r"""
Строит сразу несколько тематических срезов из "lots_current_month" -
каждый на свой лист. Работает напрямую через gspread (та же схема, что у
build_lots_missing_info.py и остальных build_*.py) - "lots_current_month"
только читает, не трогает.

Срезы (см. SELECTIONS ниже) - каждый отсортирован по "% below mkt" по
убыванию (см. _sort_by_gap), лоты без оценки Авто.ру - в конец: это
общее для всех срезов, т.к. send_digest.py одинаково подписывает
кандидатов на отправку "из топа по выгодности" для любой подборки:
  1) lots_top_gap          - топ-50 по наибольшему "% below mkt"
  2) lots_budget_1m        - price_current <= 1 000 000
  3) lots_one_owner        - autoru_owners_count == 1
  4) lots_heavy_luxury     - price_current > 5 000 000
  5) lots_polo_rio_solyaris- модель Polo/Rio/Solaris, year >= текущий-10

Цена берётся из price_current (текущая цена торгов, а не стартовая) -
так актуальнее для "интересности" прямо сейчас. У публичного предложения
это уже цена текущего периода графика на момент сборки lots_processed
(см. bidding_schedule.py); send_digest.py пересчитывает её ещё раз в
момент отправки.

Разрыв от рынка ("% below mkt") СЧИТАЕМ САМИ - по autoru_price_low/high
и price_current (см. _compute_gap, формула - lot_metrics.gap_percent).
Раньше этот процент читался из одноимённой колонки в lots_current_month,
но выяснилось, что туда просто руками вписано число - оно никак не
связано с реальными autoru_price_* и не обновляется, когда лот
переоценивают. При записи выходных срезов
эта же колонка перезаписывается посчитанным значением (см. _write_gap),
чтобы send_digest.py показывал верный разрыв, а не то, что там раньше
случайно оказалось.

% below mkt = (market_mid - price_current) / market_mid * 100, где
market_mid = (autoru_price_low + autoru_price_high) / 2 - середина вилки
Авто.ру. Положительное значение - лот дешевле рынка (зелёный в дайджесте),
отрицательное - дороже рынка (красный).
"""
import datetime
import re

import gspread
from google.oauth2.service_account import Credentials

import config
import lot_metrics
import selections

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SOURCE_SHEET = "lots_current_month"

PERCENT_BELOW_MKT_COL = "% below mkt"
CURRENT_YEAR = datetime.datetime.now().year

BUDGET_LIMIT = 1_000_000
LUXURY_MIN_PRICE = 5_000_000
TOP_GAP_LIMIT = 50
MODEL_MAX_AGE_YEARS = 10
# Модели - и латиницей, и кириллицей: в колонку name (Autodoc или
# fill_missing_from_title.py из текста title) модель может попасть как
# "Solaris", так и "Солярис".
TARGET_MODELS = {"POLO", "RIO", "SOLARIS", "ПОЛО", "РИО", "СОЛЯРИС"}

# Кириллические буквы, которые выглядят как латинские. В документах торгов
# их часто смешивают в одном слове ("РOLO" с русской Р) - такое слово не
# совпадёт ни с латинским, ни с кириллическим вариантом, поэтому слово
# дополнительно проверяем после замены двойников на латиницу.
CYR_LOOKALIKES = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")

# Ключевые слова повреждений и сама проверка - в lot_metrics.py: тот же
# список использует мини-апп (значок "возможно, повреждён" на карточке).
_looks_damaged = lot_metrics.looks_damaged


def _to_number(value):
    """
    Парсер чисел ТОЛЬКО для фильтрации/сортировки в памяти - на то, как
    цена хранится в самой таблице (текст/число), никак не влияет.

    Разделителя разрядов (тысяч) в этой таблице нет и не было - только
    десятичный, и это запятая (как обычно в русской локали: '23,5').
    Для целых чисел (без запятой вообще, например price_current вида
    '500000') замена ничего не меняет - проблема реально всплывает
    только на дробных значениях вроде "% below mkt".
    """
    if not value:
        return None
    cleaned = str(value).replace("%", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_float(value):
    return _to_number(value)


def _to_int(value):
    """Округляет через float, а не режет цифры вручную - так '6,500,000.00'
    корректно даёт 6500000, а не склеенные вместе целую и дробную части."""
    n = _to_number(value)
    return int(n) if n is not None else None


def _load(source):
    values = source.get_all_values()
    if not values:
        return [], []
    return values[0], values[1:]


def _get(row, header, col_idx_cache, name):
    if name not in col_idx_cache:
        if name not in header:
            col_idx_cache[name] = None
        else:
            col_idx_cache[name] = header.index(name)
    idx = col_idx_cache[name]
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def format_gap(gap):
    """Число -> текст для колонки "% below mkt" ('12,3'); None -> ''."""
    return f"{gap:.1f}".replace(".", ",") if gap is not None else ""


def _compute_gap(row, header, cache):
    """% below mkt по строке листа. Формула - lot_metrics.gap_percent
    (одна на дайджест и мини-апп); None, если цена или вилка Авто.ру
    не заполнены."""
    return lot_metrics.gap_percent(
        _to_float(_get(row, header, cache, "price_current")),
        _to_float(_get(row, header, cache, "autoru_price_low")),
        _to_float(_get(row, header, cache, "autoru_price_high")),
    )


def build_top_gap(header, data_rows, cache):
    rows_with_gap = []
    excluded_damaged = 0
    for row in data_rows:
        if _looks_damaged(_get(row, header, cache, "title")):
            excluded_damaged += 1
            continue
        gap = _compute_gap(row, header, cache)
        if gap is not None:
            rows_with_gap.append((gap, row))
    rows_with_gap.sort(key=lambda pair: pair[0], reverse=True)
    if excluded_damaged:
        print(f"  (top_gap: исключено {excluded_damaged} лотов по ключевым словам повреждений)")
    return [row for _, row in rows_with_gap[:TOP_GAP_LIMIT]]


def build_budget_1m(header, data_rows, cache):
    selected = []
    for row in data_rows:
        price = _to_int(_get(row, header, cache, "price_current"))
        if price is None or price > BUDGET_LIMIT:
            continue
        gap = _compute_gap(row, header, cache)
        selected.append((gap if gap is not None else float("-inf"), row))
    selected.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in selected]


def _sort_by_gap(rows, header, cache):
    """Сортировка по разрыву от рынка (по убыванию, самое выгодное сверху) -
    send_digest.py подписывает кандидатов на отправку "из топа по
    выгодности" одинаково для всех подборок, так что и сортировка должна
    быть одинаковой везде, а не только в top_gap/budget_1m. Лоты без
    оценки Авто.ру (gap=None) - в конец, а не выпадают из подборки."""
    scored = [(_compute_gap(row, header, cache), row) for row in rows]
    scored.sort(key=lambda pair: pair[0] if pair[0] is not None else float("-inf"), reverse=True)
    return [row for _, row in scored]


def build_one_owner(header, data_rows, cache):
    selected = [
        row for row in data_rows
        if _to_int(_get(row, header, cache, "autoru_owners_count")) == 1
    ]
    return _sort_by_gap(selected, header, cache)


def build_heavy_luxury(header, data_rows, cache):
    selected = []
    for row in data_rows:
        price = _to_int(_get(row, header, cache, "price_current"))
        if price is not None and price > LUXURY_MIN_PRICE:
            selected.append(row)
    return _sort_by_gap(selected, header, cache)


def build_polo_rio_solyaris(header, data_rows, cache):
    selected = []
    for row in data_rows:
        # Сравниваем ЦЕЛЫЕ слова названия модели, а не подстроку: раньше
        # проверка "RIO" in model пропускала PRIORA и PATRIOT (в обоих
        # внутри есть буквы RIO). Слова режем по всему, что не буква/цифра -
        # так "RIO X-LINE" и "POLO SEDAN" по-прежнему проходят.
        words = set(re.split(r"[\W_]+", _get(row, header, cache, "name").upper()))
        words |= {w.translate(CYR_LOOKALIKES) for w in words}
        if not words & TARGET_MODELS:
            continue
        year = _to_int(_get(row, header, cache, "year"))
        if year is None or year < CURRENT_YEAR - MODEL_MAX_AGE_YEARS:
            continue
        selected.append(row)
    return _sort_by_gap(selected, header, cache)


# Сами критерии - здесь, функциями (см. докстринг вверху файла). Имя листа,
# заголовок и текст для дайджеста - в selections.py, чтобы не дублировать
# между этим скриптом и send_digest.py.
BUILDERS = {
    "top_gap": build_top_gap,
    "budget_1m": build_budget_1m,
    "one_owner": build_one_owner,
    "heavy_luxury": build_heavy_luxury,
    "polo_rio_solyaris": build_polo_rio_solyaris,
}


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)

    source = spreadsheet.worksheet(SOURCE_SHEET)
    header, data_rows = _load(source)
    if not header:
        print(f"Лист '{SOURCE_SHEET}' пуст.")
        return

    missing = [c for c in ("price_current", "autoru_price_low", "autoru_price_high") if c not in header]
    if missing:
        print(f'ВНИМАНИЕ: не нашёл колонки {missing} в "{SOURCE_SHEET}" - '
              f'"% below mkt" посчитать не получится, срезы 1 и 2 будут пустыми.')

    # Индекс колонки "% below mkt" в выходных срезах - перезаписываем её
    # вычисленным значением (см. _write_gap), дописываем в конец header,
    # если такой колонки в lots_current_month вообще нет.
    if PERCENT_BELOW_MKT_COL in header:
        gap_col_idx = header.index(PERCENT_BELOW_MKT_COL)
    else:
        gap_col_idx = len(header)
        header.append(PERCENT_BELOW_MKT_COL)

    def _write_gap(rows):
        cache = {}
        out = []
        for row in rows:
            row = list(row)
            while len(row) <= gap_col_idx:
                row.append("")
            gap = _compute_gap(row, header, cache)
            row[gap_col_idx] = format_gap(gap)
            out.append(row)
        return out

    for item in selections.SELECTIONS:
        sheet_name = item["sheet"]
        builder = BUILDERS[item["key"]]
        cache = {}
        selected_rows = _write_gap(builder(header, data_rows, cache))

        try:
            target = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            target = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(header))

        out_rows = [header] + selected_rows
        target.clear()
        target.update(range_name="A1", values=out_rows)

        print(f"{sheet_name}: {len(selected_rows)} лотов (из {len(data_rows)})")

    print("\nГотово. Все срезы пересобраны.")


if __name__ == "__main__":
    run()