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
    У публичного предложения applications_end в "lots" - окончательный
    дедлайн (конец последнего периода), поэтому для него берётся конец
    ТЕКУЩЕГО периода из bidding_periods (bidding_schedule.py) - тот же,
    по которому лот попадёт в lots_current_month. Иначе лот с длинным
    графиком попадал бы в срез и оценку Авто.ру, но без пробега.
    Лист "lots" в полтора раза больше lots_current_month за счёт лотов,
    чьи торги ещё нескоро или уже прошли - платить за их пробег нет
    смысла: либо ещё рано (доберёмся, когда лот станет актуален), либо
    уже поздно (лот больше никто не оценивает).
  - пропускаем лоты, у которых торги уже завершены/отменены (status)
  - пропускаем те, у кого mileage_km уже заполнен (неважно, откуда)
  - пропускаем те, у кого mileage_probeg_status уже "ok", "no_data" или
    "suspicious" (уже проверяли - повторный платный запрос ничего не даст)
  - лоты со статусом "error: ..." или пустым статусом пробуем снова
  - обрезаем список до config.MILEAGE_MAX_PER_RUN - защита от случайного
    слива бюджета за один прогон

Не платим дважды за один VIN. Одна и та же машина бывает в нескольких
лотах (торги на ЭТП + "вне ЭТП", повторные торги - по ревью 29.09 73 VIN
встречаются в 151 лоте), а отметка о проверке раньше стояла только в
строке. Теперь:
  - если этот VIN уже проверен в ДРУГОЙ строке - результат копируется
    оттуда бесплатно (пробег пересчитывается на сегодня от той же даты
    замера);
  - если одинаковый VIN у нескольких кандидатов - запрос один, результат
    пишется во все их строки. Лимит MILEAGE_MAX_PER_RUN - на число
    ПЛАТНЫХ запросов (уникальных VIN).

Неправдоподобный пробег (больше lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM -
лот 7147717, Renault Logan 2007: 2 224 050 км) в mileage_km не пишется:
статус "suspicious", сырое показание - в mileage_probeg_km для проверки
глазами. Оценка Авто.ру такого лота пойдёт по году выпуска.
"""
import datetime
import time

import bidding_schedule
import build_lots_current_month as blcm
import config
import lot_metrics
import sheets_writer
import tronk_mileage


SKIP_STATUSES = {"ok", "no_data", "suspicious"}


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
        _, deadline = bidding_schedule.effective_price_and_deadline(
            r.get("price_current"), r.get("applications_end"), r.get("bidding_periods"), now
        )
        if not _is_current(deadline, now):
            continue  # торги ещё нескоро или уже прошли - платить рано/поздно
        if bidding_schedule.is_closed_status(r.get("status")):
            continue  # торги завершены/отменены - в lots_current_month не попадёт
        if (r.get("mileage_km") or "").strip():
            continue  # пробег уже есть - неважно, откуда взялся
        status = (r.get("mileage_probeg_status") or "").strip()
        if status in SKIP_STATUSES:
            continue
        candidates.append(r)
    return candidates


def _vin(row):
    return (row.get("vin") or "").strip().upper()


def checked_by_vin(rows):
    """VIN -> строка, где этот VIN уже проверен в TRONK (статус из
    SKIP_STATUSES). Из неё копируем результат вместо платного запроса."""
    donors = {}
    for r in rows:
        if _vin(r) and (r.get("mileage_probeg_status") or "").strip() in SKIP_STATUSES:
            donors.setdefault(_vin(r), r)
    return donors


def updates_from_tronk(fields, checked_at):
    """Ответ TRONK (tronk_mileage.extract_latest_mileage) -> поля строки.
    Неправдоподобный пробег - статус "suspicious", mileage_km не пишется."""
    updates = {
        "mileage_probeg_status": fields["status"],
        "mileage_probeg_date": fields["mileage_date"],
        "mileage_probeg_source": fields["mileage_source"],
        "mileage_probeg_checked_at": checked_at,
    }
    if fields["mileage_km"]:
        # Сырое показание - всегда в mileage_probeg_km, чтобы было видно, из
        # чего посчитано (или почему отброшено).
        updates["mileage_probeg_km"] = fields["mileage_km"]
        if lot_metrics.plausible_mileage(fields["mileage_km"]) is None:
            updates["mileage_probeg_status"] = "suspicious"
        else:
            # В mileage_km - не сырое показание, а пересчитанное на сегодня
            # (+ANNUAL_MILEAGE_KM за каждый год с даты замера).
            updates["mileage_km"] = tronk_mileage.extrapolate_mileage(
                fields["mileage_km"], fields["mileage_date_obj"], config.ANNUAL_MILEAGE_KM
            )
    return updates


def updates_from_donor(donor):
    """Результат, уже купленный для этого VIN в другой строке - бесплатно.
    Пробег заново пересчитывается на сегодня от той же даты замера."""
    raw_km = (str(donor.get("mileage_probeg_km") or "")).strip()
    status = (donor.get("mileage_probeg_status") or "").strip()
    if status == "ok" and raw_km and lot_metrics.plausible_mileage(raw_km) is None:
        status = "suspicious"  # донор записан до появления проверки правдоподобия
    fields = {
        "status": status,
        "mileage_km": lot_metrics.plausible_mileage(raw_km) if status == "ok" else None,
        "mileage_date": donor.get("mileage_probeg_date") or None,
        "mileage_date_obj": tronk_mileage.parse_date(donor.get("mileage_probeg_date")),
        "mileage_source": donor.get("mileage_probeg_source") or None,
    }
    updates = updates_from_tronk(fields, donor.get("mileage_probeg_checked_at") or None)
    if raw_km:
        # числом, не строкой: gspread пишет RAW (см. sheets_writer.NUMERIC_COLUMNS)
        try:
            updates["mileage_probeg_km"] = int(round(float(raw_km.replace(",", "."))))
        except ValueError:
            pass
    return updates


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

    # 1) VIN уже проверен в другой строке - копируем бесплатно.
    donors = checked_by_vin(rows)
    reused = [r for r in candidates if _vin(r) in donors]
    for r in reused:
        sheets_writer.batch_set_cells(worksheet, r["_row_num"], updates_from_donor(donors[_vin(r)]))
    if reused:
        print(f"Скопировано без запроса к TRONK (этот VIN уже проверен в другом лоте): {len(reused)}")

    # 2) Остальные - один платный запрос на VIN, результат во все его строки.
    rows_by_vin = {}
    for r in candidates:
        if _vin(r) not in donors:
            rows_by_vin.setdefault(_vin(r), []).append(r)
    if not rows_by_vin:
        print("Платных запросов не нужно, выхожу.")
        return

    vins = list(rows_by_vin)
    to_process = vins[: config.MILEAGE_MAX_PER_RUN]
    skipped_by_limit = len(vins) - len(to_process)
    cost = len(to_process) * price_per_request

    print(f"\nМетод (config.MILEAGE_METHOD): {method}")
    print(f"Лимит за один запуск (config.MILEAGE_MAX_PER_RUN): {config.MILEAGE_MAX_PER_RUN}")
    print(f"Будет отправлено платных запросов СЕЙЧАС: {len(to_process)} (уникальных VIN) "
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
    suspicious = 0
    for vin in to_process:
        vin_rows = rows_by_vin[vin]
        lot_ids = ", ".join(str(r.get("lot_id")) for r in vin_rows)
        print(f"\n[{lot_ids}] VIN={vin} ...")

        try:
            raw = tronk_mileage.get_mileage_history(config.TRONK_API_KEY, vin, method)
            fields = tronk_mileage.extract_latest_mileage(raw)
        except Exception as e:
            print(f"  Ошибка запроса: {e}")
            fields = {"status": f"error: {e}", "mileage_km": None, "mileage_date": None,
                       "mileage_date_obj": None, "mileage_source": None}

        updates = updates_from_tronk(fields, datetime.datetime.now().isoformat(timespec="seconds"))
        estimated = updates.get("mileage_km")
        if estimated is not None:
            filled += 1
            if fields["mileage_date_obj"] is None:
                print(f"  ВНИМАНИЕ: не разобрал дату показания ({fields['mileage_date']!r}) - "
                      f"беру пробег как есть, без пересчёта на сегодня")
        if updates["mileage_probeg_status"] == "suspicious":
            suspicious += 1
            print(f"  ВНИМАНИЕ: пробег {fields['mileage_km']} км неправдоподобен - не записываю, "
                  f"оценка пойдёт по году выпуска")

        for r in vin_rows:
            sheets_writer.batch_set_cells(worksheet, r["_row_num"], updates)

        print(f"  -> {updates['mileage_probeg_status']} (TRONK: {fields['mileage_km']} на {fields['mileage_date']}, "
              f"на сегодня: {estimated}, источник: {fields['mileage_source']})")

        processed += 1
        time.sleep(config.DELAY_BETWEEN_MILEAGE_REQUESTS)

    print(f"\nГотово. Отправлено запросов: {processed}, заполнено пробегов: {filled}, "
          f"отброшено неправдоподобных: {suspicious} (~{processed * price_per_request:.2f} руб. потрачено).")


if __name__ == "__main__":
    run()