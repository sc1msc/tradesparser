# -*- coding: utf-8 -*-
"""
Оценка авто по VIN + пробегу через Авто.ру (https://auto.ru/evaluation/cars/),
С ЭМУЛЯЦИЕЙ БРАУЗЕРА (Playwright) - решение по аналогии с evaluate_avito_browser.py:
лотов немного, поэтому не гонимся за скоростью, зато надёжнее проходим через
антифрод (x-csrf-token/x-yafp выглядят как браузерная защита, которую сложно
и рискованно подделывать напрямую через requests).

ЧЕРНОВИК: структура ответа getStatsPredictByCarIdentifier пока не известна -
как только пришлют реальный response body, допишу parse_prediction_response().

Флоу (по образцу того, что реально видно в HAR):
  1) open https://auto.ru/evaluation/cars/
  2) ввести VIN в соответствующее поле формы
  3) ввести пробег
  4) отправить форму / дождаться срабатывания запроса
     getStatsPredictByCarIdentifier - перехватываем именно его через
     page.expect_response(), а не читаем результат из DOM
"""
import re
import time
import random

from playwright.sync_api import sync_playwright

LANDING_URL = "https://auto.ru/evaluation/cars/"
STATS_PREDICT_URL_PART = "getStatsPredictByCarIdentifier"

# Пробег - есть точный, стабильный селектор (атрибут name, не завязан на
# захэшированные CSS-модули, которые могут поменяться при пересборке сайта).
MILEAGE_INPUT_SELECTOR = 'input[name="mileage"]'

# VIN - точного селектора не видел (прислали только <div> с лейблом, не сам
# <input>). Ищем input, ближайший в DOM к тексту лейбла "Госномер или VIN" -
# это тот же компонент Input2, что и у поля пробега, значит <input> лежит
# рядом с этим текстом. Плюс пара запасных вариантов по вероятным name=
# (тело запроса резолва VIN использует ключ "identifier").
_VIN_LABEL_TEXT = "Госномер или VIN"

# Кнопка отправки - ищем по видимому тексту, а не по классу (классы
# захэшированы CSS-модулями и могут отличаться от сборки к сборке).
SUBMIT_BUTTON_TEXT = "Оценить бесплатно"

# Город продажи - обязательное поле с 07.10.2026: без него форма не
# отправляется (getStatsPredictByCarIdentifier не уходит, шаг падал по
# таймауту). Лоты - Москва и область, рынок один: для всех лотов "Москва"
# (решение пользователя). Поле - ввод с подсказками; выбрать нужно пункт
# подсказки, просто текст в поле форма не принимает.
CITY_INPUT_SELECTOR = 'input[name="city-information"]'
CITY_NAME = "Москва"
CITY_SUGGEST_ITEM_SELECTOR = 'li[class*="Dropdown2Item"]'


def _fill_vin(page, vin):
    """Пробуем несколько стратегий по очереди - на случай, если какая-то
    не сработает из-за особенностей вёрстки (не проверено вживую)."""
    strategies = [
        lambda: page.locator('input[name="vehicle-id"]'),  # так поле называется с 10.2026
        lambda: page.locator(
            f'xpath=//div[contains(text(),"{_VIN_LABEL_TEXT}")]/following::input[1]'
        ),
        lambda: page.locator('input[name="identifier"]'),
        lambda: page.locator('input[name="vin"]'),
        lambda: page.get_by_label(_VIN_LABEL_TEXT),
    ]
    last_error = None
    for make_locator in strategies:
        try:
            locator = make_locator()
            locator.wait_for(state="visible", timeout=3000)
            locator.fill(vin)
            return
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"Не удалось найти поле VIN ни одним из известных способов: {last_error}")


def _fill_city(page, city=CITY_NAME):
    """Город продажи: ввести название и выбрать пункт подсказки. Если поля
    нет (старая форма) или город уже выбран - ничего не делаем."""
    field = page.locator(CITY_INPUT_SELECTOR)
    if not field.count():
        return
    if field.input_value().strip().startswith(city):
        return
    field.click()
    field.fill("")
    field.press_sequentially(city, delay=random.randint(80, 150))
    item = page.locator(CITY_SUGGEST_ITEM_SELECTOR).filter(has_text=city).first
    try:
        item.wait_for(state="visible", timeout=5000)
        item.click()
    except Exception:
        # запасной путь - выбрать первую подсказку с клавиатуры
        field.press("ArrowDown")
        field.press("Enter")
    time.sleep(random.uniform(0.3, 0.6))
    if not field.input_value().strip().startswith(city):
        raise RuntimeError(f"Не удалось выбрать город продажи \"{city}\" (в поле: {field.input_value()!r})")


def parse_prediction_response(data):
    """
    Реальная структура ответа getStatsPredictByCarIdentifier:
      data["autoru"] = {"from": ..., "to": ..., "currency": "RUR",
                         "uncertainty_percent": ...}  - вилка цены на Авито.ру
      data["tradein"] = то же самое, но для трейд-ина у дилера (бонус-поле)
      data["found_info"] = {"mark","model","year","owners_count","mileage",...}
                            - то, что сайт сам определил по VIN
      data["need_info_for_evaluation"] = True, если по VIN не удалось
                            однозначно определить авто (аналог "Укажите
                            параметры" у Avito) - в этом случае цифрам
                            в autoru/tradein доверять не стоит.
    """
    autoru = data.get("autoru") or {}
    tradein = data.get("tradein") or {}
    found = data.get("found_info") or {}
    need_info = bool(data.get("need_info_for_evaluation"))

    return {
        "price_low": autoru.get("from"),
        "price_high": autoru.get("to"),
        "currency": autoru.get("currency"),
        "uncertainty_percent": autoru.get("uncertainty_percent"),
        "tradein_low": tradein.get("from"),
        "tradein_high": tradein.get("to"),
        "mark": found.get("mark"),
        "model": found.get("model"),
        "year": found.get("year"),
        "owners_count": found.get("owners_count"),
        "resolved_mileage": found.get("mileage"),
        "need_info_for_evaluation": need_info,
    }


def evaluate_by_vin(page, vin, mileage_km):
    page.goto(LANDING_URL, wait_until="domcontentloaded")
    time.sleep(random.uniform(1.0, 2.0))

    _fill_vin(page, vin)
    time.sleep(random.uniform(0.3, 0.7))

    page.locator(MILEAGE_INPUT_SELECTOR).fill(str(mileage_km))
    time.sleep(random.uniform(0.3, 0.7))

    _fill_city(page)

    with page.expect_response(
        lambda r: STATS_PREDICT_URL_PART in r.url, timeout=20000
    ) as resp_info:
        page.get_by_role("button", name=SUBMIT_BUTTON_TEXT).click()

    resp = resp_info.value
    if resp.status != 200:
        raise RuntimeError(f"getStatsPredictByCarIdentifier вернул статус {resp.status}")

    return parse_prediction_response(resp.json())


if __name__ == "__main__":
    import sys

    vin = sys.argv[1] if len(sys.argv) > 1 else "Z8NBBUJ32CS033053"
    mileage = int(sys.argv[2]) if len(sys.argv) > 2 else 80000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        result = evaluate_by_vin(page, vin, mileage)
        print(result)
        browser.close()
