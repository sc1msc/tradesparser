# -*- coding: utf-8 -*-
"""
Массовая оценка лотов из Google Таблицы через ПЛАТНЫЙ API TRONK.

Запускается СТРОГО отдельно и вручную: python evaluate_tronk.py
Ничего не вызывает автоматически из main.py и не запускается по расписанию
без явного участия человека - каждый запуск сначала печатает, сколько лотов
будет обработано (= сколько платных запросов будет отправлено) и просит
подтверждение.

Логика отбора лотов:
  - берём только те, у кого есть vin
  - пропускаем те, у кого tronk_status уже "ok" (оценка уже получена)
  - пропускаем те, у кого tronk_status == "no_data" (TRONK явно сказал, что
    по этому VIN данных нет - повторный платный запрос ничего не изменит)
  - лоты со статусом "error: ..." или пустым статусом пробуем снова
    (мало ли, была временная недоступность источника)
  - обрезаем список до config.TRONK_MAX_PER_RUN - это и есть защита от
    случайного слива бюджета за один прогон
"""
import time
import datetime

import config
import expenses
import sheets_writer
import tronk_valuation


SKIP_STATUSES = {"ok", "no_data"}


def select_candidates(rows):
    candidates = []
    for r in rows:
        vin = (r.get("vin") or "").strip()
        if not vin:
            continue
        status = (r.get("tronk_status") or "").strip()
        if status in SKIP_STATUSES:
            continue
        candidates.append(r)
    return candidates


def run():
    if config.TRONK_API_KEY.startswith("ВСТАВЬТЕ"):
        print("Сначала впишите настоящий TRONK_API_KEY в config.py")
        return

    print("Подключаюсь к Google Таблице...")
    worksheet = sheets_writer.connect(
        config.SERVICE_ACCOUNT_FILE, config.SPREADSHEET_ID, config.WORKSHEET_NAME
    )
    rows = sheets_writer.read_rows(worksheet)
    print(f"Всего строк в таблице: {len(rows)}")

    candidates = select_candidates(rows)
    print(f"Лотов-кандидатов на оценку (есть VIN, ещё не оценены): {len(candidates)}")

    if not candidates:
        print("Нечего оценивать, выхожу.")
        return

    to_process = candidates[: config.TRONK_MAX_PER_RUN]
    skipped_by_limit = len(candidates) - len(to_process)

    print(f"\nЛимит за один запуск (config.TRONK_MAX_PER_RUN): {config.TRONK_MAX_PER_RUN}")
    print(f"Будет отправлено платных запросов СЕЙЧАС: {len(to_process)}")
    if skipped_by_limit > 0:
        print(f"Ещё {skipped_by_limit} лотов ждут следующего запуска (не будут обработаны сейчас).")

    print("\nЛоты, которые будут отправлены на оценку:")
    for r in to_process:
        print(f"  - lot_id={r.get('lot_id')} vin={r.get('vin')} | {r.get('title', '')[:60]}")

    answer = input(
        f"\nПодтвердите отправку {len(to_process)} ПЛАТНЫХ запросов к TRONK (yes / нет): "
    ).strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, ни одного запроса не отправлено.")
        return

    processed = 0
    ok_count = 0
    # баланс до и после - чтобы учесть реальное списание (expenses.py)
    balance_before = expenses.tronk_balance()
    try:
        for r in to_process:
            row_num = r["_row_num"]
            vin = r["vin"].strip().upper()
            lot_id = r.get("lot_id")
            print(f"\n[{lot_id}] VIN={vin} ...")

            try:
                raw = tronk_valuation.get_avg_price(
                    config.TRONK_API_KEY, vin, config.TRONK_REGION_ID
                )
                fields = tronk_valuation.extract_valuation(raw)
            except Exception as e:
                print(f"  Ошибка запроса: {e}")
                fields = {"status": f"error: {e}", "price_avg": None, "price_min": None,
                           "price_max": None, "mileage_avg": None}
            processed += 1  # запрос ушёл - деньги списаны, даже если запись ниже упадёт

            # Одним batch_update() на лот вместо 9 отдельных запросов - иначе
            # даже при небольшом TRONK_MAX_PER_RUN легко упереться в лимит
            # Google Sheets (60 write-запросов/мин на пользователя).
            sheets_writer.batch_set_cells(worksheet, row_num, {
                "tronk_price_avg": fields.get("price_avg"),
                "tronk_price_min": fields.get("price_min"),
                "tronk_price_max": fields.get("price_max"),
                "tronk_mileage_avg": fields.get("mileage_avg"),
                "tronk_marka": fields.get("marka"),
                "tronk_model": fields.get("model"),
                "tronk_year": fields.get("year"),
                "tronk_status": fields.get("status"),
                "tronk_checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            })

            print(f"  -> {fields['status']} "
                  f"(avg={fields['price_avg']}, min={fields['price_min']}, max={fields['price_max']})")

            if fields["status"] == "ok":
                ok_count += 1

            time.sleep(config.DELAY_BETWEEN_TRONK_REQUESTS)
    finally:
        expenses.record_tronk("avgpricebyvin", processed, balance_before, expenses.tronk_balance(),
                              expenses.tronk_price("avgpricebyvin"), "evaluate_tronk")

    print(f"\nГотово. Отправлено запросов: {processed}, успешных оценок: {ok_count}.")


if __name__ == "__main__":
    run()
