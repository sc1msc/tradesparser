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

Объём - сотни лотов (до 5-10 тыс. при расширении географии), поэтому вся
выборка/сортировка идёт в памяти по кэшу лотов: это проще SQL-конструктора
фильтров и заведомо быстро. Кэш сбрасывается после каждого импорта.
"""
import datetime
import json
import re
import threading

import bidding_schedule
import lot_metrics

from . import db

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
BRAND_LABELS = {"SSANGYONG": "SsangYong", "LIXIANG": "LiXiang"}

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
    "PEUGEOT", "PORSCHE", "RENAULT", "SAAB", "SKODA", "SMART", "SSANGYONG", "SUBARU",
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

CYR_LOOKALIKES = str.maketrans("АВЕКМНОРСТУХаеокрсух", "ABEKMHOPCTYXaeokpcyx")

TRADE_AUCTION = "auction"
TRADE_PUBLIC_OFFER = "public_offer"

SORTS = ("gap", "price_asc", "price_desc", "deadline")

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
    rest = re.split(r"[,;(]", rest or "", maxsplit=1)[0]
    words = rest.replace("/", " ").split()
    while words and BRAND_SPELLINGS.get(words[0].upper(), words[0].upper()) == brand_key:
        words = words[1:]
    return " ".join(words).strip(" :–-")


def clean_model(value, brand_label):
    model = " ".join((value or "").replace("_", " ").split())
    model = re.sub(r"^\W*(модель|model|тс|т\.с\.)\s*[:–-]?\s*", "", model, flags=re.IGNORECASE)
    model = re.sub(r"^\W*(модель|model)\s*[:–-]?\s*", "", model, flags=re.IGNORECASE)
    model = re.sub(r"^\([^)]*\)\s*", "", model)  # "(lada) 2190 Granta" -> "2190 Granta"
    # Документы торгов смешивают в одном слове кириллицу с латиницей
    # ("Sаnта FЕ") - в словах, где есть латиница, двойники меняем на латиницу.
    model = " ".join(w.translate(CYR_LOOKALIKES) if re.search("[A-Za-z]", w) else w for w in model.split())
    # Модель из Autodoc иногда начинается с марки ("Audi A6 ...") - убираем повтор.
    if brand_label and _norm_key(model).startswith(_norm_key(brand_label) + " "):
        model = model[len(brand_label):].strip()
    model = MODEL_JUNK_RE.sub("", model).strip(" ,.:;-")
    # непарная скобка от обрезанной фразы ("Pajero)"), парные ("2131 (4X4)") не трогаем
    if model.endswith(")") and model.count("(") < model.count(")"):
        model = model[:-1].strip()
    if model.startswith("(") and model.count("(") > model.count(")"):
        model = model[1:].strip()
    if len(model) > 25:
        return ""
    return pretty_name(model)


def _prepare(lot):
    """Статичные (не зависящие от времени) производные поля - один раз на
    загрузку кэша."""
    brand_key, brand, raw_model = resolve_brand_model(lot.get("brand"), lot.get("model"), lot.get("title"))
    model = clean_model(raw_model, brand) if brand else ""
    lot["brand_label"] = brand
    lot["model_label"] = model
    lot["brand_key"] = brand_key
    lot["model_key"] = _norm_key(model)
    lot["name"] = " ".join(x for x in (brand, model) if x) or (lot.get("title") or "Лот")[:60]
    lot["trade"] = TRADE_PUBLIC_OFFER if lot.get("is_public_offer") else TRADE_AUCTION
    lot["damage"] = lot_metrics.damage_keywords(lot.get("title"))
    # тип лота (lot_metrics.lot_kind): мультилот - без процента к рынку и
    # с меткой; права требования/доли в ленту не попадают вовсе
    lot["kind"] = lot.get("lot_kind") or lot_metrics.LOT_CAR
    if lot["kind"] == lot_metrics.LOT_MULTILOT:
        # Марка/модель у мультилота - от одной из машин (Авто.ру по первому
        # VIN: лот из 17 Solaris выходил "Hyundai Santa FE"). Показываем
        # название лота с сайта и не кладём его в фильтр по марке.
        lot["brand_key"] = lot["model_key"] = ""
        lot["name"] = " ".join((lot.get("title") or "Мультилот").split())[:60]
    lot["search_text"] = _norm_key(" ".join(
        str(x or "") for x in (brand, model, lot.get("title"), lot.get("vin"), lot.get("plate"))
    ))
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
        if _cache["lots"] is None:
            _cache["lots"] = [_prepare(lot) for lot in db.all_lots()]
        return _cache["lots"]


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
        and state["deadline"] > now and not lot["_closed_status"] \
        and lot["kind"] not in lot_metrics.EXCLUDED_KINDS


def _iso(dt):
    return dt.isoformat() if dt else None


def _first_photo(lot):
    photos = lot.get("photos") or []
    return (photos[0].get("thumb") or photos[0].get("full")) if photos else None


def summary(lot, state, now, favorites):
    gap = gap_for(lot, state["price"])
    return {
        "id": lot["lot_id"],
        "name": lot["name"],
        "year": lot.get("year"),
        # пробег мультилота - одной из машин, для лота целиком ничего не значит
        "mileage_km": lot.get("mileage_km") if lot["kind"] == lot_metrics.LOT_CAR else None,
        "mileage_estimated": bool(lot.get("mileage_estimated")),
        "price": state["price"],
        "gap": round(gap, 1) if gap is not None else None,
        # Авто.ру сам указывает большую погрешность (lot_metrics.estimate_is_uncertain) -
        # лот показываем, но с пометкой "оценка может быть неточной"
        "gap_uncertain": gap is not None and bool(lot.get("estimate_uncertain")),
        "deadline": _iso(state["deadline"]),
        "trade": lot["trade"],
        "region": lot.get("region"),
        "photo": _first_photo(lot),
        "damaged": bool(lot["damage"]),
        "kind": lot["kind"],
        "favorite": lot["lot_id"] in favorites,
        "is_open": is_open(lot, state, now),
    }


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
        "vin": lot.get("vin"),
        "plate": lot.get("plate"),
        "price_start": lot.get("price_start"),
        "market_low": lot.get("autoru_price_low"),
        "market_high": lot.get("autoru_price_high"),
        "owners": lot.get("autoru_owners"),
        "trade_form": lot.get("trade_form"),
        "platform": lot.get("platform"),
        "status": lot.get("status"),
        "bidding_start": _iso(parse_dt(lot.get("bidding_start"))),
        "description": lot.get("description"),
        "photos": lot.get("photos") or [],
        "periods": periods,
        "period_number": state["period_index"] + 1 if state["period_index"] is not None else None,
        "periods_total": state["periods_total"],
        "next_price": nxt["price"] if nxt else None,
        "next_price_from": _iso(nxt["from"]) if nxt else None,
        "damage": lot["damage"],
    })
    return out


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
    }


def _between(value, lo, hi):
    if lo is None and hi is None:
        return True
    if value is None:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _matches(item, lot, f):
    if f["q"] and not all(tok in lot["search_text"] for tok in f["q"].split()):
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
    return True


def _sort_key(sort):
    far = "9999"
    if sort == "price_asc":
        return lambda it: (it["price"] is None, it["price"] or 0)
    if sort == "price_desc":
        return lambda it: (it["price"] is None, -(it["price"] or 0))
    if sort == "deadline":
        return lambda it: (it["deadline"] or far, -(it["gap"] if it["gap"] is not None else -1e9))
    # по умолчанию - самые выгодные сверху, лоты без оценки Авто.ру - в конец
    return lambda it: (it["gap"] is None, -(it["gap"] or 0), it["deadline"] or far)


def open_items(favorites, now=None):
    """Все видимые сейчас лоты в виде (summary, lot)."""
    now = now or now_msk()
    out = []
    for lot in load():
        state = current_state(lot, now)
        if is_open(lot, state, now):
            out.append((summary(lot, state, now, favorites), lot))
    return out


def search(params, favorites, offset=0, limit=20):
    f = parse_filters(params)
    sort = params.get("sort") if params.get("sort") in SORTS else "gap"
    items = [it for it, lot in open_items(favorites) if _matches(it, lot, f)]
    items.sort(key=_sort_key(sort))
    return {"total": len(items), "items": items[offset:offset + limit]}


def facets(favorites):
    """Варианты для экрана фильтров - по всем открытым лотам."""
    brands = {}
    regions = {}
    years, prices, mileages = [], [], []
    for it, lot in open_items(favorites):
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
    brand_list = sorted(brands.values(), key=lambda b: b["label"])
    for b in brand_list:
        b["models"] = sorted(b["models"].values(), key=lambda m: m["label"])
    return {
        "brands": brand_list,
        "regions": [{"key": k, "count": v} for k, v in sorted(regions.items())],
        "year": [min(years), max(years)] if years else None,
        "price": [min(prices), max(prices)] if prices else None,
        "mileage": [0, max(mileages)] if mileages else None,
    }


def get(lot_id):
    return next((lot for lot in load() if lot["lot_id"] == str(lot_id)), None)


def favorites_list(ids, now=None):
    """Избранное: открытые лоты сверху (в порядке добавления), закрытые - ниже."""
    now = now or now_msk()
    fav = set(ids)
    by_id = {lot["lot_id"]: lot for lot in load()}
    items = []
    for lot_id in ids:
        lot = by_id.get(lot_id)
        if lot:
            items.append(summary(lot, current_state(lot, now), now, fav))
    items.sort(key=lambda it: not it["is_open"])
    return items
