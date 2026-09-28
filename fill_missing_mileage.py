# -*- coding: utf-8 -*-
"""
Доливка пробега для лотов, у которых он не указан на странице лота -
через ПЛАТНЫЙ, но дешёвый метод TRONK: probeg (~1.10 руб/запрос) или
probeg2 (~2.10 руб/запрос, история из нескольких источников - точнее),
выбирается в config.MILEAGE_METHOD (см. tronk_mileage.py). В отличие от
evaluate_tronk.py (полная оценка цены - там своя, более дорогая логика и
свои платные лимиты), здесь цель только одна: заполнить mileage_km,
чтобы им могли пользоваться все остальные скрипты (оценка Авто.ру/Авито
и т.д.), которым иначе приходится гадать пробег по формуле
(текущий_год - year) * config.ANNUAL_MILEAGE_KM.

В mileage_km пишется НЕ сырое показание TRONK, а пересчитанное на
сегодня: показание + ANNUAL_MILEAGE_KM * (лет с даты замера). Сырое
значение - в mileage_probeg_km, дата замера - в mileage_probeg_date.
Пробег с карточки лота (JSON) никогда не перезаписывается - такие лоты
сюда просто не попадают.

Запускается СТРОГО отдельно и вручную: python fill_missing_mileage.py
Всегда сначала печатает, сколько лотов будет обработано (= сколько
рублей будет потрачено) и просит подтверждение.

Логика отбора лотов:
  - берём только те, у кого есть vin
  - лот должен быть "актуален" - до applications_end осталось не больше
    build_lots_current_month.WINDOW_DAYS дней (и дедлайн ещё не прошёл).
    Проверяем ПРЯМО по колонке applications_end листа "lots" - именно
    это поле, не читая сам лист lots_current_month, поэтому скрипт
    работает независимо от того, собирали ли его вообще и когда в
    последний раз (никакой зависимости от порядка запуска: можно
    запускать сразу после main.py). Константы окна (сколько дней
    считается "актуальным") и формат даты берём напрямую из
    build_lots_current_month.py - чтобы не дублировать число и не
    разъехаться с ним, если там его когда-нибудь поменяют.
    Лист "lots" в полтора раза больше lots_current_month за счёт лотов,
    чьи торги ещё нескоро или уже прошли - платить за их пробег нет
    смысла: либо ещё рано (доберёмся, когда лот станет актуален), либо
    уже поздно (лот больше никто не оценивает).
  - пропускаем те, у кого mileage_km уже заполнен (неважно, откуда)
  - пропускаем те, у кого mileage_probeg_status уже "ok" или "no_data"
    (уже проверяли этот VIN - повторный платный запрос ничего не даст)
  - лоты со статусом "error: ..." или пустым статусом пробуем снова
  - обрезаем список до config.MILEAGE_MAX_PER_RUN - защита от случайного
    слива бюджета за один прогон
"""
import datetime
import time

import build_lots_current_month as blcm
import config
import sheets_writer
import tronk_mileage


SKIP_STATUSES = {"ok", "no_data"}


def _is_current(applications_end, now):
    """Тот же критерий "актуальности", что и в build_lots_current_month.py
    (окно blcm.WINDOW_DAYS дней, формат даты blcm.DATE_FORMAT) - но
    проверяется прямо по значению из листа lots, без обращения к самому
    lots_current_month."""
    try:
        end_dt = datetime.datetime.strptime(applications_end, blcm.DATE_FORMAT)
    except (ValueError, TypeError):
        return False
    deadline = now + datetime.timedelta(days=blcm.WINDOW_DAYS)
    return now <= end_dt <= deadline


def select_candidates(rows, now=None):
    now = now or datetime.datetime.now()
    candidates = []
    for r in rows:
        vin = (r.get("vin") or "").strip()
        if not vin:
            continue
        if not _is_current(r.get("applications_end"), now):
            continue  # торги ещё нескоро или уже прошли - платить рано/поздно
        if (r.get("mileage_km") or "").strip():
            continue  # пробег уже есть - неважно, откуда взялся
        status = (r.get("mileage_probeg_status") or "").strip()
        if status in SKIP_STATUSES:
            continue
        candidates.append(r)
    return candidates


def run():
    if config.TRONK_API_KEY.startswith("ВСТАВЬТЕ"):
        print("Сначала впишите настоящий TRONK_API_KEY в config.py")
        return

    method = config.MILEAGE_METHOD
    if method not in tronk_mileage.PRICE_PER_REQUEST_RUB:
        print(f"config.MILEAGE_METHOD={method!r} не поддерживается "
              f"(ожидается 'probeg' или 'probeg2')")
        return
    price_per_request = tronk_mileage.PRICE_PER_REQUEST_RUB[method]

    print("Подключаюсь к Google Таблице...")
    worksheet = sheets_writer.connect(
        config.SERVICE_ACCOUNT_FILE, config.SPREADSHEET_ID, config.WORKSHEET_NAME
    )
    rows = sheets_writer.read_rows(worksheet)
    print(f"Всего строк в таблице: {len(rows)}")

    candidates = select_candidates(rows)
    print(f"Лотов-кандидатов (есть VIN, лот актуален, пробег не указан, ещё не проверяли): {len(candidates)}")

    if not candidates:
        print("Нечего доливать, выхожу.")
        return

    to_process = candidates[: config.MILEAGE_MAX_PER_RUN]
    skipped_by_limit = len(candidates) - len(to_process)
    cost = len(to_process) * price_per_request

    print(f"\nМетод (config.MILEAGE_METHOD): {method}")
    print(f"Лимит за один запуск (config.MILEAGE_MAX_PER_RUN): {config.MILEAGE_MAX_PER_RUN}")
    print(f"Будет отправлено платных запросов СЕЙЧАС: {len(to_process)} "
          f"(~{cost:.2f} руб. по цене {method}, {price_per_request:.2f} руб/запрос)")
    if skipped_by_limit > 0:
        print(f"Ещё {skipped_by_limit} лотов ждут следующего запуска (не будут обработаны сейчас).")

    answer = input(
        f"\nПодтвердите отправку {len(to_process)} ПЛАТНЫХ запросов к TRONK (yes / нет): "
    ).strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено, ни одного запроса не отправлено.")
        return

    processed = 0
    filled = 0
    for r in to_process:
        row_num = r["_row_num"]
        vin = r["vin"].strip().upper()
        lot_id = r.get("lot_id")
        print(f"\n[{lot_id}] VIN={vin} ...")

        try:
            raw = tronk_mileage.get_mileage_history(config.TRONK_API_KEY, vin, method)
            fields = tronk_mileage.extract_latest_mileage(raw)
        except Exception as e:
            print(f"  Ошибка запроса: {e}")
            fields = {"status": f"error: {e}", "mileage_km": None, "mileage_date": None,
                       "mileage_date_obj": None, "mileage_source": None}

        updates = {
            "mileage_probeg_status": fields["status"],
            "mileage_probeg_date": fields["mileage_date"],
            "mileage_probeg_source": fields["mileage_source"],
            "mileage_probeg_checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        estimated = None
        if fields["mileage_km"]:
            # В mileage_km кладём не сырое показание, а пересчитанное на
            # сегодня (+ANNUAL_MILEAGE_KM за каждый год с даты замера).
            # Сырое - отдельно, в mileage_probeg_km, чтобы было видно, из
            # чего посчитано.
            estimated = tronk_mileage.extrapolate_mileage(
                fields["mileage_km"], fields["mileage_date_obj"], config.ANNUAL_MILEAGE_KM
            )
            updates["mileage_probeg_km"] = fields["mileage_km"]
            updates["mileage_km"] = estimated
            filled += 1
            if fields["mileage_date_obj"] is None:
                print(f"  ВНИМАНИЕ: не разобрал дату показания ({fields['mileage_date']!r}) - "
                      f"беру пробег как есть, без пересчёта на сегодня")

        sheets_writer.batch_set_cells(worksheet, row_num, updates)

        print(f"  -> {fields['status']} (TRONK: {fields['mileage_km']} на {fields['mileage_date']}, "
              f"на сегодня: {estimated}, источник: {fields['mileage_source']})")

        processed += 1
        time.sleep(config.DELAY_BETWEEN_MILEAGE_REQUESTS)

    print(f"\nГотово. Отправлено запросов: {processed}, заполнено пробегов: {filled} "
          f"(~{processed * price_per_request:.2f} руб. потрачено).")


if __name__ == "__main__":
    run()