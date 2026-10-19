# -*- coding: utf-8 -*-
"""
ДТП по VIN для машин ленты - ПЛАТНЫЙ шаг конвейера (TRONK, метод dtp, ~0.4 руб/запрос).

Зачем. На экране лота мини-аппа блок «ДТП: 2» (раскрывается: даты, места и схемы повреждений;
подробности - в Pro) или «ДТП не найдены» (решения владельца 19.10.2026). Скидка к рынку часто
объясняется прошлыми авариями, а проверка на сайте Госавтоинспекции закрыта капчей.

Какие машины. Лоты «одна машина» с VIN из 17 знаков в листе lots_current_month (то есть вся лента;
мультилоты, права и доли - нет). Один запрос на VIN: результат лежит в справочнике по VIN
(vin_cache.py, поля dtp_*), повторно VIN спрашиваем только через config.DTP_TTL_DAYS дней (за это
время у машины могли появиться новые записи). «Нет данных» (no_data) - тоже результат, повторяем
так же редко. Ошибки (error: ...) повторяются в следующий прогон.

Деньги. Не больше config.DTP_MAX_PER_RUN запросов за прогон и не больше остатка месячного бюджета
TRONK (config.TRONK_MONTHLY_BUDGET_RUB, общий с пробегом; траты - из учёта расходов). Списанное
записывается в учёт (expenses.record_tronk) и при падении посреди цикла. Перед запросами -
подтверждение (в автоматическом режиме проходит само, деньги ограничены лимитами).

Лист lots_current_month шаг не меняет: пишет только справочник vin_cache. В мини-апп ДТП уходят
выгрузкой (export_to_miniapp.py читает справочник по VIN).

Запуск: python fill_dtp.py (шаг 7 run_pipeline.py: после пересборки lots_current_month, перед выгрузкой).
"""
import datetime
import json
import time

import gspread
from google.oauth2.service_account import Credentials

import automation
import config
import expenses
import lot_metrics
import tronk_dtp
import vin_cache

SOURCE_SHEET = "lots_current_month"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# Столько ошибок подряд (не «нет данных», а отказ TRONK: кончились деньги, нет прав, сбой) - стоп.
MAX_ERRORS_IN_ROW = 5


def feed_vins(rows):
    """Уникальные VIN машин среза (лоты «одна машина», VIN из 17 знаков), в порядке листа."""
    out, seen = [], set()
    for r in rows:
        if (r.get("lot_kind") or lot_metrics.LOT_CAR) != lot_metrics.LOT_CAR:
            continue
        vin = vin_cache.norm_vin(r.get("vin"))
        if len(vin) == 17 and vin not in seen:
            seen.add(vin)
            out.append(vin)
    return out


def cache_fields(result, checked_at):
    """Результат tronk_dtp.parse -> поля справочника (vin_cache.DTP_FIELDS)."""
    return {
        "dtp_status": result["status"],
        "dtp_count": len(result["accidents"]) if result["status"] == "ok" else None,
        # компактный JSON: список ДТП (tronk_dtp.parse), пустой список - «ДТП не найдены»
        "dtp_accidents": json.dumps(result["accidents"], ensure_ascii=False, separators=(",", ":"))
        if result["status"] == "ok" else None,
        "dtp_as_of": result["as_of"],
        "dtp_checked_at": checked_at,
    }


def _flush_cache(cache):
    try:
        cache.flush()
    except Exception as e:
        automation.alert(f"TRONK ДТП: справочник по VIN (vin_cache) не записался ({e}). Купленное в этом "
                         f"прогоне в следующий раз оплатится снова.")


def run():
    if config.TRONK_API_KEY.startswith("ВСТАВЬТЕ"):
        print("Сначала впишите настоящий TRONK_API_KEY в local_secrets.py")
        return
    print("Подключаюсь к Google Таблице...")
    # не sheets_writer.connect: он переписывает шапку листа под схему lots
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    ws = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID).worksheet(SOURCE_SHEET)
    values = ws.get_all_values()
    header = values[0] if values else []
    rows = [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]
    cache = vin_cache.VinCache(ws.spreadsheet)
    vins = feed_vins(rows)
    todo = [v for v in vins if not cache.dtp(v, config.DTP_TTL_DAYS)]
    print(f"Машин в срезе с VIN: {len(vins)}, ДТП уже известны: {len(vins) - len(todo)}, к запросу: {len(todo)}")
    if not todo:
        return

    to_process = todo[: config.DTP_MAX_PER_RUN]
    price = expenses.tronk_price(tronk_dtp.METHOD, tronk_dtp.PRICE_PER_REQUEST_RUB)
    budget = getattr(config, "TRONK_MONTHLY_BUDGET_RUB", None)
    if budget:
        left = budget - expenses.month_spent("TRONK")
        allowed = max(0, int(left // price))
        if allowed < len(to_process):
            automation.alert(f"TRONK ДТП: месячный бюджет {budget} руб. - осталось {max(left, 0):.0f} руб., "
                             f"оплачиваю {allowed} из {len(to_process)} VIN. Остальные - в следующих прогонах "
                             f"нового месяца (или поднимите TRONK_MONTHLY_BUDGET_RUB в config.py).")
            to_process = to_process[:allowed]
            if not to_process:
                return
    print(f"Будет отправлено платных запросов СЕЙЧАС: {len(to_process)} (~{len(to_process) * price:.2f} руб. "
          f"по {price:.2f} руб/запрос)")
    if len(todo) > len(to_process):
        print(f"Ещё {len(todo) - len(to_process)} VIN - в следующие прогоны (лимит или бюджет).")
    if not automation.confirm(f"\nПодтвердите {len(to_process)} ПЛАТНЫХ запросов ДТП к TRONK (yes / нет): "):
        print("Отменено, ни одного запроса не отправлено.")
        return

    balance_before = expenses.tronk_balance()
    processed, found, clean, no_data, errors, in_row, last_error = 0, 0, 0, 0, 0, 0, ""
    try:
        for i, vin in enumerate(to_process, start=1):
            try:
                result = tronk_dtp.parse(tronk_dtp.get_dtp(config.TRONK_API_KEY, vin))
            except Exception as e:
                result = {"status": f"error: {str(e)[:150]}", "accidents": [], "as_of": None}
            processed += 1  # запрос ушёл - деньги могли списаться, даже если ответ не разобрался
            status = result["status"]
            if status.startswith("error"):
                errors += 1
                in_row += 1
                last_error = status
                print(f"  [{i}/{len(to_process)}] {vin}: {status}")
                if in_row >= MAX_ERRORS_IN_ROW:
                    automation.alert(f"TRONK ДТП: {in_row} ошибок подряд, шаг остановлен (последняя: "
                                     f"{last_error}). Проверьте баланс и доступ к методу dtp.")
                    break
                continue
            in_row = 0
            if status == "no_data":
                no_data += 1
            elif result["accidents"]:
                found += 1
            else:
                clean += 1
            cache.update(vin, cache_fields(result, datetime.datetime.now().isoformat(timespec="seconds")))
            print(f"  [{i}/{len(to_process)}] {vin}: {status}"
                  + (f", ДТП: {len(result['accidents'])}" if status == "ok" else ""))
            time.sleep(config.DELAY_BETWEEN_DTP_REQUESTS)
    finally:
        expenses.record_tronk(tronk_dtp.METHOD, processed, balance_before, expenses.tronk_balance(),
                              price, "fill_dtp")
        _flush_cache(cache)
    print(f"\nГотово. Запросов: {processed}; с ДТП: {found}, ДТП не найдены: {clean}, нет данных: {no_data}, "
          f"ошибок: {errors}.")
    if processed >= 20 and errors * 3 >= processed:
        automation.alert(f"TRONK ДТП: ошибок {errors} из {processed} запросов (последняя: {last_error}).")


if __name__ == "__main__":
    run()
