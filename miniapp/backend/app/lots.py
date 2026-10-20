# -*- coding: utf-8 -*-
r"""
Логика ленты: текущая цена/дедлайн, "% below mkt", видимость, фильтры,
сортировка, фасеты для экрана фильтров.

ГЛАВНОЕ - цена и дедлайн считаются в момент запроса, а не при импорте:
у "публичного предложения" цена ступенчато снижается по графику периодов,
и дедлайн, который надо показать пользователю - конец приёма заявок
ТЕКУЩЕГО периода, а не последнего (так же показывает и сам сайт). Импорт
раз в сутки, а период может смениться в любой момент - поэтому текущий
период выбирается по часам сервера при каждом запросе.

Сам расчёт - bidding_schedule.effective_price_and_deadline, ТОТ ЖЕ, что у
пайплайна и дайджеста (модуль копируется в Docker-образ, как lot_metrics):
цена 0 в графике = "не указана" (берётся price_current), а если график
кончился раньше окончательного дедлайна - заявки принимаются по цене с
сайта до окончательного дедлайна. Поэтому applications_end, который
присылает export_to_miniapp.py для публичного предложения - ОКОНЧАТЕЛЬНЫЙ
дедлайн (bidding_schedule.final_deadline), а не текущего периода.

"% below mkt" - та же формула, что у дайджеста (lot_metrics.gap_percent),
но от ТЕКУЩЕЙ цены периода. С фронта процент никогда не принимается.

Все даты сайта торгов - московское время без зоны; сравниваем с "сейчас"
тоже по Москве (UTC+3 круглый год, переходов на летнее время нет).

МАШИНА И ЛОТЫ. Одна машина (VIN) бывает в нескольких лотах:
  - параллельно - одни и те же торги опубликованы на нескольких площадках
    (ЭТП и "вне ЭТП"): в ленте одна карточка - лот с наименьшей ценой,
    затем ближайшим дедлайном, предпочтительно на ЭТП (_primary_key);
    остальные - на экране лота "эта машина на других площадках";
  - последовательно - торги не состоялись, машину выставили снова: это
    история торгов машины на экране лота.
Связываем только лоты "одна машина" с VIN из 17 знаков (lot["car"]);
мультилоты и лоты без VIN живут сами по себе.

ИЗБРАННОЕ СЛЕДУЕТ ЗА МАШИНОЙ (решение 01.10.2026: пользователь покупает
актив, а не конкретные торги). В favorites хранится и lot_id, и VIN;
карточка в избранном показывает актуальный лот машины: открытый, если он
есть (в том числе новый - "перевыставлен"), иначе последний закрытый с
итогом торгов. Через FAVORITE_ARCHIVE_DAYS после дедлайна закрытая
карточка уходит в "Архив".

Объём - сотни лотов (до 5-10 тыс. при расширении географии), поэтому вся
выборка/сортировка идёт в памяти по кэшу лотов: это проще SQL-конструктора
фильтров и заведомо быстро. Кэш сбрасывается после каждого импорта.
"""
import collections
import datetime
import json
import re
import threading
import urllib.parse

import bidding_schedule
import etp_lots
import etp_status
import lot_metrics

from . import catalog, db

MSK = datetime.timezone(datetime.timedelta(hours=3))
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Короткие бренды/слова, которые пишем целиком заглавными ("BMW", а не "Bmw").
UPPER_WORDS = {"BMW", "UAZ", "GAZ", "VAZ", "MG", "BYD", "GMC", "DS", "JAC", "FAW", "GAC", "BAIC", "SWM", "MINI", "AMG", "GWM", "ZAZ"}

# Синонимы марок: Авто.ру пишет "VAZ", таблица - "Lada" и т.п. Ключ - после
# замены "_" на пробел и перевода в верхний регистр.
BRAND_ALIASES = {
    "VAZ": "LADA", "ВАЗ": "LADA", "ЛАДА": "LADA",
    "MERCEDES": "MERCEDES-BENZ",
    "SSANG YONG": "SSANGYONG",
    "CHERYEXEED": "EXEED",
    "MOSCVICH": "МОСКВИЧ", "MOSKVICH": "МОСКВИЧ",
    "ГАЗ": "GAZ", "УАЗ": "UAZ",
}
BRAND_LABELS = {"SSANGYONG": "SsangYong", "LIXIANG": "LiXiang", "ROLLS-ROYCE": "Rolls-Royce"}

# Известные марки (ключ - как в BRAND_ALIASES/ленте) и их написания в
# документах торгов. Нужны, когда в поле марки попал кусок фразы ("Тс:
# Фольксваген", "И Модель: Ссанг Енг Рекстон", "Чанган Cs 35"): тогда марку
# ищем в тексте по этому списку, а то, что после неё, считаем моделью.
KNOWN_BRANDS = {
    "AUDI", "BAIC", "BELGEE", "BMW", "BYD", "CADILLAC", "CHANGAN", "CHERY", "CHEVROLET",
    "CHRYSLER", "CITROEN", "DAEWOO", "DATSUN", "DODGE", "DONGFENG", "EXEED", "FAW", "FIAT",
    "FORD", "FUSO", "GAZ", "GEELY", "GENESIS", "GREAT WALL", "GWM", "HAVAL", "HONDA",
    "HYUNDAI", "INFINITI", "ISUZU", "IVECO", "JAC", "JAECOO", "JAGUAR", "JEEP", "JETOUR",
    "KAIYI", "KIA", "LADA", "LAND ROVER", "LEXUS", "LIFAN", "LIVAN", "LIXIANG", "MAZDA",
    "MERCEDES-BENZ", "MG", "MINI", "MITSUBISHI", "МОСКВИЧ", "NISSAN", "OMODA", "OPEL",
    "PEUGEOT", "PORSCHE", "RENAULT", "ROLLS-ROYCE", "SAAB", "SKODA", "SMART", "SSANGYONG", "SUBARU",
    "SUZUKI", "SWM", "TANK", "TESLA", "TOYOTA", "UAZ", "VOLKSWAGEN", "VOLVO", "VORTEX",
    "WEY", "ZAZ", "ZOTYE",
}
BRAND_SPELLINGS = {
    "ЧАНГАН": "CHANGAN", "ЧЕРИ": "CHERY", "ДЖИЛИ": "GEELY", "ХАВАЛ": "HAVAL", "ХАВЕЙЛ": "HAVAL",
    "ХЕНДЭ": "HYUNDAI", "ХЕНДАЙ": "HYUNDAI", "ХУНДАЙ": "HYUNDAI", "ХЁНДЭ": "HYUNDAI",
    "КИА": "KIA", "ФОРД": "FORD", "ТОЙОТА": "TOYOTA", "РЕНО": "RENAULT", "ШКОДА": "SKODA",
    "ФОЛЬКСВАГЕН": "VOLKSWAGEN", "НИССАН": "NISSAN", "МИЦУБИСИ": "MITSUBISHI",
    "МИЦУБИШИ": "MITSUBISHI", "МАЗДА": "MAZDA", "ПЕЖО": "PEUGEOT", "СИТРОЕН": "CITROEN",
    "ШЕВРОЛЕ": "CHEVROLET", "ОПЕЛЬ": "OPEL", "БМВ": "BMW", "МЕРСЕДЕС-БЕНЦ": "MERCEDES-BENZ",
    "МЕРСЕДЕС БЕНЦ": "MERCEDES-BENZ", "МЕРСЕДЕС": "MERCEDES-BENZ", "АУДИ": "AUDI",
    "ЛЕКСУС": "LEXUS", "ХОНДА": "HONDA", "СУБАРУ": "SUBARU", "СУЗУКИ": "SUZUKI",
    "ВОЛЬВО": "VOLVO", "ДЭУ": "DAEWOO", "ДЕУ": "DAEWOO", "ЛИФАН": "LIFAN", "ИНФИНИТИ": "INFINITI",
    "ПОРШЕ": "PORSCHE", "ССАНГ ЕНГ": "SSANGYONG", "ССАНГ ЙОНГ": "SSANGYONG",
    "ССАНГЙОНГ": "SSANGYONG", "ОМОДА": "OMODA", "ДЖЕТУР": "JETOUR", "ЭКСИД": "EXEED",
    "ЛЕНД РОВЕР": "LAND ROVER", "ЛЭНД РОВЕР": "LAND ROVER", "ЯГУАР": "JAGUAR", "ДЖИП": "JEEP",
    "ФИАТ": "FIAT", "ГАЗ": "GAZ", "УАЗ": "UAZ", "ВАЗ": "LADA", "ЛАДА": "LADA",
    "ТЕСЛА": "TESLA", "ГРЕЙТ ВОЛЛ": "GREAT WALL", "ЗАЗ": "ZAZ",
    # аудит справочника 18.10.2026 (решение владельца)
    "КАДИЛАК": "CADILLAC", "КАДДИЛАК": "CADILLAC", "ЧЕРРИ": "CHERY",
    "РОЛЛС-РОЙС": "ROLLS-ROYCE", "РОЛЛС РОЙС": "ROLLS-ROYCE", "ROLLS ROYCE": "ROLLS-ROYCE",
    "SSANG YONG": "SSANGYONG", "MERCEDES": "MERCEDES-BENZ", "MERCEDES BENZ": "MERCEDES-BENZ",
    "VAZ": "LADA", "CHERYEXEED": "EXEED",
}
_BRAND_NAMES = sorted(set(KNOWN_BRANDS) | set(BRAND_SPELLINGS), key=len, reverse=True)
_BRAND_FIND_RE = re.compile(
    r"(?<![A-ZА-ЯЁ0-9])(" + "|".join(re.escape(n) for n in _BRAND_NAMES) + r")(?![A-ZА-ЯЁ0-9])")


def find_brand(text):
    """Первая известная марка в тексте -> (ключ, текст после неё) или (None, "")."""
    upper = " ".join((text or "").upper().replace("Ё", "Е").replace("_", " ").split())
    m = _BRAND_FIND_RE.search(upper)
    if not m:
        return None, ""
    key = BRAND_SPELLINGS.get(m.group(1), m.group(1))
    original = " ".join((text or "").replace("_", " ").split())
    return key, original[m.end():] if len(original) == len(upper) else upper[m.end():]
# Настоящая марка - короткое слово из букв/цифр/дефисов. Всё прочее ("$7C",
# "И МОДЕЛЬ: ССАНГ ЕНГ ...", целый абзац из title) - мусор разбора текста:
# такой лот остаётся в ленте и в поиске, но без марки в фильтре.
BRAND_RE = re.compile(r"^[A-ZА-Я][A-ZА-Я0-9\- ]{0,19}$")
# Хвосты, после которых в модели из разбора title идёт уже не модель:
# "Atlas года выпуска", "Largus VIN", "s-max 2006 Wfos...", "H-100 г.в.".
MODEL_JUNK_RE = re.compile(r"(\s|^)(VIN|ГОДА|Г\.В|ГОД|МОДЕЛЬ|19\d\d|20\d\d)(\W|$).*", re.IGNORECASE)

PLATE_RE = re.compile(r"\s*[АВЕКМНОРСТУХABEKMHOPCTYX]\d{3}[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\d{2,3}(?:RUS)?(?![0-9A-ZА-Я])", re.IGNORECASE)
KLASSE_RE = re.compile(r"^([A-Z0-9]+) KLASSE( AMG)?$", re.IGNORECASE)
# Классы Mercedes-Benz - и коды Авто.ру ("GLA_CLASS", "S_CLASS_MAYBACH", "GL_KLASSE_AMG"), и модели
# из названия лота ("E 200 D", "GLA 200", "E-CLASS", "E-класс" - после замены кириллических двойников
# это "E-Kлacc", "ML 350"): буквы класса, за ними слово класса
# или цифры двигателя. "ML" - это M-класс. Vito, Sprinter и прочие без цифр сюда не попадают.
MB_CLASS_RE = re.compile(
    r"^(MAYBACH\s+)?(A|B|C|E|G|R|S|V|X|CL|CLA|CLC|CLK|CLS|GL|GLA|GLB|GLC|GLE|GLK|GLS|ML|M|SL|SLC|SLK)"
    r"(?:[\s-]*(?:CLASS|KLASSE|K[ЛL][AА][CС][CС])(?![A-ZА-Я])|[\s-]?\d{2,3}(?![0-9]))(.*)$", re.IGNORECASE)
BMW_SERIES_RE = re.compile(r"^(\d)ER$", re.IGNORECASE)

CYR_LOOKALIKES = str.maketrans("АВЕКМНОРСТУХаеокрсух", "ABEKMHOPCTYXaeokpcyx")

TRADE_AUCTION = "auction"
TRADE_PUBLIC_OFFER = "public_offer"

SORTS = ("new", "gap", "price_asc", "price_desc", "deadline")
# Характеристики модификации с Авто.ру (autoru_valuation.ENGINE_TYPES/TRANSMISSIONS/DRIVES) -
# порядок вариантов в фильтрах. Неизвестные значения идут в конец.
FUELS = ("бензин", "дизель", "гибрид", "электро", "газ")
GEARBOXES = ("автомат", "робот", "вариатор", "механика")
DRIVES = ("передний", "задний", "полный")

# Через сколько дней после дедлайна закрытая карточка избранного уходит в архив.
FAVORITE_ARCHIVE_DAYS = 60
# Статусы лотов из избранного после дедлайна перепроверяются на сайте (см.
# watchlist), пока не появится итог, но не дольше этого срока и не чаще раза
# в WATCH_RECHECK_HOURS.
WATCH_DAYS = 60
WATCH_RECHECK_HOURS = 20

# Итог торгов по тексту статуса сайта. Порядок важен: "не состоялись"
# проверяем раньше "завершены".
OUTCOMES = (
    ("не состоял", "failed"),
    ("заверш", "done"),
    ("отмен", "cancelled"),
    ("аннулир", "cancelled"),
    ("приостанов", "suspended"),
    ("удал", "removed"),  # "Лот удалён с сайта" - призрак агрегатора (export_to_miniapp)
)
FINAL_OUTCOMES = {"failed", "done", "cancelled", "removed"}

_cache = {"lots": None}
_cache_lock = threading.Lock()


def now_msk():
    return datetime.datetime.now(MSK)


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(str(value).strip()[:19], DATE_FORMAT).replace(tzinfo=MSK)
    except ValueError:
        return None


def pretty_name(value):
    """'MERCEDES-BENZ' -> 'Mercedes-Benz', 'LAND ROVER' -> 'Land Rover',
    'G35'/'CR-V'/'BMW' остаются как есть. Бренды в листе записаны
    вразнобой ('KIA' и 'Kia') - приводим к одному виду."""
    words = []
    for word in (value or "").split():
        parts = []
        for part in word.split("-"):
            up = part.upper()
            if up in UPPER_WORDS or len(part) <= 2 or any(ch.isdigit() for ch in part):
                parts.append(up)
            else:
                parts.append(part[:1].upper() + part[1:].lower())
        words.append("-".join(parts))
    return " ".join(words)


def _norm_key(value):
    return " ".join((value or "").upper().replace("Ё", "Е").replace("_", " ").split())


def clean_brand(value):
    """-> (ключ, подпись) или ("", "") для мусора."""
    key = _norm_key(value)
    key = BRAND_ALIASES.get(key, key)
    key = BRAND_SPELLINGS.get(key, key)
    if not BRAND_RE.match(key):
        return "", ""
    if " " in key and key not in KNOWN_BRANDS:
        return "", ""  # "ЧАНГАН CS 35" - марка с моделью, разбирает resolve_brand_model
    return key, BRAND_LABELS.get(key) or pretty_name(key)


def resolve_brand_model(brand, model, title):
    """Марка и модель лота с дочисткой мусора из разбора текста:
    -> (ключ марки, подпись марки, модель для clean_model)."""
    key, label = clean_brand(brand)
    if key:
        return key, label, model
    # в поле марки - фраза: ищем в ней (и в модели) известную марку, хвост - модель
    for text in (brand, model):
        found, rest = find_brand(text)
        if found:
            return found, BRAND_LABELS.get(found) or pretty_name(found), _model_tail(found, rest) or model
    found, rest = find_brand(title)  # не нашли ни в марке, ни в модели - ищем в названии лота
    if found:
        return found, BRAND_LABELS.get(found) or pretty_name(found), model or _model_tail(found, rest)
    return "", "", ""


def _model_tail(brand_key, rest):
    """Хвост после марки -> модель: до первой запятой/скобки, без
    разделителей и повторного названия марки ("Чери/Chery Tiggo7" -> "Tiggo7")."""
    # «ГАЗ, модель: 3302, год выпуска...», «марки: LIVAN, модели: X6 PRO, ...» - модель после слова «модель»
    rest = re.sub(r"^[\s,;:.]*(модел[а-я]*|model)\s*[:–-]?\s*", "", rest or "", flags=re.IGNORECASE)
    rest = re.split(r"[,;(]", rest, maxsplit=1)[0]
    words = rest.replace("/", " ").split()
    while words and BRAND_SPELLINGS.get(words[0].upper(), words[0].upper()) == brand_key:
        words = words[1:]
    return " ".join(words).strip(" :–-")


def clean_model(value, brand_label):
    model = " ".join((value or "").replace("_", " ").split())
    model = re.sub(r"^\W*(модель|model|тс|т\.с\.)\s*[:–-]?\s*", "", model, flags=re.IGNORECASE)
    model = re.sub(r"^\W*(модель|model)\s*[:–-]?\s*", "", model, flags=re.IGNORECASE)
    model = re.sub(r"^\([^)]*\)\s*", "", model)  # "(lada) 2190 Granta" -> "2190 Granta"
    model = re.sub(r"\s*\[.*$", "", model)  # "NUOVO DUCATO [NUOVO DUCATO 2006 (2006-2014)]" -> "NUOVO DUCATO"
    # Документы торгов смешивают в одном слове кириллицу с латиницей
    # ("Sаnта FЕ") - в словах, где есть латиница, двойники меняем на латиницу. Так же короткие слова
    # с цифрами: «Х5» кириллицей - это X5 (аудит справочника 18.10.2026).
    model = " ".join(w.translate(CYR_LOOKALIKES)
                     if re.search("[A-Za-z]", w) or (len(w) <= 4 and re.search(r"\d", w)) else w
                     for w in model.split())
    # Модель из Autodoc иногда начинается с марки ("Audi A6 ...") - убираем повтор.
    if brand_label and _norm_key(model).startswith(_norm_key(brand_label) + " "):
        model = model[len(brand_label):].strip()
    # ...или с хвоста марки: "MERCEDES BENZ E-CLASS" -> марка Mercedes, модель "BENZ E-CLASS"
    parts = re.split(r"[\s-]+", _norm_key(brand_label))
    if len(parts) > 1 and model.split() and _norm_key(model.split()[0]) in parts[1:]:
        model = " ".join(model.split()[1:])
    if _norm_key(brand_label) == "MERCEDES-BENZ":
        m = MB_CLASS_RE.match(model.strip().translate(CYR_LOOKALIKES))  # "Е-класс" кириллицей
        if m:
            tail = _norm_key(m.group(3)).split()
            return (f"{m.group(2).upper().replace('ML', 'M')}-класс" + (" Coupe" if "COUPE" in tail else "") + (" AMG" if "AMG" in tail else "")
                    + (" Maybach" if m.group(1) or "MAYBACH" in tail else ""))
    model = MODEL_JUNK_RE.sub("", model).strip(" ,.:;-")
    model = PLATE_RE.sub("", model).strip(" ,.:;-")  # "220695-04 У668МЕ797" - госномер не модель
    # непарная скобка от обрезанной фразы ("Pajero)"), парные ("2131 (4X4)") не трогаем
    if model.endswith(")") and model.count("(") < model.count(")"):
        model = model[:-1].strip()
    if model.startswith("(") and model.count("(") > model.count(")"):
        model = model[1:].strip()
    if len(model) > 25:
        return ""
    # коды Авто.ру: "M_KLASSE" -> "M-класс", "GL_KLASSE_AMG" -> "GL-класс AMG", "5ER" -> "5 серии"
    m = KLASSE_RE.match(model)
    if m:
        return f"{m.group(1).upper()}-класс" + (" AMG" if m.group(2) else "")
    m = BMW_SERIES_RE.match(model)
    if m:
        return f"{m.group(1)} серии"
    return pretty_name(model)


# ---------- каталог моделей Авто.ру ----------
# Марку и модель большинству лотов даёт Авто.ру (по VIN, вместе с оценкой) -
# коды вида FORD / FOCUS, BMW / 5ER: у модели одно написание. У лотов без
# оценки (нет VIN, Авто.ру не определил машину - ~11% на 06.10.2026) модель
# разобрана из названия лота: "Фокус", "Focus CB4", "219010 Granta", "Jb/rio".
# Такие модели привязываем к словарю Авто.ру (build_catalog): модели всех
# лотов с оценкой плюс выученные написания - у лота с оценкой есть и модель,
# разобранная из названия (title_model): "Солярис" у Hyundai -> SOLARIS.

_TRANSLIT = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "ZH", "З": "Z",
    "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "H", "Ц": "TS", "Ч": "CH", "Ш": "SH", "Щ": "SCH",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "YU", "Я": "YA",
})


def _skeleton(value):
    """Только латинские буквы и цифры, кириллица - транслитом: "219010 Granta" ->
    "219010GRANTA", "Гранта" -> "GRANTA"."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper().translate(_TRANSLIT))


def _consonants(skeleton):
    """Согласные - для написаний на слух: "Солярис"/SOLARIS -> SLRS,
    "Октавия"/OCTAVIA -> KTV, "Туарег"/TOUAREG -> TRG."""
    s = skeleton.replace("PH", "F").replace("C", "K").replace("Q", "K").replace("W", "V")
    return re.sub(r"[AEIOUY]", "", s)


def build_catalog(raw_lots):
    """Словарь из лотов с моделью от Авто.ру: {"codes": {марка: {код модели}},
    "alias": {(марка, скелет модели из названия): код}}."""
    codes = {}
    alias = {}
    for lot in raw_lots:
        if lot.get("model_source") != "autoru" or not lot.get("model"):
            continue
        key, _ = clean_brand(lot.get("brand"))
        if not key:
            continue
        code = lot["model"].strip().upper()
        codes.setdefault(key, set()).add(code)
        tkey, tlabel, traw = resolve_brand_model(lot.get("title_brand"), lot.get("title_model"), lot.get("title"))
        sk = _skeleton(clean_model(traw, tlabel)) if tkey == key else ""
        if sk and sk != _skeleton(code):
            alias.setdefault((key, sk), collections.Counter())[code] += 1
    return {"codes": codes, "alias": {k: c.most_common(1)[0][0] for k, c in alias.items()}}


def snap_model(brand_key, model, text, catalog):
    """Код модели Авто.ру для модели, разобранной из названия, или None."""
    codes = (catalog or {}).get("codes", {}).get(brand_key)
    if not codes:
        return None
    sk = _skeleton(model)
    if sk:
        exact = [c for c in codes if _skeleton(c) == sk]  # "Golf" - это GOLF, а не GOLF_R из выученных
        if exact:
            return exact[0]
        hit = catalog["alias"].get((brand_key, sk))
        if hit:
            return hit
        # код - часть разобранной модели ("Focus CB4", "219010 Granta", "Passat CC" -> PASSAT_CC)
        found = [c for c in codes if len(_skeleton(c)) >= 2 and _skeleton(c) in sk]
        if found:
            return max(found, key=lambda c: len(_skeleton(c)))
        # на слух - всей моделью или первым словом ("Солярис 1.6 GI АТ" -> SOLARIS)
        for part in (sk, _skeleton(model.split()[0])):
            cons = _consonants(part)
            found = [c for c in codes if len(cons) >= 3 and _consonants(_skeleton(c)) == cons]
            if len(found) == 1:
                return found[0]
        return None
    # модели нет - ищем код модели отдельным словом в тексте (название, описание)
    words = {_skeleton(w) for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or "")}
    found = [c for c in codes if len(_skeleton(c)) >= 3 and _skeleton(c) in words]
    return found[0] if len(found) == 1 else None


# Свежие данные, которые сервер читает сам (status_refresh.py), важнее выгрузки с ПК, пока не
# устарели: сервер проверяет публичные предложения несколько раз в день, ПК выгружает раз в сутки.
LIVE_MAX_AGE_HOURS = 30


def _fresh(value, now):
    dt = _parse_iso(value)
    return dt is not None and now - dt < datetime.timedelta(hours=LIVE_MAX_AGE_HOURS)


def _apply_live(lot, now=None):
    """live_* (карточка агрегатора) и etp_* (страница ЭТП) поверх выгрузки с ПК. Итог на ЭТП
    (завершены, не состоялись, отменены) - статус лота; «итоги подводятся» (приём заявок на ЭТП
    окончен, а агрегатор ещё пишет «идёт приём») - лот не в ленте (_etp_pending), но не закрыт:
    торги могут продолжиться, сервер проверит снова."""
    now = now or now_msk()
    if _fresh(lot.get("live_checked_at"), now):
        if lot.get("live_status"):
            lot["status"] = lot["live_status"]
        if lot.get("live_price") is not None:
            lot["price_current"] = lot["live_price"]
        if lot.get("live_periods"):
            try:
                lot["periods"] = json.loads(lot["live_periods"])
            except ValueError:
                pass
        if lot.get("live_end"):
            lot["applications_end"] = lot["live_end"]
    lot["photo_sets"] = _photo_sets(lot)
    lot["photos"] = lot["photo_sets"][0] if lot["photo_sets"] else []
    etp_fresh = _fresh(lot.get("etp_checked_at"), now)
    if etp_fresh and lot.get("etp_state") == "closed" and lot.get("etp_outcome") in etp_status.OUTCOME_TEXT:
        lot["status"] = etp_status.OUTCOME_TEXT[lot["etp_outcome"]]
    lot["_etp_pending"] = etp_fresh and lot.get("etp_state") == "pending"


def _proxied(url):
    """Фото с площадки, которая не пускает зарубежные адреса (МЭТС), - через наш сервер (GET /img)."""
    if url and etp_status.host(url) in etp_lots.PROXY_PHOTO_HOSTS:
        return "/img?u=" + urllib.parse.quote(url, safe="")
    return url


def _public_photo(p):
    return {**p, "full": _proxied(p.get("full")), "thumb": _proxied(p.get("thumb") or p.get("full"))}


def _photo_sets(lot):
    """Наборы фото лота по порядку предпочтения (с 16.10.2026). Лента отдаёт их все, а app.js берёт
    следующий набор, если фото текущего не открылось, - так у лота не бывает «сломанных» фото:
      1. фото со страницы площадки (etp_photos: ТоргГрупп - оригиналы, МЭТС и ЦДТ - знак площадки, но
         без знака агрегатора);
      2. фото из выгрузки (у лотов агрегатора - его копии с его водяным знаком).
    Фото МЭТС - двумя наборами: через наш сервер (/img: открывается и с VPN) и напрямую (если сервер
    МЭТС не пускает, у пользователя без VPN они всё равно откроются)."""
    own = lot.setdefault("_import_photos", lot.get("photos") or [])
    etp = []
    if lot.get("etp_photos"):
        try:
            etp = json.loads(lot["etp_photos"]) or []
        except ValueError:
            etp = []
        if etp and etp_lots.photo_host(etp[0].get("full")) not in etp_lots.REPLACE_PHOTO_HOSTS:
            etp = []
    sets = []
    for group in (etp, own):
        if not group:
            continue
        if etp_lots.photo_host(group[0].get("full")) in etp_lots.PROXY_PHOTO_HOSTS:
            sets.append([_public_photo(p) for p in group])
            sets.append([{**p, "thumb": p.get("thumb") or p.get("full")} for p in group])
        else:
            sets.append(group)
    return sets


PHOTO_RANK = {"original": 3, "platform": 2, "aggregator": 1, "other": 1}


def _photo_rank(lot):
    sets = lot.get("photo_sets") or []
    return PHOTO_RANK.get(etp_lots.photo_kind(sets[0][0].get("full")), 0) if sets and sets[0] else 0


def _borrow_car_photos(prepared, cars):
    """Лоту без фото - фото другого лота той же машины (тот же VIN: запись «вне ЭТП» тех же торгов,
    прошлые торги): это та же машина. Берём лучший набор (оригиналы, потом знак площадки, потом
    агрегатор)."""
    for lot in prepared:
        if lot["photo_sets"] or not lot["car"]:
            continue
        donor = max((o for o in cars.get(lot["car"], []) if o["photo_sets"] and not o.get("_photos_from")),
                    key=_photo_rank, default=None)
        if donor:
            lot["photo_sets"], lot["photos"], lot["_photos_from"] = donor["photo_sets"], donor["photos"], donor["lot_id"]


def photo_sources():
    """Сколько лотов ленты с какими фото (по первому фото): original - без водяных знаков,
    platform - со знаком площадки, aggregator - копии агрегатора с его знаком, none - без фото."""
    out = {"original": 0, "platform": 0, "aggregator": 0, "other": 0, "none": 0, "from_same_car": 0}
    for lot in load():
        if not lot.get("in_source"):
            continue
        photos = lot.get("photos") or []
        out[etp_lots.photo_kind(photos[0].get("full")) if photos else "none"] += 1
        out["from_same_car"] += bool(lot.get("_photos_from"))
    return out


SPEC_FIELDS = ("engine_type", "displacement", "power", "drive", "transmission")


def _prepare(lot, models_index=None):
    """Статичные (не зависящие от времени) производные поля - один раз на
    загрузку кэша. models_index - словарь моделей Авто.ру (build_catalog)."""
    _apply_live(lot)
    brand_key, brand, raw_model = resolve_brand_model(lot.get("brand"), lot.get("model"), lot.get("title"))
    if not brand_key:  # название вида "Автомобиль" - марку ищем в описании
        found, rest = find_brand(lot.get("description"))
        if found:
            brand_key, brand, raw_model = found, BRAND_LABELS.get(found) or pretty_name(found), _model_tail(found, rest)
    if brand_key and not (raw_model or "").strip():  # марка есть, модели нет - ищем её в названии после марки
        found, rest = find_brand(lot.get("title"))
        if found == brand_key:
            raw_model = _model_tail(found, rest)
    if lot.get("model_source") == "autoru":
        raw_model = catalog.code_to_model(raw_model)  # CR_V -> CR-V, X_TRAIL -> X-TRAIL
    model = clean_model(raw_model, brand) if brand else ""
    if brand_key and lot.get("model_source") != "autoru":
        code = snap_model(brand_key, model, f"{lot.get('title') or ''} {lot.get('description') or ''}", models_index)
        if code:
            model = clean_model(catalog.code_to_model(code), brand)
    # справочник: семейства (Niva, Priora...), единые подписи (RAV4, Santa Fe), ручные правки из базы
    brand_key, brand, model = catalog.normalize(brand_key, brand, model, lot, clean_brand)
    lot["brand_label"] = brand
    lot["model_label"] = model
    lot["brand_key"] = brand_key
    lot["model_key"] = _norm_key(model)
    lot["name"] = " ".join(x for x in (brand, model) if x) or (lot.get("title") or "Лот")[:60]
    lot["trade"] = TRADE_PUBLIC_OFFER if lot.get("is_public_offer") else TRADE_AUCTION
    lot["damage"] = lot_metrics.damage_keywords(lot.get("title"))
    # Тотальные повреждения (сгорела, на запчасти, разобрана): по тексту или по
    # проверке фото (check_damage_photos.py, вердикт total). Такие лоты прячет
    # галочка "Скрыть битые" - она в ленте включена по умолчанию.
    lot["photo_damage"] = (lot.get("photo_signs") or []) if lot.get("photo_verdict") == "total" else []
    lot["total_damage"] = bool(lot_metrics.total_damage_keywords(lot.get("title"))) or lot.get("photo_verdict") == "total"
    # тип лота (lot_metrics.lot_kind): мультилот - без процента к рынку и
    # с меткой; права требования/доли в ленту не попадают вовсе
    lot["kind"] = lot.get("lot_kind") or lot_metrics.LOT_CAR
    # Характеристик от рыночной оценки нет (нет VIN, оценка не нашла модель) - берём однозначное из
    # текста лота: «2.0 л, 150 л.с., АКПП», выписка из ПТС (lot_metrics.specs_from_text, 20.10.2026).
    # Только в пустые поля: оценку текст не перекрывает.
    if lot["kind"] == lot_metrics.LOT_CAR and not any(lot.get(k) for k in SPEC_FIELDS):
        found = lot_metrics.specs_from_text(f"{lot.get('title') or ''} {lot.get('description') or ''}")
        for k, v in found.items():
            if v is not None:
                lot[k] = v
    if lot["kind"] == lot_metrics.LOT_MULTILOT:
        # Марка/модель у мультилота - от одной из машин (Авто.ру по первому
        # VIN: лот из 17 Solaris выходил "Hyundai Santa FE"). Показываем
        # название лота с сайта и не кладём его в фильтр по марке.
        lot["brand_key"] = lot["model_key"] = ""
        lot["name"] = " ".join((lot.get("title") or "Мультилот").split())[:60]
    # Ключ машины: VIN лота "одна машина" (мультилоты и лоты без VIN не связываем).
    vin = (lot.get("vin") or "").strip().upper()
    lot["car"] = vin if lot["kind"] == lot_metrics.LOT_CAR and len(vin) == 17 else None
    lot["_off_etp"] = "вне этп" in (lot.get("platform") or "").lower()
    lot["_final_deadline"] = parse_dt(lot.get("applications_end"))
    lot["search_text"] = _norm_key(" ".join(
        str(x or "") for x in (brand, model, lot.get("title"), lot.get("vin"), lot.get("plate"))
    ))
    _search_index(lot, brand, model)
    # График: [[bid_end, price], ...] (формат листа, см. bidding_schedule).
    # Старые записи базы - списком словарей с карточки сайта.
    pairs = []
    for p in lot.get("periods") or []:
        if isinstance(p, dict):
            p = [p.get("bid_end") or p.get("end"), p.get("price")]
        if isinstance(p, (list, tuple)) and len(p) == 2 and parse_dt(p[0]):
            pairs.append([str(p[0])[:19], p[1]])
    pairs.sort(key=lambda pair: pair[0])
    lot["_periods_text"] = json.dumps(pairs) if pairs else ""
    periods, prev_end = [], None
    for bid_end, price in pairs:
        end = parse_dt(bid_end)
        price = _int(price)
        # начало периода - конец предыдущего; цена 0 = "не указана"
        periods.append({"begin": prev_end, "bid_end": end, "price": price if price and price > 0 else None})
        prev_end = end
    lot["_periods"] = periods
    lot["_closed_status"] = bidding_schedule.is_closed_status(lot.get("status"))
    return lot


def _int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def load():
    with _cache_lock:
        # Базу изменил другой процесс (ручной запуск python -m app.etp_collect --photos и т.п.):
        # data_version SQLite меняется только от чужих записей, свои записи этот процесс сбрасывает
        # сам (invalidate). Проверка - один PRAGMA на запрос.
        version = db.conn().execute("PRAGMA data_version").fetchone()[0]
        if _cache.get("data_version") != version:
            _cache["data_version"] = version
            _cache["lots"] = None
        if _cache["lots"] is None:
            raw = db.all_lots()
            catalog.load_fixes()  # ручные правки справочника (python -m app.catalog fix/rename)
            models_index = build_catalog(raw)
            prepared = [_prepare(lot, models_index) for lot in raw]
            cars = {}
            for lot in prepared:
                if lot["car"]:
                    cars.setdefault(lot["car"], []).append(lot)
            _borrow_car_photos(prepared, cars)
            _cache["cars"] = cars
            _cache["by_id"] = {lot["lot_id"]: lot for lot in prepared}
            _cache["lots"] = prepared
        return _cache["lots"]


def car_lots(lot):
    """Все лоты той же машины (включая сам лот)."""
    load()
    return _cache["cars"].get(lot["car"], [lot]) if lot["car"] else [lot]


def invalidate():
    with _cache_lock:
        _cache["lots"] = None


def current_state(lot, now):
    """Цена и дедлайн на момент now (bidding_schedule - общий расчёт с
    пайплайном) + номер текущего периода и следующая ступень цены для
    экрана лота. Для аукциона - цена и конец приёма заявок из листа."""
    periods = lot["_periods"] if lot["trade"] == TRADE_PUBLIC_OFFER else []
    price_text = "" if lot.get("price_current") is None else str(lot["price_current"])
    naive_now = now.astimezone(MSK).replace(tzinfo=None)  # даты сайта - Москва без зоны
    price, deadline = bidding_schedule.effective_price_and_deadline(
        price_text, lot.get("applications_end") or "", lot["_periods_text"] if periods else "", naive_now)
    idx = next((i for i, p in enumerate(periods) if p["bid_end"] > now), None)
    nxt = periods[idx + 1] if idx is not None and idx + 1 < len(periods) else None
    return {
        "price": _int(str(price or "").replace(",", ".")),
        "deadline": parse_dt(deadline),
        "period_index": idx,
        "periods_total": len(periods) or None,
        # следующая ступень - только если у неё известна цена
        "next": {"price": nxt["price"], "from": nxt["begin"]} if nxt and nxt["price"] else None,
    }


def gap_for(lot, price):
    if lot["kind"] != lot_metrics.LOT_CAR:
        return None  # мультилот: цена за несколько машин против вилки одной
    return lot_metrics.gap_percent(price, lot.get("autoru_price_low"), lot.get("autoru_price_high"))


def is_open(lot, state, now):
    """Лот виден в ленте: есть в текущем листе, приём заявок ещё идёт,
    торги не отменены/не завершены."""
    return bool(lot.get("in_source")) and state["deadline"] is not None \
        and state["deadline"] > now and not lot["_closed_status"] and not lot.get("_etp_pending") \
        and lot["kind"] not in lot_metrics.EXCLUDED_KINDS


def _iso(dt):
    return dt.isoformat() if dt else None


def _first_photo(lot):
    photos = lot.get("photos") or []
    return (photos[0].get("thumb") or photos[0].get("full")) if photos else None


def _is_new(first_seen, now):
    dt = _parse_iso(first_seen)
    return bool(dt) and now - dt < datetime.timedelta(hours=NEW_LOT_HOURS)


def summary(lot, state, now, favorites):
    gap = gap_for(lot, state["price"])
    return {
        "id": lot["lot_id"],
        "name": lot["name"],
        "year": lot.get("year"),
        # пробег мультилота - одной из машин, для лота целиком ничего не значит
        "mileage_km": lot.get("mileage_km") if lot["kind"] == lot_metrics.LOT_CAR else None,
        "mileage_estimated": bool(lot.get("mileage_estimated")),
        # число владельцев - из рыночной оценки по VIN (фильтр «Владельцы», 19.10.2026)
        "owners": lot.get("autoru_owners") if lot["kind"] == lot_metrics.LOT_CAR else None,
        # когда лот впервые появился в ленте; «новый» - за последние NEW_LOT_HOURS часов
        "first_seen": lot.get("first_seen_at"),
        "is_new": _is_new(lot.get("first_seen_at"), now),
        # число ДТП по VIN (TRONK): None - нет данных, 0 - «ДТП не найдены» (метка в ленте)
        "dtp_count": _dtp(lot)["count"] if _dtp(lot) else None,
        # пробег из отчёта (TRONK) - пересчитанное на сегодня показание: в ленте «~», на экране лота
        # «по записи из отчёта от …»; старые выгрузки без источника - как раньше
        "mileage_source": lot.get("mileage_source") or ("estimate" if lot.get("mileage_estimated") else None),
        "mileage_record_date": lot.get("mileage_record_date"),
        "price": state["price"],
        "gap": round(gap, 1) if gap is not None else None,
        # Авто.ру сам указывает большую погрешность (lot_metrics.estimate_is_uncertain) -
        # лот показываем, но с пометкой "оценка может быть неточной"
        "gap_uncertain": gap is not None and bool(lot.get("estimate_uncertain")),
        "deadline": _iso(state["deadline"]),
        "trade": lot["trade"],
        "region": lot.get("region"),
        "photo": _first_photo(lot),
        # запасные превью: не открылось первое - app.js берёт следующее (lots._photo_sets)
        "photo_alts": [s[0].get("thumb") or s[0].get("full") for s in (lot.get("photo_sets") or [])[1:] if s],
        "damaged": bool(lot["damage"]) or lot["total_damage"],
        "total_damage": lot["total_damage"],
        "kind": lot["kind"],
        "favorite": favorites.has(lot),
        "is_open": is_open(lot, state, now),
        "listings": 1,
        **specs(lot),
    }


DTP_SCHEME_URL = "https://data.tronk.info/img.ashx?mode=sr&id={}"


def _dtp(lot):
    """ДТП по VIN из выгрузки (export_to_miniapp.dtp_payload) - только у лота «одна машина»."""
    d = lot.get("dtp")
    return d if isinstance(d, dict) and lot["kind"] == lot_metrics.LOT_CAR and d.get("count") is not None else None


def dtp_detail(lot):
    """Блок «ДТП» экрана лота: схемы - через наш сервер (/img: кэш, без похода браузера к TRONK).
    Даты и схемы мини-апп показывает только с Pro (app.js), число - всем."""
    d = _dtp(lot)
    if not d:
        return None
    return {
        "count": d["count"],
        "as_of": d.get("as_of"),
        "accidents": [{
            "date": a.get("date"), "type": a.get("type"), "region": a.get("region"),
            "scheme": "/img?u=" + urllib.parse.quote(DTP_SCHEME_URL.format(int(a["scheme"])), safe="")
            if str(a.get("scheme") or "").isdigit() else None,
        } for a in d.get("accidents") or []],
    }


def specs(lot):
    """Двигатель, коробка, привод - по модификации, которую нашёл Авто.ру. У мультилота они
    одной из машин и для лота целиком ничего не значат."""
    car = lot["kind"] == lot_metrics.LOT_CAR
    return {k: (lot.get(k) if car else None)
            for k in ("engine_type", "displacement", "power", "drive", "transmission")}


def liters(displacement):
    """см³ -> литры с одним знаком, как пишут в объявлениях: 1598 -> 1.6."""
    return round(displacement / 100) / 10 if displacement else None


def detail(lot, now, favorites):
    state = current_state(lot, now)
    out = summary(lot, state, now, favorites)
    periods = []
    for i, p in enumerate(lot["_periods"]):
        periods.append({
            "begin": _iso(p["begin"]),
            "bid_end": _iso(p["bid_end"]),
            "price": p["price"],
            "is_current": state["period_index"] == i and out["is_open"],
            "is_past": p["bid_end"] <= now,
        })
    nxt = state["next"]
    out.update({
        "title": lot.get("title"),
        "url": lot.get("url"),
        # лот на самой площадке (устаревшие ссылки - в рабочий вид); нет ЭТП - объявление на ЕФРСБ; нет и его -
        # кнопка ведёт на url (агрегатор)
        "etp_url": None if lot.get("etp_state") == "missing" and _fresh(lot.get("etp_checked_at"), now)
        else (etp_status.normalize_etp_url(lot.get("etp_url")) or None),
        "efrsb_url": lot.get("efrsb_url"),
        "vin": lot.get("vin"),
        "plate": lot.get("plate"),
        "price_start": lot.get("price_start"),
        "market_low": lot.get("autoru_price_low"),
        "market_high": lot.get("autoru_price_high"),
        "owners": lot.get("autoru_owners"),
        # характеристики (engine_type, displacement, power, drive, transmission) - уже в summary
        "trade_form": lot.get("trade_form"),
        "platform": lot.get("platform"),
        "status": lot.get("status"),
        "bidding_start": _iso(parse_dt(lot.get("bidding_start"))),
        "description": lot.get("description"),
        "photos": lot.get("photos") or [],
        "photo_sets": lot.get("photo_sets") or [],  # запасные наборы фото (lots._photo_sets)
        "periods": periods,
        "period_number": state["period_index"] + 1 if state["period_index"] is not None else None,
        "periods_total": state["periods_total"],
        "next_price": nxt["price"] if nxt else None,
        "next_price_from": _iso(nxt["from"]) if nxt else None,
        "damage": lot["damage"],
        "photo_damage": lot["photo_damage"],
        "dtp": dtp_detail(lot),
    })
    out["listings_list"], out["history"] = car_context(lot, now)
    out["listings"] = max(1, len(out["listings_list"]))
    return out


def outcome(lot, state, now):
    """open / awaiting (приём заявок закончился, итога ещё нет) / failed /
    done / cancelled / suspended."""
    status = (lot.get("status") or "").lower()
    for marker, value in OUTCOMES:
        if marker in status:
            return value
    return "open" if is_open(lot, state, now) else "awaiting"


def _primary_key(lot, state):
    """Какой из параллельных лотов машины показывать: дешевле, потом
    раньше дедлайн, потом площадка ЭТП, а не "вне ЭТП"."""
    price = state["price"]
    return (price is None, price or 0, state["deadline"] or datetime.datetime.max.replace(tzinfo=MSK),
            lot["_off_etp"], lot["lot_id"])


def car_context(lot, now):
    """Для экрана лота: открытые лоты этой же машины на других площадках и
    история всех её торгов (если лотов больше одного)."""
    lots_ = car_lots(lot)
    if len(lots_) < 2:
        return [], []
    states = [(l, current_state(l, now)) for l in lots_]
    listings = sorted(((l, s) for l, s in states if is_open(l, s, now)), key=lambda p: _primary_key(*p))
    listings_out = [{
        "id": l["lot_id"], "platform": l.get("platform"), "price": s["price"],
        "deadline": _iso(s["deadline"]), "this": l["lot_id"] == lot["lot_id"],
    } for l, s in listings]
    far_past = datetime.datetime.min.replace(tzinfo=MSK)
    history = sorted(states, key=lambda p: p[1]["deadline"] or far_past, reverse=True)
    history_out = [{
        "id": l["lot_id"], "trade": l["trade"], "platform": l.get("platform"), "price": s["price"],
        "deadline": _iso(s["deadline"]), "outcome": outcome(l, s, now), "this": l["lot_id"] == lot["lot_id"],
    } for l, s in history]
    return listings_out, history_out


class Favs:
    """Избранное пользователя: лоты и машины (VIN). Лот считается
    избранным, если он сам в избранном или в избранном его машина."""

    def __init__(self, rows=()):
        self.rows = list(rows)  # [(lot_id, vin)], новые сверху
        self.lots = {lot_id for lot_id, _ in self.rows}
        self.cars = {vin for _, vin in self.rows if vin}
        load()
        for lot_id, vin in self.rows:  # записи до появления VIN в избранном
            lot = _cache["by_id"].get(lot_id)
            if not vin and lot and lot["car"]:
                self.cars.add(lot["car"])

    def has(self, lot):
        return lot["lot_id"] in self.lots or (lot["car"] is not None and lot["car"] in self.cars)


# ---------- выборка ленты ----------

def _split(value):
    return [x for x in (value or "").split(",") if x != ""]


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_filters(params):
    """params - dict query-параметров. Неизвестное/кривое молча игнорируем."""
    models = {}
    for item in _split(params.get("models")):
        if "|" in item:
            b, m = item.split("|", 1)
            models.setdefault(_norm_key(b), set()).add(_norm_key(m))
    return {
        "q": _norm_key(params.get("q")),
        "q_tokens": _query_tokens(_norm_key(params.get("q"))),
        "q_skel": _skeleton(params.get("q")),
        "brands": {_norm_key(b) for b in _split(params.get("brands"))},
        "models": models,
        "year_from": _num(params.get("year_from")),
        "year_to": _num(params.get("year_to")),
        "price_from": _num(params.get("price_from")),
        "price_to": _num(params.get("price_to")),
        "mileage_to": _num(params.get("mileage_to")),
        "regions": set(_split(params.get("regions"))),
        "kinds": set(_split(params.get("kinds"))),
        "trade": set(_split(params.get("trade"))),
        "gap_min": _num(params.get("gap_min")),
        "owners_to": _num(params.get("owners_to")),  # владельцев не больше
        "dtp_to": _num(params.get("dtp_to")),  # ДТП не больше (0 - «Без ДТП»)
        "hide_damaged": params.get("hide_damaged") == "1",
        "fuel": set(_split(params.get("fuel"))),
        "gearbox": set(_split(params.get("gearbox"))),
        "drive": set(_split(params.get("drive"))),
        "vol_from": _num(params.get("vol_from")),   # литры
        "vol_to": _num(params.get("vol_to")),
        "power_from": _num(params.get("power_from")),  # л.с.
        "power_to": _num(params.get("power_to")),
    }


# ---------- поиск по тексту ----------
# До 18.10.2026 слово запроса искалось подстрокой в марке, модели и названии лота как есть: «rav4» не
# находил «RAV 4», «камри» - Camry, «солярис» - 8 лотов из 40, «шкода октавия» - 6 из 30, а «рио» находил
# «Приору». Теперь (для поиска в ленте и для сохранённых поисков) слово запроса совпадает, если:
#   - с него начинается слово марки, модели или названия (кириллические двойники = латиница: «Х5» = X5);
#     слово из 1-2 знаков - только целиком («x5», «6» у Mazda 6, а не любая цифра VIN; буквы - ещё и
#     началом марки или модели: «ки» = Kia, пока пользователь печатает); слово с цифрами или
#     дефисом от 3 знаков - подстрокой, как раньше (кусок VIN, госномер, «cx-5»);
#   - это марка по-русски (ШКОДА -> Skoda, МЕРСЕДЕС -> Mercedes-Benz);
#   - со «скелета» (только буквы и цифры, кириллица транслитом) начинается слово или пара соседних слов
#     марки и модели: «rav4» = RAV 4, «crv» = CR-V, «xtrail» = X-Trail;
#   - слово из одних букв на слух совпадает со словом марки или модели (двойные буквы = одна): те же
#     согласные и не больше одной другой буквы
#     (двух - у слов одной длины от 6 букв): «камри» = Camry (но не Camaro), «солярис» = Solaris, «крета» = Creta
#     (но не Cerato), «лансер» = Lancer.
# Весь запрос «скелетом» тоже сверяется с маркой и моделью: «мазда 6» = Mazda 6, «санта фе» = Santa Fe.

_WORD_SPLIT_RE = re.compile(r"[^A-ZА-Я0-9]+")
_SOUND = (("DZH", "J"), ("ZH", "J"), ("Z", "S"), ("PH", "F"), ("TH", "T"), ("TS", "S"), ("CE", "SE"), ("CI", "SI"), ("CY", "SI"),
          ("C", "K"), ("Q", "K"), ("W", "V"), ("X", "KS"), ("Y", "I"))
_DOUBLE_RE = re.compile(r"(.)\1+")


def _sound(skeleton):
    """Написание «на слух»: двойные буквы = одна, Z = S, C = K (перед E/I/Y - S), Y = I...
    «тиго» = TIGGO, «акорд» = ACCORD, «гетц» = «гетс» = GETZ, «церато» = CERATO."""
    skeleton = _DOUBLE_RE.sub(r"\1", skeleton)
    for a, b in _SOUND:
        skeleton = skeleton.replace(a, b)
    if skeleton.startswith("IKS"):
        skeleton = skeleton[1:]  # «икстрейл» = X-TRAIL
    return _DOUBLE_RE.sub(r"\1", skeleton)


def _sound_cons(sound):
    return re.sub("[AEIOU]", "", sound)


def _search_index(lot, brand, model):
    """Поля для поиска по тексту - один раз на загрузку кэша (_prepare)."""
    words = " " + " ".join(_WORD_SPLIT_RE.split(lot["search_text"])) + " "
    lot["search_lat"] = lot["search_text"].translate(CYR_LOOKALIKES)
    lot["search_words"], lot["search_words_lat"] = words, words.translate(CYR_LOOKALIKES)
    skels = [_skeleton(w) for w in f"{brand} {model}".split()]
    skels = [w for w in skels if w]
    pairs = [a + b for a, b in zip(skels, skels[1:])]
    lot["search_skel"] = " " + " ".join(skels + pairs + [_skeleton(model)]) + " "
    sounds = {}
    for sk in skels + [_skeleton(model)]:
        if not sk.isalpha():
            continue  # коды с цифрами (X5, CS55) на слух не сравниваем: x5 - не CX-5
        snd = _sound(sk)
        sounds.setdefault(_sound_cons(snd), set()).add(snd)
    lot["search_sound"] = sounds


def _query_tokens(q):
    """Слова запроса с вариантами написания (см. «поиск по тексту»)."""
    out = []
    for tok in (q or "").split():
        sk = _skeleton(tok)
        snd = _sound(sk)
        out.append({"tok": tok, "lat": tok.translate(CYR_LOOKALIKES), "alpha": bool(re.fullmatch("[A-ZА-Я]+", tok)),
                    "skel": sk, "sound": snd, "cons": _sound_cons(snd),
                    "brand": BRAND_SPELLINGS.get(tok) or BRAND_ALIASES.get(tok)})
    return out


def _close(a, b):
    """Расстояние Левенштейна не больше 1 (2 - у слов одной длины от 6 букв: «кулрей» = COOLRAY, но
    «соната» - не SANTA)."""
    limit = 2 if len(a) >= 6 and len(a) == len(b) else 1
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def _token_matches(t, lot):
    tok, lat, sk = t["tok"], t["lat"], t["skel"]
    if len(tok) <= 2:
        if f" {tok} " in lot["search_words"] or f" {lat} " in lot["search_words_lat"]:
            return True
    elif t["alpha"]:
        if f" {tok}" in lot["search_words"] or f" {lat}" in lot["search_words_lat"]:
            return True
    elif tok in lot["search_text"] or lat in lot["search_lat"]:
        return True
    if t["brand"] and t["brand"] == lot["brand_key"]:
        return True
    # начало слова марки/модели; цифры из 1-2 знаков - только целиком («6» - не 626)
    if sk and (f" {sk} " if len(sk) <= 2 and not t["alpha"] else f" {sk}") in lot["search_skel"]:
        return True
    # на слух (только слова из букв): с допуском в букву - от 3 согласных или от 4 букв («тиго» = TIGGO),
    # короче - только точно
    if not t["alpha"]:
        return False
    sounds = lot["search_sound"].get(t["cons"], ())
    if len(t["cons"]) >= 3 or len(t["sound"]) >= 4:
        return any(_close(t["sound"], s) for s in sounds)
    return len(t["sound"]) >= 3 and t["sound"] in sounds


def text_matches(f, lot):
    """Совпадает ли лот с текстом запроса (f - parse_filters)."""
    if not f["q"]:
        return True
    if len(f["q_skel"]) >= 3 and f" {f['q_skel']}" in lot["search_skel"]:
        return True
    return all(_token_matches(t, lot) for t in f["q_tokens"])


def _between(value, lo, hi):
    if lo is None and hi is None:
        return True
    if value is None:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _matches(item, lot, f, skip_damage=False):
    """skip_damage - не применять "Скрыть битые" (чтобы посчитать, сколько скрыто)."""
    if f["hide_damaged"] and lot["total_damage"] and not skip_damage:
        return False
    if not text_matches(f, lot):
        return False
    if f["brands"] and lot["brand_key"] not in f["brands"]:
        return False
    # Модели уточняют бренд: если у бренда выбраны модели - только они.
    chosen = f["models"].get(lot["brand_key"])
    if chosen and lot["model_key"] not in chosen:
        return False
    if not _between(item["year"], f["year_from"], f["year_to"]):
        return False
    if not _between(item["price"], f["price_from"], f["price_to"]):
        return False
    if not _between(item["mileage_km"], None, f["mileage_to"]):
        return False
    if f["regions"] and (lot.get("region") or "") not in f["regions"]:
        return False
    if f["trade"] and lot["trade"] not in f["trade"]:
        return False
    if f["kinds"] and lot["kind"] not in f["kinds"]:
        return False
    if f["gap_min"] is not None and (item["gap"] is None or item["gap"] < f["gap_min"]):
        return False
    # число владельцев известно не у всех (только с рыночной оценкой): при фильтре лот без него не показываем
    if f["owners_to"] is not None and (item["owners"] is None or item["owners"] > f["owners_to"]):
        return False
    # ДТП (TRONK по VIN): без данных при фильтре не показываем - «нет данных» не значит «без ДТП»
    if f["dtp_to"] is not None and (item["dtp_count"] is None or item["dtp_count"] > f["dtp_to"]):
        return False
    # характеристики известны не у всех лотов: при выбранном фильтре лот без них не показываем
    if f["fuel"] and item["engine_type"] not in f["fuel"]:
        return False
    if f["gearbox"] and item["transmission"] not in f["gearbox"]:
        return False
    if f["drive"] and item["drive"] not in f["drive"]:
        return False
    if not _between(liters(item["displacement"]), f["vol_from"], f["vol_to"]):
        return False
    if not _between(item["power"], f["power_from"], f["power_to"]):
        return False
    return True


def _sort_key(sort):
    far = "9999"
    if sort == "new":
        # Сначала новые (сортировка по умолчанию в мини-аппе с 20.10.2026, решение владельца): лоты
        # приходят пачкой раз в сутки, поэтому по дню появления, а внутри дня - самые выгодные сверху
        return lambda it: (-_day_number(it["first_seen"]), it["gap"] is None, -(it["gap"] or 0),
                           it["deadline"] or far)
    if sort == "price_asc":
        return lambda it: (it["price"] is None, it["price"] or 0)
    if sort == "price_desc":
        return lambda it: (it["price"] is None, -(it["price"] or 0))
    if sort == "deadline":
        return lambda it: (it["deadline"] or far, -(it["gap"] if it["gap"] is not None else -1e9))
    # по умолчанию - самые выгодные сверху, лоты без оценки Авто.ру - в конец
    return lambda it: (it["gap"] is None, -(it["gap"] or 0), it["deadline"] or far)


def _day_number(iso):
    """'2026-10-20T07:31:02+03:00' -> номер дня (для сортировки «Сначала новые»); нет даты - 0."""
    try:
        return datetime.date.fromisoformat(str(iso)[:10]).toordinal()
    except ValueError:
        return 0


# «Новый» лот (метка на фото и сортировка «Сначала новые»): появился в ленте не раньше стольких часов
# назад - выгрузка раз в сутки, 30 часов покрывают и прогон, задержавшийся на несколько часов.
NEW_LOT_HOURS = 30


def open_items(favorites, now=None):
    """Все видимые сейчас лоты в виде (summary, lot); параллельные лоты одной
    машины - одной карточкой (summary["listings"] - сколько площадок)."""
    now = now or now_msk()
    groups = {}
    for lot in load():
        state = current_state(lot, now)
        if is_open(lot, state, now):
            groups.setdefault(lot["car"] or ("lot", lot["lot_id"]), []).append((lot, state))
    out = []
    for group in groups.values():
        group.sort(key=lambda p: _primary_key(*p))
        lot, state = group[0]
        item = summary(lot, state, now, favorites)
        item["listings"] = len(group)
        out.append((item, lot))
    return out


def search(params, favorites, offset=0, limit=20):
    f = parse_filters(params)
    sort = params.get("sort") if params.get("sort") in SORTS else "gap"
    pairs = open_items(favorites)
    items = [it for it, lot in pairs if _matches(it, lot, f)]
    items.sort(key=_sort_key(sort))
    # сколько битых спрятала галочка "Скрыть битые" среди подходящих под остальные фильтры
    hidden = sum(1 for it, lot in pairs if lot["total_damage"] and _matches(it, lot, f, skip_damage=True))         if f["hide_damaged"] else 0
    return {"total": len(items), "hidden_damaged": hidden, "items": items[offset:offset + limit]}


def facets(favorites):
    """Варианты для экрана фильтров - по всем открытым лотам."""
    brands = {}
    regions = {}
    years, prices, mileages = [], [], []
    spec_counts = {"engine_type": {}, "transmission": {}, "drive": {}}
    volumes, powers, cars, with_specs, with_owners, with_dtp = [], [], 0, 0, 0, 0
    for it, lot in open_items(favorites):
        if lot["kind"] == lot_metrics.LOT_CAR:
            cars += 1
            with_specs += bool(it["engine_type"] or it["transmission"] or it["drive"] or it["power"])
            with_owners += it["owners"] is not None
            with_dtp += it["dtp_count"] is not None
        for key, counts in spec_counts.items():
            if it[key]:
                counts[it[key]] = counts.get(it[key], 0) + 1
        if it["displacement"]:
            volumes.append(liters(it["displacement"]))
        if it["power"]:
            powers.append(it["power"])
        if lot["brand_key"]:
            b = brands.setdefault(lot["brand_key"], {"key": lot["brand_key"], "label": lot["brand_label"],
                                                     "count": 0, "models": {}})
            b["count"] += 1
            if lot["model_key"]:
                m = b["models"].setdefault(lot["model_key"], {"key": lot["model_key"],
                                                              "label": lot["model_label"], "count": 0})
                m["count"] += 1
        if lot.get("region"):
            regions[lot["region"]] = regions.get(lot["region"], 0) + 1
        if it["year"]:
            years.append(it["year"])
        if it["price"]:
            prices.append(it["price"])
        if it["mileage_km"]:
            mileages.append(it["mileage_km"])
    # Марки и модели, которых сейчас нет на торгах, но которые встречались раньше (база хранит все
    # выгруженные лоты) - с числом 0: по ним можно сохранить поиск «на будущее» (решение владельца
    # 19.10.2026, кнопки «Показать все марки» / «Все модели» в app.js). Каталог пополняется сам.
    for lot in load():
        if lot["kind"] != lot_metrics.LOT_CAR or not lot["brand_key"]:
            continue
        b = brands.setdefault(lot["brand_key"], {"key": lot["brand_key"], "label": lot["brand_label"],
                                                 "count": 0, "models": {}})
        if lot["model_key"]:
            b["models"].setdefault(lot["model_key"], {"key": lot["model_key"], "label": lot["model_label"], "count": 0})
    brand_list = sorted(brands.values(), key=lambda b: b["label"])
    for b in brand_list:
        b["models"] = sorted(b["models"].values(), key=lambda m: m["label"])
    return {
        "brands": brand_list,
        "regions": [{"key": k, "count": v} for k, v in sorted(regions.items())],
        "year": [min(years), max(years)] if years else None,
        "price": [min(prices), max(prices)] if prices else None,
        "mileage": [0, max(mileages)] if mileages else None,
        # характеристики: варианты с числом лотов в заданном порядке; у скольких машин они известны
        "fuel": _ordered(spec_counts["engine_type"], FUELS),
        "gearbox": _ordered(spec_counts["transmission"], GEARBOXES),
        "drive": _ordered(spec_counts["drive"], DRIVES),
        "volume": [min(volumes), max(volumes)] if volumes else None,
        "power": [min(powers), max(powers)] if powers else None,
        "specs_known": with_specs, "cars": cars, "owners_known": with_owners, "dtp_known": with_dtp,
    }


def _ordered(counts, order):
    keys = [k for k in order if k in counts] + sorted(k for k in counts if k not in order)
    return [{"key": k, "count": counts[k]} for k in keys]


def get(lot_id):
    load()
    return _cache["by_id"].get(str(lot_id))


def favorites_list(favs, now=None):
    """Карточки избранного - по одной на машину (или лот без VIN):
    актуальный лот машины + fav_state (open / awaiting / failed / done /
    cancelled / suspended), relisted (машину выставили снова, а в избранное
    добавляли прежний лот), archived (закрыт больше FAVORITE_ARCHIVE_DAYS
    дней назад). Порядок: открытые, закрытые, архив; внутри - как добавляли."""
    now = now or now_msk()
    load()
    by_id = _cache["by_id"]
    groups = {}  # ключ машины/лота -> lot_id из избранного (новые первыми)
    for lot_id, vin in favs.rows:
        lot = by_id.get(lot_id)
        car = vin or (lot["car"] if lot else None)
        key = car or ("lot", lot_id)
        groups.setdefault(key, []).append(lot_id)
    items = []
    for key, fav_ids in groups.items():
        lots_ = list(_cache["cars"].get(key, [])) if isinstance(key, str) else []
        lots_ += [by_id[i] for i in fav_ids if i in by_id and by_id[i] not in lots_]
        if not lots_:
            continue
        states = [(l, current_state(l, now)) for l in lots_]
        opened = [p for p in states if is_open(p[0], p[1], now)]
        if opened:
            lot, state = min(opened, key=lambda p: _primary_key(*p))
        else:
            far_past = datetime.datetime.min.replace(tzinfo=MSK)
            lot, state = max(states, key=lambda p: p[1]["deadline"] or far_past)
        item = summary(lot, state, now, favs)
        item["favorite"] = True
        item["listings"] = max(1, len(opened))
        item["fav_state"] = outcome(lot, state, now)
        fav_states = [p for p in states if p[0]["lot_id"] in fav_ids]
        if opened and lot["lot_id"] not in fav_ids and fav_states \
                and not any(is_open(l, s, now) for l, s in fav_states):
            prev = max(fav_states, key=lambda p: p[1]["deadline"] or now)
            item["relisted"] = True
            item["prev_price"] = prev[1]["price"]
        closed_at = state["deadline"]
        item["archived"] = item["fav_state"] != "open" and closed_at is not None \
            and now - closed_at > datetime.timedelta(days=FAVORITE_ARCHIVE_DAYS)
        items.append(item)
    rank = lambda it: 2 if it["archived"] else (0 if it["fav_state"] == "open" else 1)
    items.sort(key=rank)  # sort стабильный - порядок добавления внутри групп сохраняется
    return items


def _parse_iso(value):
    """Время, записанное сервером (isoformat с зоной), - не формат сайта."""
    try:
        dt = datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MSK)


def watchlist(now=None):
    """Лоты из избранного (и все лоты избранных машин), чей итог ещё
    неизвестен: приём заявок закончился или лот ушёл из среза, а статус не
    окончательный. ПК перечитывает их карточки на сайте (export_to_miniapp)."""
    now = now or now_msk()
    load()
    favs = Favs(db.all_favorite_rows())
    out = []
    for lot in load():
        if not favs.has(lot):
            continue
        state = current_state(lot, now)
        if is_open(lot, state, now) or outcome(lot, state, now) in FINAL_OUTCOMES:
            continue
        end = lot["_final_deadline"] or state["deadline"]
        if end is not None and now - end > datetime.timedelta(days=WATCH_DAYS):
            continue
        checked = _parse_iso(lot.get("status_checked_at"))
        if checked is not None and now - checked < datetime.timedelta(hours=WATCH_RECHECK_HOURS):
            continue
        out.append({"lot_id": lot["lot_id"], "url": lot.get("url")})
    return out
