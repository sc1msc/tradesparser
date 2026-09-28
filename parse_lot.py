# -*- coding: utf-8 -*-
"""
Парсер карточки лота с сайта-агрегатора торгов (новый дизайн, Next.js).

В отличие от старой версии, здесь НЕ парсится HTML-разметка через
BeautifulSoup - вместо этого из страницы вытаскивается встроенный JSON-объект
"lot" (см. nextjs_json.py), который содержит все нужные данные в готовом,
чистом виде: цену, даты, организатора, управляющего, должника и т.д.
Это надёжнее, чем разбирать вёрстку - вёрстка снова может измениться, а
структура данных вряд ли, раз именно из неё рендерится страница.

Использование:
    from parse_lot import parse_lot_html
    data = parse_lot_html(html_text, url="https://.../lot/7168718")
"""
import re
from nextjs_json import extract_combined_payload, find_json_value

# Госномер РФ: буква + 3 цифры + 2 буквы + 2-3 цифры региона.
# Буквы - только те, что совпадают по начертанию с латиницей (ГОСТ Р 50577-93):
# А В Е К М Н О Р С Т У Х. Пробелы между частями опциональны.
PLATE_RE = re.compile(
    r"\b[АВЕКМНОРСТУХ]\s?\d{3}\s?[АВЕКМНОРСТУХ]{2}\s?\d{2,3}\b",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
MILEAGE_RE = re.compile(r"пробег[а-я]*[:\s]*([\d\s]{3,10})\s*км", re.IGNORECASE)


def _extract_plate(text):
    if not text:
        return None
    m = PLATE_RE.search(text)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(0)).upper()


def _extract_vin_from_text(text):
    if not text:
        return None
    m = VIN_RE.search(text)
    return m.group(1).upper() if m else None


def _extract_mileage_from_text(text):
    if not text:
        return None
    m = MILEAGE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def _get(d, *path, default=None):
    """Достаёт значение по цепочке ключей из вложенных словарей, не падая на None/отсутствии ключа."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def parse_lot_html(html, url=None):
    payload = extract_combined_payload(html)
    lot, _ = find_json_value(payload, "lot", kind="object")

    if lot is None:
        # Не нашли встроенный JSON - вероятно, снова поменялась вёрстка/формат.
        # Возвращаем максимум того, что можно, чтобы пайплайн не падал целиком.
        return {"url": url, "lot_id": None, "title": None, "parse_error": "lot JSON not found"}

    title = lot.get("title")
    description = lot.get("information")  # текстовое описание тех. характеристик
    status = _get(lot, "status", "title")
    region = _get(lot, "region", "title")
    trade_kind = lot.get("trade_form")
    trade_section = _get(lot, "trades_section", "title")
    platform = _get(lot, "marketplace", "title")

    stages = lot.get("stages") or {}
    applications_start = stages.get("begin_bid_time")
    applications_end = stages.get("end_bid_time")
    bidding_start = stages.get("begin_offer_time") or lot.get("begin_offer_time")

    organizer = lot.get("organizer") or {}
    manager = lot.get("arbitration_administrator") or {}
    debtor = lot.get("debtor") or {}

    # VIN: сначала пробуем явный массив vins (когда сайт его сам вычленил),
    # иначе - регуляркой из заголовка/описания.
    vins = lot.get("vins") or []
    vin = vins[0] if vins else (_extract_vin_from_text(title) or _extract_vin_from_text(description))

    plate = _extract_plate(title) or _extract_plate(description)
    mileage = _extract_mileage_from_text(description) or _extract_mileage_from_text(title)

    pictures = lot.get("pictures") or []
    photo_url = pictures[0].get("link") if pictures else None

    return {
        "url": url,
        "lot_id": str(lot.get("id")) if lot.get("id") is not None else None,
        "title": title,
        "status": status,
        "vin": vin,
        "vins_all": vins,
        "plate": plate,
        "mileage_km": mileage,
        "photo_url": photo_url,
        "region": region,
        "price_start": lot.get("start_price"),
        "price_current": lot.get("current_price"),
        "currency": "RUB",
        "trade_kind": trade_kind,
        "trade_section": trade_section,
        "platform": platform,
        "applications_start": applications_start,
        "applications_end": applications_end,
        "bidding_start": bidding_start,
        "organizer_name": organizer.get("name") or lot.get("conact_name"),
        "organizer_phone": organizer.get("phone") or lot.get("conact_phone"),
        "organizer_email": organizer.get("email") or lot.get("conact_email"),
        "manager_name": manager.get("name"),
        "manager_sro": manager.get("sro"),
        "manager_inn": manager.get("inn"),
        "debtor_name": debtor.get("name"),
        "debtor_inn": debtor.get("inn"),
        "description": description,
        "raw_lot": lot,  # весь исходный объект - на случай, если понадобится что-то ещё
    }


if __name__ == "__main__":
    import sys
    import json as json_module
    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/1.html"
    with open(path, encoding="utf-8", errors="ignore") as f:
        html = f.read()
    data = parse_lot_html(html, url="https://xn----etbpba5admdlad.xn--p1ai/lot/7168718")
    data.pop("raw_lot", None)  # для читаемого вывода в консоль
    print(json_module.dumps(data, ensure_ascii=False, indent=2))
