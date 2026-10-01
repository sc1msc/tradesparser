# -*- coding: utf-8 -*-
r"""
Справочник по VIN (лист "vin_cache") - купленные и посчитанные данные о
МАШИНЕ, которые не должны пропадать вместе с ЛОТОМ.

Зачем. Лот живёт в таблице недолго: строка в "lots" удаляется через
EXPIRED_LOT_DAYS после окончательного дедлайна (вместе с пробегом TRONK,
за который заплатили), а оценка Авто.ру живёт только в
"lots_current_month" и пропадает, как только лот выпал из 30-дневного
окна. Машина же возвращается: торги не состоялись - её выставляют снова
(новым лотом, дешевле), плюс одни и те же торги публикуются параллельно
на нескольких площадках. Без справочника каждое такое появление - новый
платный запрос TRONK и новая оценка в браузере.

Что хранится (строка на VIN):
  - пробег TRONK: mileage_probeg_status/km/date/source/checked_at -
    действует бессрочно (пересчёт показания на сегодня делает
    fill_missing_mileage.py при копировании);
  - оценка Авто.ру: autoru_* и estimated_mileage - действует
    config.AUTORU_ESTIMATE_TTL_DAYS дней (рынок меняется), потом лот
    оценивается заново.

Кто пишет и читает:
  - fill_missing_mileage.py (шаг 2): перед платным запросом ищет VIN здесь;
    после запроса - пишет сюда. Купленное раньше, но ещё не попавшее в
    справочник (строки "lots" до появления справочника), подбирает сам
    (absorb_mileage);
  - build_lots_current_month.py (шаг 4): подставляет в срез свежие оценки
    Авто.ру отсюда, а оценки, которые есть только в старой версии среза,
    сначала сохраняет сюда (absorb_autoru) - до пересборки;
  - evaluate_autoru_browser.py (шаг 5): после оценки пишет сюда.

Запись - пачкой (flush): квота Google - около 60 запросов записи в минуту,
а запись в справочник по одной строке удвоила бы число запросов шагов 2 и 5.

Разовый перенос уже купленного (при первом запуске):
  python vin_cache.py --backfill   (сначала печатает, что перенесёт)
"""
import datetime
import sys
import time

import gspread

import sheets_writer

SHEET_NAME = "vin_cache"

MILEAGE_FIELDS = [
    "mileage_probeg_status", "mileage_probeg_km", "mileage_probeg_date",
    "mileage_probeg_source", "mileage_probeg_checked_at",
]
AUTORU_FIELDS = [
    "estimated_mileage",
    "autoru_price_low", "autoru_price_high",
    "autoru_tradein_low", "autoru_tradein_high",
    "autoru_uncertainty_percent", "autoru_mark", "autoru_model",
    "autoru_year", "autoru_owners_count", "autoru_accuracy_note",
    "autoru_status", "autoru_checked_at",
]
HEADER = ["vin"] + MILEAGE_FIELDS + AUTORU_FIELDS + ["updated_at"]

# Результат TRONK, который повторять не нужно (см. fill_missing_mileage.SKIP_STATUSES).
MILEAGE_FINAL = {"ok", "no_data", "suspicious"}
# Оценка Авто.ру, которую можно переиспользовать (ошибки и no_mileage - нет).
AUTORU_FINAL = {"ok", "ambiguous"}

FLUSH_EVERY = 25


def norm_vin(value):
    return (value or "").strip().upper()


def _parse_dt(value):
    try:
        return datetime.datetime.fromisoformat(str(value).strip()[:19])
    except ValueError:
        return None


def _retry_quota(call, attempts=4):
    """Запрос к Google с повтором при 429 - квота на запись (~60 запросов в
    минуту на пользователя): ждём минуту и повторяем."""
    for attempt in range(attempts):
        try:
            return call()
        except gspread.exceptions.APIError as e:
            if "429" not in str(e) or attempt == attempts - 1:
                raise
            print("  Google: лимит запросов в минуту, жду 60 с и повторяю...")
            time.sleep(60)


class VinCache:
    def __init__(self, spreadsheet):
        try:
            self.ws = spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            self.ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=len(HEADER))
            self.ws.update(range_name="A1", values=[HEADER])
        values = self.ws.get_all_values()
        self.header = values[0] if values and values[0] else []
        missing = [c for c in HEADER if c not in self.header]
        if missing:  # новые поля справочника - дописываем в шапку
            self.header = self.header + missing
            if len(self.header) > self.ws.col_count:
                self.ws.add_cols(len(self.header) - self.ws.col_count)
            self.ws.update(range_name="A1", values=[self.header])
        self.rows = {}      # vin -> {поле: значение}
        self.row_num = {}   # vin -> номер строки в листе
        for i, row in enumerate(values[1:], start=2):
            rec = dict(zip(self.header, row + [""] * (len(self.header) - len(row))))
            vin = norm_vin(rec.get("vin"))
            if vin:
                self.rows[vin] = rec
                self.row_num[vin] = i
        self.next_row = len(values) + 1 if values else 2
        self._dirty = set()

    # ---------- чтение ----------

    def get(self, vin):
        return self.rows.get(norm_vin(vin))

    def mileage(self, vin):
        """Строка справочника, если пробег по этому VIN уже запрошен."""
        rec = self.get(vin)
        if rec and (rec.get("mileage_probeg_status") or "").strip() in MILEAGE_FINAL:
            return rec
        return None

    def autoru(self, vin, ttl_days, now=None):
        """Поля оценки Авто.ру, если она есть и моложе ttl_days, иначе None."""
        rec = self.get(vin)
        if not rec or (rec.get("autoru_status") or "").strip() not in AUTORU_FINAL:
            return None
        checked = _parse_dt(rec.get("autoru_checked_at"))
        if checked is None or (now or datetime.datetime.now()) - checked > datetime.timedelta(days=ttl_days):
            return None
        return {f: rec.get(f, "") for f in AUTORU_FIELDS}

    # ---------- запись ----------

    def update(self, vin, fields, autoflush=True):
        """Обновляет поля VIN в памяти; на лист - при flush(). Пустые
        значения не затирают уже известные. autoflush - сбрасывать на лист
        каждые FLUSH_EVERY машин (для шагов, где запись идёт по одному лоту);
        массовый перенос (absorb_*) пишет одним flush() в конце."""
        vin = norm_vin(vin)
        if not vin:
            return
        rec = self.rows.setdefault(vin, {"vin": vin})
        changed = False
        for k, v in fields.items():
            if k not in HEADER or v is None or str(v).strip() == "":
                continue
            if str(rec.get(k, "")) != str(v):
                rec[k] = v
                changed = True
        if changed:
            rec["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            self._dirty.add(vin)
            if autoflush and len(self._dirty) >= FLUSH_EVERY:
                self.flush()

    def flush(self):
        """Пишет изменённые строки: одним batch_update на всё, новые строки -
        в конец листа (лист расширяется при необходимости)."""
        if not self._dirty:
            return 0
        data = []
        for vin in sorted(self._dirty):
            if vin not in self.row_num:
                self.row_num[vin] = self.next_row
                self.next_row += 1
            row = [self.rows[vin].get(name, "") for name in self.header]
            sheets_writer.numify_rows(self.header, [row])
            last = gspread.utils.rowcol_to_a1(self.row_num[vin], len(self.header))
            data.append({"range": f"A{self.row_num[vin]}:{last}", "values": [row]})
        need_rows = max(self.row_num.values())
        if need_rows > self.ws.row_count:
            _retry_quota(lambda: self.ws.add_rows(max(sheets_writer.ROWS_GROW_STEP, need_rows - self.ws.row_count)))
        _retry_quota(lambda: self.ws.batch_update(data))
        n = len(self._dirty)
        self._dirty.clear()
        return n

    # ---------- подбор уже купленного ----------

    def absorb_mileage(self, rows):
        """Строки "lots" с уже полученным ответом TRONK, которого нет в
        справочнике, - в справочник (без запросов к TRONK)."""
        n = 0
        for r in rows:
            vin = norm_vin(r.get("vin"))
            status = (r.get("mileage_probeg_status") or "").strip()
            if vin and status in MILEAGE_FINAL and not self.mileage(vin):
                self.update(vin, {f: r.get(f) for f in MILEAGE_FIELDS}, autoflush=False)
                n += 1
        return n

    def absorb_autoru(self, rows):
        """Строки среза с готовой оценкой Авто.ру - в справочник, если там
        её нет или она старше."""
        n = 0
        for r in rows:
            vin = norm_vin(r.get("vin"))
            status = (r.get("autoru_status") or "").strip()
            if not vin or status not in AUTORU_FINAL:
                continue
            have = self.get(vin) or {}
            new_dt = _parse_dt(r.get("autoru_checked_at"))
            old_dt = _parse_dt(have.get("autoru_checked_at")) if (have.get("autoru_status") or "") in AUTORU_FINAL else None
            if old_dt is None or (new_dt is not None and new_dt > old_dt):
                self.update(vin, {f: r.get(f) for f in AUTORU_FIELDS}, autoflush=False)
                n += 1
        return n


def _rows(ws):
    values = ws.get_all_values()
    if not values:
        return []
    h = values[0]
    return [dict(zip(h, r + [""] * (len(h) - len(r)))) for r in values[1:]]


def backfill():
    """Разовый перенос: пробег TRONK из "lots" и оценки Авто.ру из
    "lots_current_month" в справочник."""
    from google.oauth2.service_account import Credentials
    import config
    creds = Credentials.from_service_account_file(
        config.SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)
    lots = _rows(sh.worksheet("lots"))
    cm = _rows(sh.worksheet("lots_current_month"))
    mil = sum(1 for r in lots if norm_vin(r.get("vin")) and (r.get("mileage_probeg_status") or "").strip() in MILEAGE_FINAL)
    aut = sum(1 for r in cm if norm_vin(r.get("vin")) and (r.get("autoru_status") or "").strip() in AUTORU_FINAL)
    print(f"Найдено: пробег TRONK у {mil} строк lots, оценка Авто.ру у {aut} строк lots_current_month.")
    if input("Перенести в лист vin_cache? (yes / нет): ").strip().lower() not in ("yes", "y", "да"):
        print("Отменено.")
        return
    cache = VinCache(sh)
    a = cache.absorb_mileage(lots)
    b = cache.absorb_autoru(cm)
    cache.flush()
    print(f"Готово: пробег {a} VIN, оценки Авто.ру {b} VIN. Всего в справочнике: {len(cache.rows)}.")


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        backfill()
    else:
        print(__doc__)
