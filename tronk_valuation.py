# -*- coding: utf-8 -*-
"""
Оценка автомобиля по VIN через платный API TRONK (data.tronk.info).
Документация: https://data.tronk.info/docs/avgpricebyvin

ВАЖНО: каждый вызов get_avg_price() - это платный запрос, деньги списываются
с аккаунта TRONK. Этот модуль НЕ вызывается автоматически ни из main.py, ни
из какого-либо другого места - только явным отдельным запуском:
  - python tronk_valuation.py <VIN>        - проверка ОДНОГО VIN, ничего не
                                              пишет в таблицу, только печатает
                                              ответ, и просит подтверждение
                                              перед отправкой запроса.
  - python evaluate_tronk.py               - массовая оценка лотов из таблицы,
                                              тоже с подтверждением и жёстким
                                              лимитом (config.TRONK_MAX_PER_RUN).
"""
import requests

BASE_URL = "https://data.tronk.info/avgpricebyvin.ashx"


def get_avg_price(api_key, vin, region_id=None, timeout=25):
    """
    Делает ОДИН платный запрос к TRONK. Возвращает распарсенный JSON как есть -
    парсинг/извлечение нужных полей вынесено в extract_valuation(), чтобы
    здесь оставалась только сама отправка запроса (легче тестировать и
    контролировать, где именно уходят деньги).
    """
    params = {"key": api_key, "vin": vin}
    if region_id:
        params["regionid"] = region_id
    resp = requests.get(BASE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def extract_valuation(data):
    """
    Превращает сырой ответ TRONK в плоский словарь для записи в таблицу.
    Согласно документации:
      - data["error"] == true (или truthy) -> ошибка, смотрим data["error_msg"]
      - data["result"] == null -> ничего не найдено по этому VIN
      - иначе result содержит price_avg/price_min/price_max/probeg_avg и т.д.
    """
    if data.get("error"):
        return {
            "status": f"error: {data.get('error_msg') or 'неизвестная ошибка'}",
            "price_avg": None, "price_min": None, "price_max": None, "mileage_avg": None,
            "marka": None, "model": None, "year": None,
        }

    result = data.get("result")
    if not result:
        return {
            "status": "no_data",
            "price_avg": None, "price_min": None, "price_max": None, "mileage_avg": None,
            "marka": None, "model": None, "year": None,
        }

    return {
        "status": "ok",
        "price_avg": result.get("price_avg"),
        "price_min": result.get("price_min"),
        "price_max": result.get("price_max"),
        "mileage_avg": result.get("probeg_avg"),
        # марка/модель/год - уже входят в этот же (оплаченный) ответ TRONK.
        # Используются как бесплатная подсказка для скрипта Авито-оценки,
        # когда Авито сам не может однозначно определить модель/год по VIN.
        "marka": result.get("marka"),
        "model": result.get("model"),
        "year": result.get("year"),
    }


if __name__ == "__main__":
    # Тестовый прогон на ОДНОМ VIN. Ничего не пишет в Google Таблицу.
    import sys
    import json
    import config

    if len(sys.argv) < 2:
        print("Использование: python tronk_valuation.py <VIN> [regionid]")
        raise SystemExit(1)

    vin = sys.argv[1].strip().upper()
    region = int(sys.argv[2]) if len(sys.argv) > 2 else config.TRONK_REGION_ID

    if config.TRONK_API_KEY.startswith("ВСТАВЬТЕ"):
        print("Сначала впишите настоящий TRONK_API_KEY в config.py")
        raise SystemExit(1)

    print(f"VIN: {vin}")
    print("ВНИМАНИЕ: это ПЛАТНЫЙ запрос к TRONK, деньги спишутся с вашего аккаунта.")
    answer = input("Отправить запрос? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, запрос не отправлен.")
        raise SystemExit(0)

    raw = get_avg_price(config.TRONK_API_KEY, vin, region)
    print("\n--- Сырой ответ TRONK ---")
    print(json.dumps(raw, ensure_ascii=False, indent=2))

    print("\n--- Извлечённые поля (то, что уйдёт в таблицу) ---")
    print(json.dumps(extract_valuation(raw), ensure_ascii=False, indent=2))
