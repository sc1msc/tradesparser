# -*- coding: utf-8 -*-
"""
Оценка лотов из Google Таблицы через форму Авито (https://www.avito.ru/evaluation/cars)
С ЭМУЛЯЦИЕЙ БРАУЗЕРА (Playwright), а не прямыми HTTP-запросами - см. историю
обсуждения: прямые запросы (requests) стабильно ловили 429 от антибота Qrator.

Запускается СТРОГО отдельно и вручную: python evaluate_avito_browser.py
Требует: pip install playwright && playwright install chromium

Логика по каждому лоту (в терминах, которыми вы её описали):
  1) вводим VIN в форму, жмём "Оценить"
  2) из ответа сайта (после клика "Оценить") достаём год выпуска -> пишем в avito_year (AF)
  3) владельцы: берём avito_owners (AG) из таблицы, если пусто - "4+"
  4) пробег: берём mileage_km (G), чистим от нецифровых символов (там либо
     пробег с карточки лота, либо пересчитанное на сегодня показание TRONK -
     см. fill_missing_mileage.py); только если пусто - считаем
     (текущий_год - avito_year) * config.ANNUAL_MILEAGE_KM
  5) если AG или "чистый" пробег из G были пустые - ставим пометку в
     avito_accuracy_note (AH): "Оценка может быть неточной"

ВАЖНОЕ ОТЛИЧИЕ от "буквального" сценария кликов по попапу "Укажите параметры":
шаги 3-5 отправляются не кликами по чекбоксам/полям попапа (эти селекторы
я не видел вживую и рисковал бы промахнуться), а тем же самым запросом,
который в итоге уходит на сервер при нажатии "Показать оценку" - но
отправленным через fetch() ИЗНУТРИ той же браузерной страницы
(page.evaluate), то есть из настоящей аутентифицированной сессии браузера.
Логика сборки этого запроса - та же самая, что уже проверена в
avito_valuation.py (build_price_payload), просто транспорт другой.

Если это всё равно будет банится - следующий шаг эскалации: открыть форму
самим через Playwright codegen (`playwright codegen https://www.avito.ru/evaluation/cars`),
подтвердить/поправить реальные селекторы попапа и переписать шаги 3-5 на
настоящие клики - я не могу сделать это вслепую без живого браузера.
"""
import re
import time
import random
import datetime

from playwright.sync_api import sync_playwright

import config
import sheets_writer
import avito_valuation


CURRENT_YEAR = datetime.datetime.now().year
YEAR_FIELD_ID = 164669  # "Год выпуска" в схеме резолвера Avito (см. avito_valuation.py)

VIN_INPUT_SELECTOR = '[data-marker="landing/vin-gos-input/input"]'
ESTIMATE_BUTTON_SELECTOR = '[data-marker="landing/estimate-button"]'

# Извлечение марки/модели/года из ТЕКСТА самого лота (title) - бесплатный
# источник подсказки для disambiguation, когда Авито не смог определить
# модель/год сам по VIN (см. скриншоты "Укажите параметры"). Управляющие
# почти всегда пишут в заголовке в духе "марка NISSAN, модель TEANA,
# год выпуска 2012" - на этом формате регулярки и построены.
MARKA_RE = re.compile(r"марка[:\s]+([^,\.]+)", re.IGNORECASE)
MODEL_RE = re.compile(r"модель[:\s]+([^,\.]+)", re.IGNORECASE)
TITLE_YEAR_RE = re.compile(r"год\s+(?:выпуска|изготовления)[:\s]+(\d{4})", re.IGNORECASE)


def _build_hints(row):
    """
    Собирает подсказки марка/модель/год для disambiguation. Приоритет:
    1) уже оплаченные данные TRONK, если лот через evaluate_tronk.py уже
       оценивался (новых платных запросов отсюда НЕ делаем);
    2) бесплатный regex-разбор title лота, если TRONK-данных нет.
    """
    title = row.get("title") or ""

    marka = (row.get("tronk_marka") or "").strip()
    if not marka:
        m = MARKA_RE.search(title)
        marka = m.group(1).strip() if m else ""

    model = (row.get("tronk_model") or "").strip()
    if not model:
        m = MODEL_RE.search(title)
        model = m.group(1).strip() if m else ""

    year = (row.get("tronk_year") or "").strip()
    if not year:
        m = TITLE_YEAR_RE.search(title)
        year = m.group(1) if m else ""

    hints = {}
    if marka:
        hints["Марка"] = marka
    if model:
        hints["Модель"] = model
    if year:
        hints["Год выпуска"] = str(year)
    return hints

# Текст со страницы капчи Qrator ("Доступ ограничен: проблема с IP") -
# по нему определяем, что вместо формы оценки показали челлендж.
QRATOR_CHALLENGE_MARKER = "Доступ ограничен"


def _wait_past_qrator_challenge(page):
    """
    Если вместо страницы оценки показалась капча/челлендж Qrator - скрипт
    не может решить её сам (это и есть весь смысл такой защиты). Раз браузер
    открыт не в headless-режиме, человек видит то же окно - ставим выполнение
    на паузу и просим решить капчу руками (нажать "Продолжить" и, если
    появится, пройти проверку), затем продолжаем по Enter.
    """
    try:
        content = page.content()
    except Exception:
        return
    if QRATOR_CHALLENGE_MARKER not in content:
        return

    print("\n  !! Похоже, показалась капча Qrator ('Доступ ограничен: проблема с IP').")
    print("     В открывшемся окне браузера решите её вручную (кнопка «Продолжить»,")
    print("     возможно потребуется пройти проверку).")
    input("     Когда сайт снова откроется нормально - нажмите Enter здесь, чтобы продолжить...")


def _clean_mileage(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def select_candidates(rows):
    """Лоты с VIN, которые ещё не оценены (avito_status != 'ok')."""
    candidates = []
    for r in rows:
        vin = (r.get("vin") or "").strip()
        if not vin:
            continue
        if (r.get("avito_status") or "").strip() == "ok":
            continue
        candidates.append(r)
    return candidates


def _fill_vin(page, vin):
    """Пробуем .fill(), а если элемент под data-marker - не сам <input>
    (а обёртка), кликаем и печатаем через клавиатуру - это работает в обоих случаях."""
    locator = page.locator(VIN_INPUT_SELECTOR)
    try:
        locator.fill(vin, timeout=5000)
    except Exception:
        locator.click()
        page.keyboard.type(vin, delay=random.randint(40, 90))


def process_lot(page, row):
    vin = row["vin"].strip().upper()

    page.goto(avito_valuation.LANDING_URL, wait_until="domcontentloaded")
    time.sleep(random.uniform(1.0, 2.0))  # дать странице догрузиться, повести себя "по-человечески"

    _wait_past_qrator_challenge(page)

    _fill_vin(page, vin)
    time.sleep(random.uniform(0.3, 0.8))

    with page.expect_response(lambda r: "resolve/number" in r.url, timeout=20000) as resp_info:
        page.locator(ESTIMATE_BUTTON_SELECTOR).click()
    resolve_resp = resp_info.value
    if resolve_resp.status != 200:
        raise RuntimeError(f"resolve/number вернул статус {resolve_resp.status}")
    resolve_data = resolve_resp.json()

    hints = _build_hints(row)
    resolve_data, resolved_via_hint, unresolved = avito_valuation.resolve_ambiguous_fields(
        resolve_data, hints
    )
    if unresolved:
        raise RuntimeError(
            "Авито не смог однозначно определить: " + ", ".join(unresolved) +
            " - и подсказки не хватило (нет данных TRONK и не удалось разобрать title)"
        )

    year_raw = avito_valuation.get_field_current_value(resolve_data, YEAR_FIELD_ID)
    year = int(year_raw) if year_raw else None

    owners_raw = (row.get("avito_owners") or "").strip()
    owners_label = owners_raw if owners_raw else "4+"

    mileage_from_sheet = _clean_mileage(row.get("mileage_km"))
    mileage_was_missing = mileage_from_sheet is None
    if mileage_from_sheet is not None:
        mileage = mileage_from_sheet
    elif year:
        mileage = max((CURRENT_YEAR - year) * config.ANNUAL_MILEAGE_KM, 0)
    else:
        mileage = 100000  # крайний случай: и пробег, и год неизвестны

    payload = avito_valuation.build_price_payload(resolve_data, mileage, owners_label)

    result = page.evaluate(
        """
        async (payload) => {
            const resp = await fetch('https://www.avito.ru/web/2/imv/price', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/plain, */*'
                },
                credentials: 'include',
                body: JSON.stringify(payload)
            });
            const body = await resp.json();
            return {status: resp.status, body: body};
        }
        """,
        payload,
    )

    if result["status"] != 200:
        raise RuntimeError(f"imv/price вернул статус {result['status']}")

    prices = avito_valuation.parse_price_response(result["body"])
    inaccurate = (not owners_raw) or mileage_was_missing or bool(resolved_via_hint)

    return {
        "year": year,
        "price_low": prices.get("price_low"),
        "price_high": prices.get("price_high"),
        "inaccurate": inaccurate,
        "resolved_via_hint": resolved_via_hint,
    }


def run():
    print("Подключаюсь к Google Таблице...")
    worksheet = sheets_writer.connect(
        config.SERVICE_ACCOUNT_FILE, config.SPREADSHEET_ID, config.WORKSHEET_NAME
    )
    rows = sheets_writer.read_rows(worksheet)
    candidates = select_candidates(rows)
    print(f"Кандидатов на оценку (есть VIN, ещё не оценены): {len(candidates)}")

    if not candidates:
        print("Нечего оценивать, выхожу.")
        return

    to_process = candidates[: config.AVITO_BROWSER_MAX_PER_RUN]
    skipped = len(candidates) - len(to_process)
    print(f"Лимит за запуск: {config.AVITO_BROWSER_MAX_PER_RUN}. Будет обработано сейчас: {len(to_process)}")
    if skipped:
        print(f"Ещё {skipped} лотов дождутся следующего запуска.")
    for r in to_process:
        print(f"  - lot_id={r.get('lot_id')} vin={r.get('vin')} | {(r.get('title') or '')[:60]}")

    answer = input("\nЗапустить браузер и начать оценку? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено.")
        return

    processed = 0
    ok_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.AVITO_BROWSER_HEADLESS)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        for row in to_process:
            row_num = row["_row_num"]
            lot_id = row.get("lot_id")
            print(f"\n[{lot_id}] VIN={row['vin']} ...")

            # Собираем все поля лота и пишем одним batch_update() вместо
            # отдельного set_cell() на каждое (было до 6 запросов на лот).
            updates = {
                "avito_checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            try:
                result = process_lot(page, row)
                updates["avito_year"] = result["year"]
                updates["avito_price_low"] = result["price_low"]
                updates["avito_price_high"] = result["price_high"]
                if result["inaccurate"]:
                    updates["avito_accuracy_note"] = "Оценка может быть неточной"
                updates["avito_status"] = "ok"
                print(
                    f"  -> год={result['year']} цена={result['price_low']}-{result['price_high']}"
                    f"{' (неточно)' if result['inaccurate'] else ''}"
                )
                if result["resolved_via_hint"]:
                    print(f"     (по подсказке досопоставлено: {', '.join(result['resolved_via_hint'])})")
                ok_count += 1
            except Exception as e:
                print(f"  Ошибка: {e}")
                updates["avito_status"] = f"error: {e}"[:200]

            sheets_writer.batch_set_cells(worksheet, row_num, updates)
            processed += 1
            time.sleep(config.DELAY_BETWEEN_AVITO_BROWSER_REQUESTS + random.uniform(0, 2))

        browser.close()

    print(f"\nГотово. Обработано: {processed}, успешно: {ok_count}.")


if __name__ == "__main__":
    run()