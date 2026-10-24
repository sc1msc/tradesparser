# -*- coding: utf-8 -*-
r"""
Массовая оценка лотов через форму Авто.ру (эмуляция браузера,
см. autoru_valuation.py) - ТОЛЬКО для актуальных лотов из листа
"lots_current_month" (не всей базы "lots"/"lots_processed" - незачем
считать оценку для лотов, торги по которым ещё нескоро или уже прошли).

Работает с листом напрямую через gspread (та же схема доступа, что у
build_lots_processed.py/build_lots_current_month.py) - НЕ через
sheets_writer.py, его локальная схема колонок разошлась с реальной
таблицей. Сам добавляет недостающие колонки в шапку при первом запуске:
    estimated_mileage (колонка P)                        - см. ниже
    autoru_price_low, autoru_price_high,
    autoru_tradein_low, autoru_tradein_high,
    autoru_uncertainty_percent, autoru_mark, autoru_model,
    autoru_year, autoru_owners_count, autoru_accuracy_note,
    autoru_status, autoru_checked_at,
    autoru_engine_type, autoru_displacement, autoru_power,       - характеристики
    autoru_drive, autoru_transmission, autoru_modification        модификации (с 13.10.2026)
    autoru_body_type, autoru_body                                  - кузов (с 24.10.2026)

ХАРАКТЕРИСТИКИ (топливо, объём см³, мощность л.с., привод, коробка, название
модификации "1.6 AT (110 л.с.)") приходят вместе с оценкой - см.
autoru_valuation.parse_specs; пишутся в лист и в vin_cache вместе с ценой.

ДОЗАПОЛНЕНИЕ характеристик у уже оценённых лотов: с 20.10.2026 - в конце каждого
прогона, config.AUTORU_SPECS_PER_RUN машин, без ожидания Enter; вручную - сколько угодно:
    python evaluate_autoru_browser.py --specs [N]
Лоты со статусом ok/ambiguous без характеристик, одна оценка на VIN (машина на
нескольких площадках - один запрос), не больше N машин за запуск (по умолчанию
config.AUTORU_MAX_PER_RUN). Пишутся ТОЛЬКО колонки характеристик - цена и статус
не меняются. Перед заполнением формы скрипт открывает Авто.ру и ждёт Enter:
кнопку согласия на сайте владелец нажимает сам. Повторный запуск продолжает с
тех, у кого характеристик ещё нет.

Пробег для запроса к Авто.ру берётся из mileage_km (там либо пробег с
карточки лота, либо показание TRONK, пересчитанное на сегодня - см.
fill_missing_mileage.py); только если он пуст или неправдоподобен (больше
lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM) - из estimated_mileage,
который сам же и считает по формуле (как для Avito):
(текущий_год - year) * config.ANNUAL_MILEAGE_KM. Если и year пуст -
пробег взять неоткуда, лот помечается "no_mileage" и пропускается.

ВАЖНО: build_lots_current_month.py при пересборке списка актуальных
лотов сохраняет все эти колонки по совпадению VIN - можно спокойно
перезапускать оба скрипта в любом порядке, уже сделанная работа не
потеряется (см. правки в build_lots_current_month.py).

Как и у Avito - Авто.ру сам резолвит марку/модель/год по VIN в том же
ответе, где отдаёт вилку цены. Если need_info_for_evaluation==true -
однозначно определить авто не удалось, цифрам доверять не стоит - статус
"ambiguous", а не "ok".
"""
import re
import time
import random
import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

import automation
import config
import lot_metrics
import autoru_valuation
import sheets_writer
import vin_cache

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "lots_current_month"
CURRENT_YEAR = datetime.datetime.now().year
# Условный пробег для запроса "какой это год" (у лота нет ни года, ни пробега):
# цена из этого ответа не используется, нужен только год, который Авто.ру
# определяет по VIN.
PROBE_MILEAGE_KM = 100000

# Госномер - когда у лота нет VIN: поле формы Авто.ру называется "Госномер или
# VIN" и принимает и то и другое (с 11.10.2026 так оцениваются ~2% лотов, раньше
# они оставались без оценки). Номер - из колонки plate, иначе из названия лота.
def _lot_plate(row, col):
    """Госномер лота ("Р131КТ77") для формы Авто.ру или None: тот же разбор,
    что у парсера (lot_metrics.find_plate - и латиница, и номер, склеенный со
    следующим словом)."""
    return lot_metrics.find_plate(row[col["plate"]] if "plate" in col else "") or \
        lot_metrics.find_plate(row[col["title"]] if "title" in col else "")

# Колонки, которые скрипт сам добавляет в шапку, если их ещё нет -
# именно в этом порядке (дописываются в конец листа).
NEW_COLUMNS = [
    "estimated_mileage",
    "autoru_price_low", "autoru_price_high",
    "autoru_tradein_low", "autoru_tradein_high",
    "autoru_uncertainty_percent", "autoru_mark", "autoru_model",
    "autoru_year", "autoru_owners_count", "autoru_accuracy_note",
    "autoru_status", "autoru_checked_at",
] + vin_cache.AUTORU_SPEC_FIELDS


def _spec_updates(result):
    """Характеристики из ответа оценки (autoru_valuation) -> {колонка: значение}."""
    return {
        "autoru_engine_type": result.get("engine_type"),
        "autoru_displacement": result.get("displacement"),
        "autoru_power": result.get("power"),
        "autoru_drive": result.get("drive"),
        "autoru_transmission": result.get("transmission"),
        "autoru_modification": result.get("modification"),
        "autoru_body_type": result.get("body_type"),
        "autoru_body": result.get("body"),
    }


def _clean_mileage(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def _estimate_mileage(year_str):
    if not year_str:
        return None
    try:
        year = int(year_str)
    except ValueError:
        return None
    return max((CURRENT_YEAR - year) * config.ANNUAL_MILEAGE_KM, 0)


def _ensure_columns(worksheet, header):
    """Дописывает в шапку недостающие колонки из NEW_COLUMNS. Возвращает
    обновлённый header (список имён)."""
    missing = [c for c in NEW_COLUMNS if c not in header]
    if not missing:
        return header
    new_header = header + missing
    worksheet.update(range_name="A1", values=[new_header])
    print(f"Добавил в шапку колонки: {missing}")
    return new_header


def _batch_write(worksheet, row_num, col, updates):
    """
    Пишет все ячейки одного лота ОДНИМ запросом к Sheets API вместо
    отдельного update_cell() на каждое поле. Критично для квоты Google
    (60 write-запросов/мин на пользователя) - раньше на один лот уходило
    до 13 отдельных запросов подряд без паузы между ними, чего хватало,
    чтобы упереться в лимит даже при небольшом числе лотов за прогон.

    updates: {имя_колонки: значение}. Пустые/None значения не пишем -
    нечего записывать нулём поверх того, чего не получили.
    """
    data = []
    for name, value in updates.items():
        if value is None:
            continue
        cell = gspread.utils.rowcol_to_a1(row_num, col[name] + 1)
        data.append({"range": cell, "values": [[value]]})
    if data:
        # таймаут или 5xx Google - повтор, а не падение всего шага (так упало дозаполнение 13.10.2026)
        sheets_writer.batch_update_retry(worksheet, data)


def run(specs_only=False, limit=None):
    if specs_only:
        return run_specs(limit)
    stopped = _run_estimates()
    # Дозаполнение характеристик у старых оценок (до 13.10.2026 характеристики не сохранялись, а цена
    # из справочника по VIN переходит в новые лоты без них - так у Touareg 7233557 не было объёма и
    # мощности). Бесплатно, AUTORU_SPECS_PER_RUN машин за прогон, после новых оценок; Авто.ру
    # остановил оценку (капча, ошибки подряд) - не трогаем. Сбой здесь шаг не роняет.
    if stopped or not getattr(config, "AUTORU_SPECS_PER_RUN", 0):
        return
    # обрыв связи с Google (21.10.2026: ConnectionResetError при чтении листа) - одна повторная попытка
    for attempt in (1, 2):
        try:
            run_specs(config.AUTORU_SPECS_PER_RUN, interactive=False)
            return
        except Exception as e:
            if attempt == 1:
                print(f"Дозаполнение характеристик: {str(e)[:150]} - повтор через 60 с")
                time.sleep(60)
            else:
                automation.alert(f"Авто.ру: дозаполнение характеристик не прошло ({str(e)[:150]}), повторится завтра.")


def _run_estimates():
    """Новые оценки. -> True, если Авто.ру остановил шаг (капча, ошибки подряд) или его отменили."""
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    values = worksheet.get_all_values()
    if not values:
        print(f"Лист '{SHEET_NAME}' пуст.")
        return

    header = _ensure_columns(worksheet, values[0])
    col = {name: idx for idx, name in enumerate(header)}  # 0-based индекс по имени

    for field in ("vin", "year", "mileage_km"):
        if field not in col:
            print(f'В шапке не нашёл колонку "{field}".')
            return

    data_rows = values[1:]

    candidates = []  # (row_num, row_list)
    for i, row in enumerate(data_rows):
        while len(row) < len(header):
            row.append("")
        status = row[col["autoru_status"]].strip()
        has_price = bool(row[col["autoru_price_low"]].strip() and row[col["autoru_price_high"]].strip())
        if status in ("ambiguous", "no_price") or (status == "ok" and has_price):
            continue
        # VIN, а без него - госномер (Авто.ру принимает и то и другое)
        vin = row[col["vin"]].strip()
        if len(vin) != 17:
            vin = _lot_plate(row, col)
        if not vin:
            continue
        # Мультилот (несколько машин одним лотом) не оцениваем: вилка одной
        # машины к цене всего лота отношения не имеет (lot_metrics.lot_kind).
        if "lot_kind" in col and row[col["lot_kind"]].strip() == lot_metrics.LOT_MULTILOT:
            continue
        candidates.append((i + 2, row))  # 1-based номер строки (шапка - строка 1)

    print(f"Кандидатов на оценку (есть VIN, ещё не оценены, лот актуален): {len(candidates)}")
    if not candidates:
        print("Нечего оценивать, выхожу.")
        return

    to_process = candidates[: config.AUTORU_MAX_PER_RUN]
    skipped = len(candidates) - len(to_process)
    print(f"Лимит за запуск: {config.AUTORU_MAX_PER_RUN}. Будет обработано сейчас: {len(to_process)}")
    if skipped:
        print(f"Ещё {skipped} лотов дождутся следующего запуска.")
    for row_num, row in to_process:
        title_preview = row[col["title"]][:60] if "title" in col else ""
        print(f"  - vin={row[col['vin']]} | {title_preview}")

    if not automation.confirm("\nЗапустить браузер и начать оценку? (yes / нет): "):
        print("Отменено.")
        return True

    processed = 0
    ok_count = 0
    errors_in_row = 0
    stopped = False
    # Готовые оценки - ещё и в справочник по VIN: переживут выпадение лота
    # из среза и пригодятся, если машину выставят снова (vin_cache.py).
    cache = vin_cache.VinCache(spreadsheet)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.AUTORU_HEADLESS)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        for row_num, row in to_process:
            vin = row[col["vin"]].strip().upper()
            if len(vin) != 17:  # нет VIN - оцениваем по госномеру (см. отбор кандидатов)
                vin = _lot_plate(row, col)
            raw_mileage = _clean_mileage(row[col["mileage_km"]])
            # Больше lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM - ошибка источника
            # (TRONK/текст лота): считаем, что пробега нет, и оцениваем по году.
            mileage = lot_metrics.plausible_mileage(raw_mileage)
            mileage_source = "mileage_km"
            if raw_mileage is not None and mileage is None:
                print(f"  Пробег {raw_mileage} км неправдоподобен - считаю по году выпуска")
            updates = {}  # копим все поля этого лота, пишем одним batch_update в конце

            if mileage is None:
                mileage = _estimate_mileage(row[col["year"]])
                mileage_source = "estimated_mileage"
                if mileage is not None:
                    updates["estimated_mileage"] = mileage

            print(f"\n[{vin}] пробег={mileage} (источник: {mileage_source}) ...")

            if mileage is None:
                # Ни пробега, ни года в листе (раньше год давал декодер Autodoc - он
                # с 10.2026 не отвечает, а год из 10-го символа VIN верен лишь в
                # половине случаев). Год спрашиваем у самого Авто.ру: он определяет
                # машину по VIN. Первый запрос - с условным пробегом, только ради года;
                # второй, ниже, - уже с пробегом по этому году, ради цены.
                try:
                    probe = autoru_valuation.evaluate_by_vin(page, vin, PROBE_MILEAGE_KM)
                    if not probe.get("year") and not probe.get("mark"):
                        # Авто.ру машину не опознал (бывает со сменившимся госномером) -
                        # как и прочие "не знает", не повторяем каждый день
                        print("  -> Авто.ру не опознал машину")
                        updates["autoru_status"] = "no_price"
                        updates["autoru_checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                        _batch_write(worksheet, row_num, col, updates)
                        processed += 1
                        time.sleep(config.DELAY_BETWEEN_AUTORU_REQUESTS + random.uniform(0, 2))
                        continue
                    if probe.get("year"):
                        mileage = _estimate_mileage(str(probe["year"]))
                        mileage_source = f"estimated_mileage (год {probe['year']} - от Авто.ру)"
                        updates["estimated_mileage"] = mileage
                        print(f"  Года нет - Авто.ру определил по VIN: {probe['year']} г., пробег по году {mileage}")
                        time.sleep(config.DELAY_BETWEEN_AUTORU_REQUESTS + random.uniform(0, 2))
                except Exception as e:
                    print(f"  Не удалось узнать год у Авто.ру: {e}")

            if mileage is None:
                print("  Ни пробега, ни года - взять пробег неоткуда, пропускаю")
                updates["autoru_status"] = "no_mileage"
                updates["autoru_checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                _batch_write(worksheet, row_num, col, updates)
                processed += 1
                continue

            try:
                result = autoru_valuation.evaluate_by_vin(page, vin, mileage)

                updates["autoru_price_low"] = result["price_low"]
                updates["autoru_price_high"] = result["price_high"]
                updates["autoru_tradein_low"] = result["tradein_low"]
                updates["autoru_tradein_high"] = result["tradein_high"]
                updates["autoru_uncertainty_percent"] = result["uncertainty_percent"]
                updates["autoru_mark"] = result["mark"]
                updates["autoru_model"] = result["model"]
                updates["autoru_year"] = result["year"]
                updates["autoru_owners_count"] = result["owners_count"]
                updates.update(_spec_updates(result))

                if result["need_info_for_evaluation"]:
                    status = "ambiguous"
                    updates["autoru_accuracy_note"] = "Оценка может быть неточной"
                    print("  -> ВНИМАНИЕ: Авто.ру не смог однозначно определить авто по VIN")
                elif result["price_low"] is None or result["price_high"] is None:
                    # Авто.ру не знает эту машину (грузовик, автобус, спецтехника,
                    # американский рынок) - раньше такие лоты получали "ok" без цены
                    status = "no_price"
                    print("  -> Авто.ру не дал цену: машину не знает")
                else:
                    status = "ok"
                    ok_count += 1

                updates["autoru_status"] = status
                print(
                    f"  -> цена={result['price_low']}-{result['price_high']} "
                    f"({result['mark']} {result['model']}, {result['year']} г.)"
                )
            except Exception as e:
                print(f"  Ошибка: {e}")
                if "showcaptcha" in page.url:
                    # капча: лот не портим ошибкой (проверится в следующий раз),
                    # ждём человека; не решили - останавливаем шаг
                    if not _wait_captcha(page):
                        automation.alert(f"Авто.ру просит капчу, её не решили за {config.AUTORU_CAPTCHA_WAIT_MIN} мин. "
                                         f"Оценено {ok_count} лотов, остальные {len(to_process) - processed} - "
                                         f"в следующий прогон.")
                        stopped = True
                        break
                    continue
                updates["autoru_status"] = f"error: {e}"[:200]
                errors_in_row += 1
                last_error = str(e)[:150]
            else:
                errors_in_row = 0

            updates["autoru_checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _batch_write(worksheet, row_num, col, updates)
            # в справочник по VIN - только настоящий VIN, не госномер
            if updates.get("autoru_status") in vin_cache.AUTORU_FINAL and len(vin) == 17:
                cache.update(vin, updates)
            processed += 1
            if errors_in_row >= config.AUTORU_MAX_ERRORS_IN_ROW:
                automation.alert(f"Авто.ру: {errors_in_row} ошибок подряд (последняя: {last_error}). Шаг "
                                 f"остановлен, оценено {ok_count}, остальные - в следующий прогон.")
                stopped = True
                break
            time.sleep(config.DELAY_BETWEEN_AUTORU_REQUESTS + random.uniform(0, 2))

        browser.close()
    cache.flush()

    print(f"\nГотово. Обработано: {processed}, успешно: {ok_count}.")
    return stopped


def _wait_captcha(page):
    """Авто.ру показал капчу: ждём до config.AUTORU_CAPTCHA_WAIT_MIN минут,
    что её решат в открытом окне браузера. -> True, если капча ушла."""
    print(f"  Авто.ру просит капчу - решите её в окне браузера (жду до {config.AUTORU_CAPTCHA_WAIT_MIN} мин)...")
    deadline = time.time() + config.AUTORU_CAPTCHA_WAIT_MIN * 60
    while time.time() < deadline:
        time.sleep(5)
        try:
            if "showcaptcha" not in page.url:
                print("  Капча решена, продолжаю.")
                return True
        except Exception:
            return False
    return False


def _new_context(p):
    browser = p.chromium.launch(headless=config.AUTORU_HEADLESS)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        ),
        locale="ru-RU",
        viewport={"width": 1440, "height": 900},
    )
    return browser, context.new_page()


SPECS_MAX_EMPTY_IN_ROW = 8  # столько пустых оценок подряд - Авто.ру перестал отвечать, стоп


def run_specs(limit=None, interactive=True):
    """Дозаполнение характеристик у уже оценённых лотов (см. докстринг модуля). interactive=False - из
    утреннего шага: без ожидания Enter (без VPN кнопки согласия на Авто.ру нет)."""
    limit = limit or config.AUTORU_MAX_PER_RUN
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    spreadsheet = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    header = _ensure_columns(worksheet, values[0])
    col = {name: idx for idx, name in enumerate(header)}

    # ключ машины (VIN, без него - госномер) -> строки листа с этой машиной
    groups, order = {}, []
    for i, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(header) - len(row))
        if row[col["autoru_status"]].strip() not in ("ok", "ambiguous"):
            continue
        # характеристики есть - пропускаем; кузов (с 24.10.2026) дозаполняется и у оценок с характеристиками
        if (row[col["autoru_power"]].strip() or row[col["autoru_modification"]].strip()) and row[col["autoru_body_type"]].strip():
            continue
        if "lot_kind" in col and row[col["lot_kind"]].strip() == lot_metrics.LOT_MULTILOT:
            continue
        key = row[col["vin"]].strip().upper()
        if len(key) != 17:
            key = _lot_plate(row, col)
        if not key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((i, row))
    todo = order[:limit]
    print(f"Без характеристик: {sum(len(g) for g in groups.values())} лотов, {len(order)} машин. "
          f"Сейчас: {len(todo)} машин (лимит {limit}).")
    if not todo:
        return

    cache = vin_cache.VinCache(spreadsheet)
    done = errors_in_row = empty_in_row = 0
    last_error = ""
    with sync_playwright() as p:
        browser, page = _new_context(p)
        page.goto(autoru_valuation.LANDING_URL, wait_until="domcontentloaded")
        if interactive:
            input("Нажмите кнопку согласия в окне Авто.ру, затем Enter здесь: ")
        for key in todo:
            rows = groups[key]
            row = rows[0][1]
            mileage = (lot_metrics.plausible_mileage(_clean_mileage(row[col["mileage_km"]]))
                       or _clean_mileage(row[col["estimated_mileage"]]) or PROBE_MILEAGE_KM)
            try:
                result = autoru_valuation.evaluate_by_vin(page, key, mileage)
            except Exception as e:
                print(f"[{key}] ошибка: {str(e)[:150]}")
                if "showcaptcha" in page.url and not _wait_captcha(page):
                    print("Капчу не решили - стоп. Повторный запуск продолжит с этого места.")
                    break
                errors_in_row += 1
                last_error = str(e)[:150]
                if errors_in_row >= config.AUTORU_MAX_ERRORS_IN_ROW:
                    print(f"{errors_in_row} ошибок подряд (последняя: {last_error}) - стоп.")
                    break
                continue
            errors_in_row = 0
            specs = {k: v for k, v in _spec_updates(result).items() if v is not None}
            print(f"[{key}] {result.get('mark')} {result.get('model')}: {specs.get('autoru_modification') or specs or 'характеристик нет'}"
                  f"{' (лотов: ' + str(len(rows)) + ')' if len(rows) > 1 else ''}")
            if specs:
                for row_num, _ in rows:
                    _batch_write(worksheet, row_num, col, specs)
                if len(key) == 17:
                    cache.update(key, specs)
                done += 1
                empty_in_row = 0
                if done % 25 == 0:
                    cache.flush()  # прервут Ctrl+C - записанное в кэш не пропадёт
            elif not result.get("mark"):
                # Пустая оценка (ни марки, ни модели) подряд у многих машин - Авто.ру перестал
                # отвечать (14.10.2026: после ~50 машин так шло 40+ подряд). В таблицу ничего не
                # пишется, машины остаются в очереди - останавливаемся, повторный запуск продолжит.
                empty_in_row += 1
                if empty_in_row >= SPECS_MAX_EMPTY_IN_ROW:
                    print(f"{empty_in_row} пустых оценок подряд - Авто.ру, похоже, ограничил запросы. "
                          f"Стоп; повторите позже, запуск продолжит с этого места.")
                    break
            time.sleep(config.DELAY_BETWEEN_AUTORU_REQUESTS + random.uniform(0, 2))
        browser.close()
    cache.flush()
    print(f"\nГотово: характеристики записаны для {done} машин из {len(todo)}. "
          f"Осталось без характеристик: {len(order) - done} машин.")


if __name__ == "__main__":
    import sys
    if "--specs" in sys.argv:
        rest = sys.argv[sys.argv.index("--specs") + 1:]
        run(specs_only=True, limit=int(rest[0]) if rest and rest[0].isdigit() else None)
    else:
        run()