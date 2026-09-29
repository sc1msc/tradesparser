# -*- coding: utf-8 -*-
r"""
Строит сразу несколько тематических срезов из "lots_current_month" -
каждый на свой лист. Работает напрямую через gspread (та же схема, что у
build_lots_missing_info.py и остальных build_*.py). В самом
"lots_current_month" пишет ровно одну колонку - "% below mkt" (см. ниже),
остальное только читает.

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
и price_current (см. _compute_gap) и пишем:
  - в колонку "% below mkt" листа lots_current_month - это основная
    колонка, по которой лоты смотрят в самой таблице. Раньше ни один
    скрипт её не заполнял: там лежали когда-то вписанные значения вида
    "4%", не связанные с autoru_price_* и не обновлявшиеся при
    переоценке, а у новых оценённых лотов было пусто. Пишется здесь, а не
    в build_lots_current_month.py, потому что этот шаг идёт ПОСЛЕ оценки
    Auto.ru (evaluate_autoru_browser.py) - значит, видит свежие оценки.
    Формулу в таблице ставить бесполезно: build_lots_current_month.py
    перезаписывает лист значениями на каждом прогоне;
  - в ту же колонку выходных срезов (см. _write_gap) - по ней
    send_digest.py подписывает лоты.

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
import selections
import sheets_writer

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

# Ключевые слова, по которым лот выглядит как повреждённый/неисправный -
# такие лоты исключаем из "самый большой зазор от рынка": там огромный
# дисконт объясняется не выгодой, а состоянием автомобиля (Auto.ru же
# оценивает исправный авто того же года/модели, отсюда и ложный "разрыв").
# Список - первое приближение по тому, что реально встречалось в title;
# расширяйте по мере обнаружения новых выбросов.
DAMAGE_KEYWORDS = [
    "ДТП", "НЕИСПРАВН", "НЕ НА ХОДУ", "НЕ НАХОДУ", "БИТ", "АВАРИЙН",
    "ГОДНЫЕ ОСТАТКИ", "ГОДНЫЕ ОСТАНКИ", "УТИЛИЗАЦ", "ТРЕБУЕТ РЕМОНТА",
    "ПОСЛЕ ПОЖАРА", "СГОРЕВШ", "ЗАТОПЛЕН", "КОНСТРУКТИВНАЯ ГИБЕЛЬ",
]


def _looks_damaged(title):
    upper = (title or "").upper()
    return any(kw in upper for kw in DAMAGE_KEYWORDS)


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
    if value is None or value == "":
        return None
    cleaned = str(value).replace("%", "").replace(",", ".").replace(" ", "").replace(" ", "").strip()
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


def gap_percent(price_current, autoru_price_low, autoru_price_high):
    """% below mkt = (market_mid - price_current) / market_mid * 100.
    Значения - как в листе (текст, запятая). None, если цена или вилка
    Авто.ру не заполнены (лот ещё не оценён или market_mid <= 0 - защита
    от деления на ноль/мусора). Отдельной функцией - её же зовёт
    send_digest.py, когда пересчитывает цену публичного предложения на
    момент отправки."""
    price_current = _to_float(price_current)
    low = _to_float(autoru_price_low)
    high = _to_float(autoru_price_high)
    if price_current is None or low is None or high is None:
        return None
    market_mid = (low + high) / 2
    if market_mid <= 0:
        return None
    return (market_mid - price_current) / market_mid * 100


def _compute_gap(row, header, cache):
    return gap_percent(
        _get(row, header, cache, "price_current"),
        _get(row, header, cache, "autoru_price_low"),
        _get(row, header, cache, "autoru_price_high"),
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

    # "% below mkt" в самом lots_current_month - одним запросом, всей
    # колонкой (числом, в процентных пунктах: 12.3 = 12,3%).
    gaps = []
    cache = {}
    for row in data_rows:
        gap = _compute_gap(row, header, cache)
        gaps.append([round(gap, 1) if gap is not None else ""])
    if gap_col_idx + 1 > source.col_count:
        source.add_cols(gap_col_idx + 1 - source.col_count)
    first = gspread.utils.rowcol_to_a1(1, gap_col_idx + 1)
    last = gspread.utils.rowcol_to_a1(len(data_rows) + 1, gap_col_idx + 1)
    source.update(range_name=f"{first}:{last}", values=[[PERCENT_BELOW_MKT_COL]] + gaps)
    filled = sum(1 for g in gaps if g[0] != "")
    print(f"{SOURCE_SHEET}: '% below mkt' посчитан для {filled} из {len(data_rows)} лотов "
          f"(у остальных нет оценки Auto.ru или цены)")

    def _write_gap(rows):
        cache = {}
        out = []
        for row in rows:
            row = list(row)
            while len(row) <= gap_col_idx:
                row.append("")
            gap = _compute_gap(row, header, cache)
            row[gap_col_idx] = round(gap, 1) if gap is not None else ""
            out.append(row)
        # Строки прочитаны из листа строками - числа пишем числами
        # (см. sheets_writer.NUMERIC_COLUMNS).
        return sheets_writer.numify_rows(header, out)

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