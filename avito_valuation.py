# -*- coding: utf-8 -*-
"""
Модуль оценки авто по VIN через Avito (используется недокументированное
внутреннее API формы https://www.avito.ru/evaluation/cars, без эмуляции браузера).

Флоу:
  1) POST /web/1/imv/resolve/number {"number": VIN}
     -> возвращает список "fields": каждое поле уже содержит currentValueId,
        если оно однозначно определилось по VIN (марка/модель/год/кузов/
        комплектация и т.д.). Поля "Владельцы" (id 1167) и "Пробег" (id 2687)
        никогда не приходят предзаполненными - их нужно передать вручную,
        как в браузере.
  2) POST /web/2/imv/price с итоговым набором fieldsValueIds + мест положением
     -> возвращает вилку цены.

ВАЖНО:
- Сайт защищён Qrator (антибот). Голый requests.post с нуля может быть
  заблокирован. Нужно: 1) заходить через requests.Session(), 2) сначала
  сделать обычный GET на /evaluation/cars, чтобы получить куки, 3) слать
  реалистичные заголовки (User-Agent, Accept-Language, Referer, Origin),
  4) не долбить без пауз - иначе рано или поздно всё равно поймаете капчу
   или бан по IP. Для больших объёмов лучше рассмотреть прокси/ротацию.
- Раздел "Город" (id 100006) в ответе resolve/number не содержит
  currentValueId - в реальном запросе цены город передаётся отдельным
  объектом "location" (id/lat/long), а не в fieldsValueIds. У меня нет
  примера, как Avito резолвит city name -> location id, поэтому ниже задан
  DEFAULT_LOCATION (Москва, взято из вашего примера). Если нужна точность
  по другим регионам - придётся отдельно найти эндпоинт геокодинга Avito
  (скорее всего autocomplete по названию города) и заменить заглушку.
- У меня нет реального тела ответа /web/2/imv/price (в HAR тела ответов не
  сохранились), поэтому парсер ниже ищет price/price_low/price_high по
  всей структуре ответа рекурсивно - это должно быть устойчиво к разным
  вариантам вложенности, но стоит свериться с реальным ответом при первом
  прогоне и, если что, поправить `_find_price_fields`.
"""
import random
import time
import copy
import re
import requests

BASE = "https://www.avito.ru"
RESOLVE_URL = f"{BASE}/web/1/imv/resolve/number"
PRICE_URL = f"{BASE}/web/2/imv/price"
LANDING_URL = f"{BASE}/evaluation/cars"

# Поля, которые НЕ нужно копировать из resolve-ответа в price-запрос:
# 100006 - город (уходит отдельным объектом "location")
# 1167   - владельцы (задаём вручную)
# 2687   - пробег (задаём вручную)
EXCLUDED_FIELD_IDS = {100006, 1167, 2687}

# Заглушка: Москва, из примера в HAR. Замените под свой регион при необходимости.
DEFAULT_LOCATION = {"id": 637640, "lat": 55.755814, "long": 37.617635}

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": BASE,
    "Referer": LANDING_URL,
}


def make_session():
    """Создаёт сессию и «прогревает» её обычным заходом на страницу оценки,
    чтобы получить нужные куки перед XHR-запросами."""
    s = requests.Session()
    s.headers.update(COMMON_HEADERS)
    s.get(LANDING_URL, timeout=15)
    time.sleep(1)  # не долбить сразу пачкой запросов
    return s


def _post_json_with_retry(session, url, payload, max_retries=5, base_delay=8):
    """
    POST с автоматическим повтором при 429 (Too Many Requests).
    Ждём либо столько, сколько попросил сервер в заголовке Retry-After,
    либо по нарастающей (8с, 16с, 32с...) + случайный джиттер, чтобы
    не долбить сервер синхронными волнами запросов.
    """
    last_error = None
    for attempt in range(max_retries):
        resp = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/plain, */*"},
            timeout=20,
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else base_delay * (2 ** attempt)
            wait += random.uniform(0, 3)
            print(f"      429 Too Many Requests от Avito, жду {wait:.1f} сек "
                  f"(попытка {attempt + 1}/{max_retries})...")
            time.sleep(wait)
            last_error = requests.exceptions.HTTPError(
                f"429 Client Error: Too Many Requests for url: {url}"
            )
            continue
        resp.raise_for_status()
        return resp.json()
    raise last_error or RuntimeError(f"Не удалось получить ответ от {url}")


def resolve_vin(session, vin):
    """Шаг 1: резолвим VIN в структуру полей."""
    return _post_json_with_retry(session, RESOLVE_URL, {"number": vin})


def _owners_value_id(resolve_data, owners_label):
    """Находит valueId для выбранного количества владельцев по человекочитаемой метке ('1','2','3','4+')."""
    for field in resolve_data.get("fields", []):
        if field.get("id") == 1167:
            for v in field.get("values", []):
                if v.get("label") == str(owners_label):
                    return v["valueId"]
    raise ValueError(f"Не нашёл вариант владельцев '{owners_label}' в ответе resolve_vin")


def _vin_token(resolve_data):
    """Достаёт подписанный токен VIN (поле id=836), обязателен в запросе цены."""
    for field in resolve_data.get("fields", []):
        if field.get("id") == 836:
            return field.get("currentValueId")
    return None


def build_price_payload(resolve_data, mileage_km, owners_label, location=None):
    """Собирает fieldsValueIds: всё, что резолвер заполнил сам по VIN + пробег/владельцы, заданные вручную."""
    fields_value_ids = []

    for field in resolve_data.get("fields", []):
        fid = field.get("id")
        if fid in EXCLUDED_FIELD_IDS:
            continue
        current = field.get("currentValueId")
        if current is not None:
            fields_value_ids.append({"id": fid, "valueId": current})

    fields_value_ids.append({"id": 1167, "valueId": _owners_value_id(resolve_data, owners_label)})
    fields_value_ids.append({"id": 2687, "valueId": str(mileage_km)})

    return {
        "location": location or DEFAULT_LOCATION,
        "fieldsValueIds": fields_value_ids,
        "settings": {"fromPage": "landing", "vinHidden": True},
    }


def _find_price_fields(obj):
    """
    Реальная структура ответа /web/2/imv/price:
    obj["priceDescription"]["priceRanges"] - список из 3 диапазонов
    (greyLow / normal / greyHigh). Нужный нам - тот, где type == "normal":
    у него есть "min" и "max" - это и есть вилка "Авито Оценка".
    Плюс есть человекочитаемый дубль в priceDescription.emptyDescription
    вида "Авито Оценка: 629 400 — 799 600 ₽" - используем как fallback,
    если структура вдруг слегка поменяется.
    """
    result = {"price_low": None, "price_high": None, "raw_text": None}

    desc = obj.get("priceDescription", {})
    result["raw_text"] = desc.get("emptyDescription")

    for rng in desc.get("priceRanges", []):
        if rng.get("type") == "normal":
            result["price_low"] = rng.get("min")
            result["price_high"] = rng.get("max")
            break

    if result["price_low"] is None or result["price_high"] is None:
        # fallback: парсим текст "Авито Оценка: 629 400 — 799 600 ₽"
        import re
        text = result["raw_text"] or ""
        m = re.search(r"([\d\s]+)\s*[—-]\s*([\d\s]+)\s*₽", text)
        if m:
            result["price_low"] = int(re.sub(r"\D", "", m.group(1)))
            result["price_high"] = int(re.sub(r"\D", "", m.group(2)))

    return result


def get_field_current_value(resolve_data, field_id):
    """
    Достаёт currentValueId любого поля резолвера по его id - используется
    отдельным браузерным скриптом оценки (evaluate_avito_browser.py), чтобы
    прочитать год выпуска (id=164669), который сайт сам определил по VIN.
    """
    for field in resolve_data.get("fields", []):
        if field.get("id") == field_id:
            return field.get("currentValueId")
    return None


# Публичный алиас: другие модули (evaluate_avito_browser.py) переиспользуют
# уже проверенный парсер ответа /web/2/imv/price, не трогая "приватную" функцию.
parse_price_response = _find_price_fields


def _normalize_label(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def resolve_ambiguous_fields(resolve_data, hints):
    """
    Иногда Авито не может однозначно определить поле по VIN (см. скриншоты
    "Укажите параметры" - просит выбрать модель или год руками) - в этом
    случае currentValueId у такого поля просто отсутствует, зато полный
    список вариантов (values) сайт всё равно присылает сразу, в первом же
    ответе resolve/number. Значит довыбрать нужное можно самим, без
    дополнительных кликов по попапу - лишь бы знать, что выбирать.

    hints - словарь {label_поля: текстовая_подсказка}, например
    {"Марка": "NISSAN", "Модель": "TEANA", "Год выпуска": "2012"}.
    Подсказки для конкретного лота обычно берутся из TRONK (если лот уже
    оценивался там) или из текста самого лота (title часто содержит
    "марка X, модель Y, год выпуска Z").

    Возвращает (новые_данные, resolved_via_hint, unresolved):
      - resolved_via_hint - подписи полей, которые заполнили по подсказке
        (это ЗДОГАДКА, а не то, что сайт подтвердил сам - стоит пометить
        итоговую оценку как потенциально неточную)
      - unresolved - подписи полей, которые НЕ удалось определить ни по
        подсказке, ни автоматически (единственный вариант в списке) -
        для них цену запрашивать не стоит, слишком велик риск получить
        оценку совсем другого автомобиля.
    """
    data = copy.deepcopy(resolve_data)
    resolved_via_hint = []
    unresolved = []

    for field in data.get("fields", []):
        if field.get("currentValueId"):
            continue
        values = field.get("values") or []
        if not values:
            continue  # поля свободного ввода (пробег, владельцы) сюда не попадают

        label = field.get("label", "")
        hint_text = None
        for hint_label, text in (hints or {}).items():
            if _normalize_label(hint_label) == _normalize_label(label):
                hint_text = text
                break

        chosen = None
        via_hint = False
        if hint_text:
            norm_hint = _normalize_label(hint_text)
            for v in values:
                norm_val = _normalize_label(v.get("label", ""))
                if norm_val == norm_hint or norm_hint in norm_val or norm_val in norm_hint:
                    chosen = v
                    via_hint = True
                    break

        if chosen is None and len(values) == 1:
            chosen = values[0]  # единственный вариант - это не догадка, а факт

        if chosen:
            field["currentValueId"] = chosen["valueId"]
            if via_hint:
                resolved_via_hint.append(label)
        else:
            unresolved.append(label)

    return data, resolved_via_hint, unresolved


def get_price(session, resolve_data, mileage_km, owners_label, location=None):
    """Шаг 2: получаем вилку оценки."""
    payload = build_price_payload(resolve_data, mileage_km, owners_label, location)
    data = _post_json_with_retry(session, PRICE_URL, payload)
    prices = _find_price_fields(data)
    prices["raw_response"] = data  # на всякий случай сохраняем весь ответ
    return prices


def evaluate_by_vin(vin, mileage_km, owners_label="1", location=None):
    """Полный флоу: VIN -> вилка оценки."""
    session = make_session()
    resolve_data = resolve_vin(session, vin)
    time.sleep(0.5)
    return get_price(session, resolve_data, mileage_km, owners_label, location)


if __name__ == "__main__":
    import json
    import sys
    vin = sys.argv[1] if len(sys.argv) > 1 else "VF7NX5FEADY530542"
    mileage = int(sys.argv[2]) if len(sys.argv) > 2 else 90000
    owners = sys.argv[3] if len(sys.argv) > 3 else "2"
    result = evaluate_by_vin(vin, mileage, owners)
    print(json.dumps(result, ensure_ascii=False, indent=2))
