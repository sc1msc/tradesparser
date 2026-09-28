# -*- coding: utf-8 -*-
"""
Парсер страницы поиска/каталога сайта-агрегатора торгов (новый дизайн, Next.js).

Как и в parse_lot.py, данные берутся не из HTML-вёрстки, а из встроенного
JSON внутри страницы: массив "initialLots" (сами карточки лотов) и объект
"initialMeta" (пагинация: текущая страница, всего страниц, общее число лотов).

URL-схема поиска НЕ изменилась при редизайне (проверено на реальной странице:
/search?categorie_childs[0]=2&regions[0]=50&regions[1]=77&trades-section[0]=bankrupt
&history_only=0&page=N) - поэтому build_search_url() не менялся.

Использование:
    from parse_search import parse_search_html, build_search_url

    url = build_search_url(page=1)
    html = ...  # скачали по url
    result = parse_search_html(html)
    for lot in result["lots"]:
        print(lot["lot_id"], lot["url"])
    next_url = result["next_page_url"]
"""
import re
from urllib.parse import urlencode
from nextjs_json import extract_combined_payload, find_json_value

BASE_DOMAIN = "https://xn----etbpba5admdlad.xn--p1ai"

# Параметры фильтра вынесены отдельно, чтобы легко менять категорию/регион/раздел торгов,
# не трогая логику парсинга. Значения (categorie_childs, regions) взяты из реальной
# ссылки поиска, которую сформировал сам сайт при выборе фильтров
# "Москва + Московская область, Банкротство, Легковой транспорт".
DEFAULT_SEARCH_PARAMS = {
    "categorie_childs[0]": 2,       # категория: Легковой транспорт
    "regions[0]": 50,               # Московская область
    "regions[1]": 77,               # г. Москва
    "trades-section[0]": "bankrupt",
    "history_only": 0,
}

PLATE_RE = re.compile(
    r"\b[АВЕКМНОРСТУХ]\s?\d{3}\s?[АВЕКМНОРСТУХ]{2}\s?\d{2,3}\b",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
MILEAGE_RE = re.compile(r"([\d\s]{3,10})\s*км\b", re.IGNORECASE)


def build_search_url(page=1, params=None):
    """Собирает URL страницы поиска из параметров фильтра."""
    query = dict(DEFAULT_SEARCH_PARAMS)
    if params:
        query.update(params)
    query["page"] = page
    return f"{BASE_DOMAIN}/search?{urlencode(query)}"


def _extract_plate(text):
    if not text:
        return None
    m = PLATE_RE.search(text)
    return re.sub(r"\s+", "", m.group(0)).upper() if m else None


def _extract_vin(text):
    if not text:
        return None
    m = VIN_RE.search(text)
    return m.group(1).upper() if m else None


def _extract_year(text):
    if not text:
        return None
    m = YEAR_RE.search(text)
    return int(m.group(1)) if m else None


def _extract_mileage(text):
    if not text:
        return None
    m = MILEAGE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def _parse_item(item):
    lot_id = str(item.get("id")) if item.get("id") is not None else None
    title = item.get("title")
    url = f"{BASE_DOMAIN}/lot/{lot_id}" if lot_id else None

    # На странице поиска, в отличие от карточки лота, нет отдельного текстового
    # описания - есть только заголовок, поэтому VIN/год/пробег/номер вытаскиваем
    # из него. Это просто бонус-фолбэк на случай, если понадобится быстро
    # прикинуть данные не открывая карточку - основной источник этих полей
    # всё равно parse_lot.py.
    return {
        "lot_id": lot_id,
        "url": url,
        "title": title,
        "excerpt": None,
        "region": item.get("region_title"),
        "platform": item.get("marketplace_title"),
        "price_current": item.get("current_price"),
        "price_start": item.get("start_price"),
        "currency": "RUB",
        "trade_type": item.get("trade_type_title"),
        "trade_kind": item.get("trade_form"),
        "status": item.get("status"),
        "vin": _extract_vin(title),
        "plate": _extract_plate(title),
        "year": _extract_year(title),
        "mileage_km": _extract_mileage(title),
    }


def parse_search_html(html):
    payload = extract_combined_payload(html)

    items, _ = find_json_value(payload, "initialLots", kind="array")
    meta, _ = find_json_value(payload, "initialMeta", kind="object")

    lots = [_parse_item(item) for item in (items or []) if item.get("id") is not None]

    current_page = (meta or {}).get("current_page", 1)
    last_page = (meta or {}).get("last_page", current_page)
    total = (meta or {}).get("total")
    has_next = bool(last_page) and current_page < last_page

    return {
        "lots": lots,
        "current_page": current_page,
        "last_page": last_page,
        "total": total,
        "has_next": has_next,
        # next_page_url специально не строим здесь через сырой href из meta["links"] -
        # надёжнее и проще пересобрать его через build_search_url(page=current_page+1)
        # с теми же параметрами фильтра, которые использует сам оркестратор (main.py).
    }


if __name__ == "__main__":
    import sys
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/1.html"
    with open(path, encoding="utf-8", errors="ignore") as f:
        html = f.read()
    result = parse_search_html(html)
    print(f"Найдено лотов на странице: {len(result['lots'])}")
    print(f"Страница {result['current_page']} из {result['last_page']}, всего лотов: {result['total']}, есть следующая: {result['has_next']}")
    print(json.dumps(result["lots"][:3], ensure_ascii=False, indent=2))
    print("...")
    print(f"\nПример URL поиска: {build_search_url(page=2)}")
