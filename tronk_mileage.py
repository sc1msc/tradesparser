# -*- coding: utf-8 -*-
"""
Пробег по VIN через ПЛАТНЫЕ, но дешёвые методы TRONK - probeg или probeg2.
Какой метод использовать - config.MILEAGE_METHOD.
Документация: https://data.tronk.info/docs/probeg, .../probeg2

  probeg  (~1.10 руб/запрос) - одно, самое свежее известное показание.
  probeg2 (~2.10 руб/запрос) - история из нескольких источников (СТО,
          объявления, техосмотр, таможня, полевые осмотры) - точнее за
          счёт кросс-проверки, но чуть дороже.

Оба - на порядок дешевле, чем спрашивать полную оценку avgpricebyvin
только ради пробега (там пробег - лишь побочный показатель).

ВАЖНО: каждый вызов get_mileage_history() - платный запрос, деньги
списываются с аккаунта TRONK. Этот модуль не вызывается автоматически -
только явным запуском fill_missing_mileage.py (с подтверждением стоимости).
"""
import datetime
import re

import requests

ENDPOINTS = {
    "probeg": "https://data.tronk.info/probeg.ashx",
    "probeg2": "https://data.tronk.info/probeg2.ashx",
}

# Ориентировочная цена за запрос - см. https://data.tronk.info/price.
# Используется только для оценки стоимости прогона ПЕРЕД подтверждением -
# сверяйте с реальным прайсом, если TRONK его поменяет.
PRICE_PER_REQUEST_RUB = {
    "probeg": 1.10,
    "probeg2": 2.10,
}


def get_mileage_history(api_key, vin, method, timeout=25):
    """Делает ОДИН платный запрос к TRONK (метод - 'probeg' или 'probeg2').
    Возвращает распарсенный JSON как есть - извлечение нужного значения
    вынесено в extract_latest_mileage(), чтобы здесь оставалась только
    сама отправка запроса (легче тестировать и контролировать, где именно
    уходят деньги).

    liverequest=1 - явно просим TRONK сходить к источникам, а не отдавать
    то, что уже есть в кэше. По этим VIN (машины с банкротных торгов)
    в кэше почти наверняка пусто - без этого параметра метод, скорее
    всего, каждый раз отвечал бы "нет данных", даже когда у TRONK данные
    по источникам реально есть."""
    if method not in ENDPOINTS:
        raise ValueError(
            f"Неизвестный метод TRONK для пробега: {method!r} "
            f"(ожидается 'probeg' или 'probeg2')"
        )
    params = {"key": api_key, "vin": vin, "liverequest": 1}
    resp = requests.get(ENDPOINTS[method], params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


_DOTNET_DATE_RE = re.compile(r"/Date\((-?\d+)")
_DATE_FORMATS = (
    "%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y", "%m.%Y",
)
_MIN_PLAUSIBLE_DATE = datetime.date(1980, 1, 1)


def _plausible(d):
    """Отсекаем мусор (0 -> 1970 год, даты из будущего и т.п.)."""
    return d is not None and _MIN_PLAUSIBLE_DATE <= d <= datetime.date.today() + datetime.timedelta(days=1)


def _date_from_timestamp(value):
    try:
        ts = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if ts > 10 ** 11:  # похоже на миллисекунды
        ts //= 1000
    try:
        d = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return d if _plausible(d) else None


def parse_date(value):
    """Разбирает дату показания пробега из строки в одном из встречающихся
    форматов (ДД.ММ.ГГГГ, ГГГГ-ММ-ДД, ISO, .NET "/Date(1700000000000)/").
    Возвращает datetime.date или None."""
    if not value:
        return None
    text = str(value).strip()

    m = _DOTNET_DATE_RE.search(text)
    if m:
        return _date_from_timestamp(m.group(1))

    for fmt in _DATE_FORMATS:
        try:
            d = datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return d if _plausible(d) else None

    try:
        d = datetime.datetime.fromisoformat(text).date()
    except ValueError:
        return None
    return d if _plausible(d) else None


def _entry_date(entry):
    """Дата одной записи TRONK: сначала Datesecond (метка времени), если она
    кривая или пустая - строка Date."""
    return _date_from_timestamp(entry.get("Datesecond")) or parse_date(entry.get("Date"))


def _unwrap_entry(entry):
    """
    На практике (не по документации!) probeg заворачивает единственную
    запись ещё в один слой - result это не {Probeg, Date, ...} напрямую,
    а {"m_probeg": {Probeg, Date, ...}}:

        {"result": {"m_probeg": {"Probeg": 140000, "Date": "...", ...}}}

    Разворачиваем именно эту, подтверждённую реальным ответом обёртку.
    """
    if isinstance(entry, dict) and "Probeg" not in entry and "m_probeg" in entry:
        return entry["m_probeg"]
    return entry


def extrapolate_mileage(mileage_km, measured_on, annual_km, today=None):
    """
    Пересчитывает показание пробега на сегодняшний день: к значению на
    дату measured_on добавляем annual_km за каждый прошедший год (дробно,
    по дням). Если дата неизвестна или в будущем - прибавлять нечего,
    возвращаем как есть.
    """
    if mileage_km is None:
        return None
    if measured_on is None:
        return int(mileage_km)
    today = today or datetime.date.today()
    years = max((today - measured_on).days, 0) / 365.25
    return int(round(mileage_km + annual_km * years))


def extract_latest_mileage(data):
    """
    Превращает сырой ответ probeg/probeg2 в одно число - самое свежее (по
    дате) показание пробега - плюс откуда оно взято.

    result у probeg - ОДИН объект (на практике завёрнутый в "m_probeg" -
    см. _unwrap_entry, документация это не показывает); у probeg2 -
    СПИСОК таких объектов из разных источников (порядок не гарантирован
    документацией). Обрабатываем оба варианта одинаково - приводим к
    списку и берём самую свежую по дате запись, а не первую попавшуюся.

    Пустой result (null/{}/[])  - по этому VIN данных нет.

    Возвращает СЫРОЕ показание на дату замера (mileage_km) и саму дату
    (mileage_date_obj - datetime.date или None, mileage_date - строка
    ГГГГ-ММ-ДД или исходная строка, если разобрать не удалось). Пересчёт
    на сегодня - отдельно, extrapolate_mileage().
    """
    empty = {
        "mileage_km": None, "mileage_date": None, "mileage_date_obj": None,
        "mileage_source": None,
    }

    if data.get("error"):
        return {"status": f"error: {data.get('error_msg') or 'неизвестная ошибка'}", **empty}

    result = data.get("result")
    if not result:
        return {"status": "no_data", **empty}

    if isinstance(result, dict):
        entries = [result]
    elif isinstance(result, list):
        entries = result
    else:
        return {"status": f"error: неожиданный формат result ({type(result).__name__})", **empty}

    entries = [_unwrap_entry(e) for e in entries if isinstance(e, dict)]
    if not entries:
        return {"status": "no_data", **empty}

    latest = max(entries, key=lambda e: _entry_date(e) or datetime.date.min)
    measured_on = _entry_date(latest)

    digits = re.sub(r"\D", "", str(latest.get("Probeg") or ""))
    mileage_km = int(digits) if digits else None

    return {
        "status": "ok" if mileage_km else "no_data",
        "mileage_km": mileage_km,
        "mileage_date": measured_on.isoformat() if measured_on else latest.get("Date"),
        "mileage_date_obj": measured_on,
        "mileage_source": latest.get("SourceName"),
    }


if __name__ == "__main__":
    # Тестовый прогон на ОДНОМ VIN. Ничего не пишет в Google Таблицу.
    import sys
    import json
    import config

    if len(sys.argv) < 2:
        print("Использование: python tronk_mileage.py <VIN> [probeg|probeg2]")
        raise SystemExit(1)

    vin = sys.argv[1].strip().upper()
    method = sys.argv[2] if len(sys.argv) > 2 else config.MILEAGE_METHOD

    if config.TRONK_API_KEY.startswith("ВСТАВЬТЕ"):
        print("Сначала впишите настоящий TRONK_API_KEY в config.py")
        raise SystemExit(1)

    price = PRICE_PER_REQUEST_RUB.get(method, "?")
    print(f"VIN: {vin}, метод: {method}")
    print(f"ВНИМАНИЕ: это ПЛАТНЫЙ запрос к TRONK (~{price} руб).")
    answer = input("Отправить запрос? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, запрос не отправлен.")
        raise SystemExit(0)

    raw = get_mileage_history(config.TRONK_API_KEY, vin, method)
    print("\n--- Сырой ответ TRONK ---")
    print(json.dumps(raw, ensure_ascii=False, indent=2))

    fields = extract_latest_mileage(raw)
    print("\n--- Извлечённое значение ---")
    print(json.dumps(fields, ensure_ascii=False, indent=2, default=str))

    estimated = extrapolate_mileage(
        fields["mileage_km"], fields["mileage_date_obj"], config.ANNUAL_MILEAGE_KM
    )
    print(f"\nПересчёт на сегодня ({config.ANNUAL_MILEAGE_KM} км/год): {estimated}")