# -*- coding: utf-8 -*-
r"""
Для строк листа "lots_processed", где пусто хотя бы одно из brand/name/year,
пытается достать эти поля из текста title - каскадом методов по убыванию
надёжности:

  год:    явные лейблы ("год выпуска:", "год изготовления:") -> "N года
          выпуска" -> "N г.в." -> голое "Nг"
  бренд/
  модель: явные лейблы ("марка:"/"модель:"/"марка/модель:") -> позиционная
          эвристика (бренд+модель в начале строки без лейблов) + разбивка
          по словарю известных брендов (латиница + кириллица)

Пишет только в ПУСТЫЕ ячейки - уже заполненные decoder'ом значения не
трогает. То, что не удалось распознать ни одним методом, остаётся пустым -
это осознанно: лучше не записывать ничего, чем записать наугад неверный
бренд/модель.

Работает напрямую с листом "lots_processed" через gspread (ищет колонки
по именам в шапке) - "lots" не трогает вообще.
"""
import re

import gspread
from google.oauth2.service_account import Credentials

import config
import sheets_writer

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "lots_processed"

CURRENT_YEAR = 2026  # для валидации диапазона года; можно заменить на datetime.now().year


# ---------------------------------------------------------------- ГОД ----

YEAR_PATTERNS = [
    r"год[а]?\s+(?:выпуска|изготовления)\s*[:\-–—]?\s*(\d{4})",
    r"(\d{4})\s*года?\s*выпуска",
    r"(\d{4})\s*года?\b",
    r"(\d{4})\s*г\.?\s*в\.?\b",
    r"(\d{4})\s*г\b",
]
YEAR_PATTERNS = [re.compile(p, re.IGNORECASE) for p in YEAR_PATTERNS]


def extract_year(title):
    for pattern in YEAR_PATTERNS:
        m = pattern.search(title)
        if m:
            year = int(m.group(1))
            if 1960 <= year <= CURRENT_YEAR + 1:
                return str(year)
    return None


# ------------------------------------------------------- БРЕНД/МОДЕЛЬ ----

# (канонiчное_имя, [алиасы кириллицей/латиницей, КАК ОНИ ВСТРЕЧАЮТСЯ В ТЕКСТЕ])
# Список не претендует на полноту - расширяется по мере появления
# нераспознанных случаев в lots_missing_info.
BRAND_ALIASES = [
    ("Mitsubishi", ["МИЦУБИСИ", "МИЦУБИШИ", "MITSUBISHI"]),
    ("Nissan", ["НИССАН", "NISSAN"]),
    ("Volkswagen", ["ФОЛЬКСВАГЕН", "VOLKSWAGEN", "VW"]),
    ("Kia", ["КИА", "KIA", "KIA"]),
    ("Ford", ["ФОРД", "FORD"]),
    ("Toyota", ["ТОЙОТА", "TOYOTA"]),
    ("BMW", ["БМВ", "BMW"]),
    ("Chevrolet", ["ШЕВРОЛЕ", "ШЕВТОЛЕ", "CHEVROLET", "CHEVTOLET"]),
    ("Skoda", ["ШКОДА", "SKODA"]),
    ("Opel", ["ОПЕЛЬ", "ОПЕЛ", "OPEL"]),
    ("Honda", ["ХОНДА", "HONDA"]),
    ("Hyundai", ["ХЕНДЭ", "ХЕНДАЙ", "ХУНДАЙ", "HYUNDAI"]),
    ("Mazda", ["МАЗДА", "MAZDA"]),
    ("Lexus", ["ЛЕКСУС", "LEXUS"]),
    ("Audi", ["АУДИ", "AUDI"]),
    ("Renault", ["РЕНО", "RENAULT"]),
    ("Citroen", ["СИТРОЕН", "CITROEN"]),
    ("Subaru", ["СУБАРУ", "SUBARU"]),
    ("SsangYong", ["ССАНГ ЕНГ", "ССАНГЙОНГ", "САНГЙОНГ", "SSANGYONG", "SSANG YONG"]),
    ("Peugeot", ["ПЕЖО", "PEUGEOT"]),
    ("Lada", ["ВАЗ", "ЛАДА", "LADA"]),
    ("GAZ", ["ГАЗ"]),
    ("UAZ", ["УАЗ"]),
    ("Geely", ["ДЖИЛИ", "ГИЛИ", "GEELY"]),
    ("Chery", ["ЧЕРИ", "CHERY"]),
    ("Great Wall", ["ГРЕЙТ ВОЛЛ", "GREAT WALL"]),
    ("Haval", ["ХАВЕЙЛ", "ХАВАЛ", "HAVAL"]),
    ("Land Rover", ["ЛЕНД РОВЕР", "ЛАНД РОВЕР", "LAND ROVER"]),
    ("Mercedes-Benz", ["МЕРСЕДЕС-БЕНЦ", "МЕРСЕДЕС", "MERCEDES-BENZ", "MERCEDES", "BENZ"]),
    ("Porsche", ["ПОРШЕ", "PORSCHE"]),
    ("Smart", ["СМАРТ", "SMART"]),
    ("Acura", ["АКУРА", "ACURA"]),
    ("Vortex", ["ВОРТЕКС", "VORTEX"]),
    ("Lifan", ["ЛИФАН", "LIFAN"]),
    ("JAC", ["ДЖАК", "JAC"]),
    ("Exeed", ["ЭКСИД", "EXEED"]),
    ("Datsun", ["ДАТСУН", "DATSUN"]),
    ("Infiniti", ["ИНФИНИТИ", "INFINITI"]),
    ("Jaguar", ["ЯГУАР", "JAGUAR"]),
    ("Jeep", ["ДЖИП", "JEEP"]),
    ("Mini", ["МИНИ", "MINI"]),
    ("Volvo", ["ВОЛЬВО", "VOLVO"]),
    ("Saab", ["СААБ", "SAAB"]),
    ("Fiat", ["ФИАТ", "FIAT", "FIAT PROFESSIONAL"]),
    ("Alfa Romeo", ["АЛЬФА РОМЕО", "ALFA ROMEO"]),
    ("Dodge", ["ДОДЖ", "DODGE"]),
    ("Cadillac", ["КАДИЛЛАК", "CADILLAC"]),
    ("Chrysler", ["КРАЙСЛЕР", "CHRYSLER"]),
    ("Daewoo", ["ДЭУ", "DAEWOO"]),
    ("Moskvich", ["МОСКВИЧ"]),
    ("Izh", ["ИЖ"]),
]

# Плоский словарь: нормализованный (upper, без лишних пробелов) алиас -> каноническое имя.
# Сортируем по убыванию длины алиаса в словах, чтобы многословные
# ("LAND ROVER", "FIAT PROFESSIONAL") матчились раньше однословных.
_ALIAS_MAP = {}
for canonical, aliases in BRAND_ALIASES:
    for alias in aliases:
        _ALIAS_MAP[alias.upper()] = canonical
_ALIASES_BY_LENGTH = sorted(_ALIAS_MAP.keys(), key=lambda a: -len(a.split()))

LABEL_STRIP_WORDS = [
    "АВТОТРАНСПОРТНОЕ СРЕДСТВО",
    "ТРАНСПОРТНОЕ СРЕДСТВО (ТС)",
    "ТРАНСПОРТНОЕ СРЕДСТВО",
    "ЛЕГКОВОЙ АВТОМОБИЛЬ",
    "ГРУЗОВОЙ АВТОМОБИЛЬ",
    "АВТОМОБИЛЬ ЛЕГКОВОЙ",
    "АВТОМОБИЛЬ МАРКИ",
    "АВТОМОБИЛЬ",
    "ЛЕГКОВОЙ",
    "ГРУЗОВОЙ",
    "ТС",
]

# Останавливаем захват текста на следующей пунктуации ИЛИ на начале
# следующего служебного поля (VIN, год, гос.номер и т.п.) - без этого
# "модель: ARRIZO 8 VIN: LVVD..." захватывало бы VIN в модель, если перед
# VIN не было запятой (частый случай в этих текстах).
_STOP_LOOKAHEAD = (
    r"(?=,|;|\.|$|"
    r"\bVIN\b|\bвин\b|идентификационный|"
    r"\bгод[а]?\b|\bг\.?\s*в\.?\b|\bгос\b|\bцвет\b|кузов|"
    r"разрешенная|масса)"
)

MARKA_MODEL_RE = re.compile(
    # Разделитель между "марка" и "модель" - слэш ("марка/модель:") или
    # запятая ("марка, модель:" - оба слова как единый лейбл с пустой
    # первой половиной; без этого сама МАРКА (пустая) "утекала" бы в
    # захват MARKA_RE, а следом за ней - и вся МОДЕЛЬ).
    r"марка\s*[,/]\s*модель\s*[:\-–—]?\s*(.+?)" + _STOP_LOOKAHEAD, re.IGNORECASE
)
MARKA_RE = re.compile(r"марк[аи]\s*[:\-–—]?\s*(.+?)" + _STOP_LOOKAHEAD, re.IGNORECASE)
MODEL_RE = re.compile(r"модель\s*[:\-–—]?\s*(.+?)" + _STOP_LOOKAHEAD, re.IGNORECASE)

VIN_TOKEN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{11,17}\b", re.IGNORECASE)


def _clean_model_text(model, year=None):
    """Подчищает уже извлечённый текст модели: обрезает на VIN-подобном
    токене и вырезает год, если они всё же затесались внутрь (актуально
    для позиционной эвристики, где нет явного лейбла-стоппера)."""
    if not model:
        return model
    m = VIN_TOKEN_RE.search(model)
    if m:
        model = model[: m.start()]
    if year:
        model = re.sub(r"\b" + re.escape(year) + r"\b", "", model)
    return re.sub(r"\s+", " ", model).strip(" ,.-–—") or None


def _split_brand_model(text):
    """
    Ищет в начале строки известный бренд (по словарю, многословные варианты
    первыми) и возвращает (бренд_канонический, остаток_строки_как_модель)
    либо (None, None), если ни один алиас не совпал.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    upper = normalized.upper()
    for alias in _ALIASES_BY_LENGTH:
        if upper == alias or upper.startswith(alias + " "):
            canonical = _ALIAS_MAP[alias]
            model = normalized[len(alias):].strip(" ,.-–—")
            return canonical, model or None
    return None, None


def _strip_leading_generic_words(text):
    """Итеративно срезает служебные слова/фразы с начала строки - в том
    числе несколько подряд (например, 'Транспортное средство: Легковой
    автомобиль, OPEL...' - оба сегмента служебные, бренд идёт только
    третьим)."""
    text = text.strip()
    changed = True
    while changed:
        changed = False
        upper = text.upper()
        for word in LABEL_STRIP_WORDS:
            if upper.startswith(word):
                text = text[len(word):].lstrip(" :,-–—").strip()
                changed = True
                break
    return text


def extract_brand_model(title):
    """
    Возвращает (brand, model, method), method - для логов/отладки:
    "labeled" / "positional" / None (не распознано).
    """
    year = extract_year(title)  # нужен здесь же для очистки модели от даты

    # 1) явный комбинированный лейбл "марка/модель:"
    m = MARKA_MODEL_RE.search(title)
    if m:
        brand, split_model = _split_brand_model(m.group(1))
        if brand:
            return brand, _clean_model_text(split_model, year), "labeled"

    # 2) раздельные лейблы "марка:" и "модель:"
    marka_m = MARKA_RE.search(title)
    model_m = MODEL_RE.search(title)
    if marka_m:
        brand, split_model = _split_brand_model(marka_m.group(1))
        if model_m:
            model = model_m.group(1)
        else:
            # отдельного "модель:" нет - модель, скорее всего, уже была
            # захвачена внутри самого "марка: X Y" как остаток после бренда
            model = split_model
        if brand:
            return brand, _clean_model_text(model, year), "labeled"
        raw_brand = re.sub(r"\s+", " ", marka_m.group(1)).strip()
        if raw_brand:
            return raw_brand.title(), _clean_model_text(model, year), "labeled-unmatched"

    # 3) позиционная эвристика: бренд+модель в начале строки без лейблов
    stripped = _strip_leading_generic_words(title)
    head = stripped.split(",")[0]
    brand, model = _split_brand_model(head)
    if brand:
        return brand, _clean_model_text(model, year), "positional"

    return None, None, None


def run():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(config.SPREADSHEET_ID).worksheet(SHEET_NAME)

    values = worksheet.get_all_values()
    if not values:
        print(f"Лист '{SHEET_NAME}' пуст.")
        return

    header = values[0]
    data_rows = values[1:]

    required = ["brand", "name", "year", "title"]
    for field in required:
        if field not in header:
            print(f'В шапке не нашёл колонку "{field}".')
            return

    brand_idx = header.index("brand")
    name_idx = header.index("name")
    year_idx = header.index("year")
    title_idx = header.index("title")

    stats = {"labeled": 0, "positional": 0, "year_only": 0, "unresolved": 0, "untouched": 0}

    for row in data_rows:
        # выравниваем длину строки до ширины шапки, чтобы не словить IndexError
        while len(row) < len(header):
            row.append("")

        missing_brand = not row[brand_idx].strip()
        missing_name = not row[name_idx].strip()
        missing_year = not row[year_idx].strip()

        if not (missing_brand or missing_name or missing_year):
            stats["untouched"] += 1
            continue

        title = row[title_idx]
        changed = False

        if missing_year:
            year = extract_year(title)
            if year:
                row[year_idx] = year
                changed = True

        if missing_brand or missing_name:
            brand, model, method = extract_brand_model(title)
            if brand and missing_brand:
                row[brand_idx] = brand
                changed = True
            if model and missing_name:
                row[name_idx] = model
                changed = True
            if method in ("labeled", "labeled-unmatched"):
                stats["labeled"] += 1
            elif method == "positional":
                stats["positional"] += 1
            elif not brand:
                stats["unresolved"] += 1

        if not changed and not (missing_brand or missing_name) and missing_year:
            stats["year_only"] += 1

    # Лист перезаписывается целиком из прочитанных СТРОК - без этого все
    # числа стали бы текстом (см. sheets_writer.NUMERIC_COLUMNS).
    sheets_writer.numify_rows(header, data_rows)
    out_rows = [header] + data_rows
    worksheet.update(range_name="A1", values=out_rows)

    print("Готово.")
    print(f"  Найдено по явным лейблам (марка:/модель:): {stats['labeled']}")
    print(f"  Найдено позиционной эвристикой: {stats['positional']}")
    print(f"  Не распознано ни одним методом (бренд/модель): {stats['unresolved']}")
    print(f"  Строк без пропусков (не трогали): {stats['untouched']}")


if __name__ == "__main__":
    run()