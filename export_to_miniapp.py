# -*- coding: utf-8 -*-
r"""
Выгрузка лотов в мини-апп honestlot: последний шаг run_pipeline.py.

Что делает:
  1) читает лист "lots_current_month" (только читает, ничего не пишет);
  2) для каждого лота берёт с его карточки на сайте торгов то, чего в
     таблице нет: ВСЕ фото (в таблице - только первое), описание, форму
     торгов, площадку и stages.end_bid_time;
  3) отправляет всё одним запросом на сервер мини-аппа (POST /api/import).

Что откуда:
  - статус торгов и график публичного предложения (bidding_periods) - из
    ЛИСТА: пайплайн обновляет их каждый день (main.py перечитывает идущие
    публичные предложения, см. DATA_UPDATES.md). Кэш карточек - только
    запасной вариант, если в листе пусто;
  - окончательный дедлайн публичного предложения - bidding_schedule.
    final_deadline(end_bid_time с карточки, график из листа): в листе
    applications_end у публичного предложения - уже дедлайн ТЕКУЩЕГО
    периода, а бэкенду нужен окончательный (текущий период он выбирает
    сам в момент запроса);
  - фото, описание, форма торгов, площадка - из карточки (кэш), в таблице
    их нет.

Карточки кэшируются в локальном файле DETAILS_CACHE_FILE (в git не
хранится): в таблицу эти данные не пишутся, они нужны только мини-аппу.
Первый запуск скачивает карточки всех лотов (сотни запросов с паузой
DELAY_BETWEEN_LOT_REQUESTS - это десятки минут), дальше - только новые
лоты и те, чей кэш старше MINIAPP_DETAILS_REFRESH_DAYS.

Если в local_secrets.py не заданы MINIAPP_API_URL / MINIAPP_IMPORT_TOKEN -
шаг ничего не делает (пайплайн работает как раньше). Если сервер
недоступен - шаг печатает ошибку и НЕ роняет пайплайн: мини-апп просто
покажет вчерашние данные. Убрать шаг из пайплайна - закомментировать
одну строку в STEPS в run_pipeline.py.

Отдельный запуск: python export_to_miniapp.py
  (--dry-run - всё собрать, но не отправлять; сохранит payload в
   miniapp_export_preview.json для проверки)
"""
import datetime
import json
import os
import re
import sys
import time

import gspread
import requests
from google.oauth2.service_account import Credentials

import bidding_schedule
import config
import lot_metrics
import main
from nextjs_json import extract_combined_payload, find_json_value, resolve_text_ref

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SOURCE_SHEET = "lots_current_month"
DETAILS_CACHE_FILE = "miniapp_details_cache.json"
PREVIEW_FILE = "miniapp_export_preview.json"
LOT_ID_RE = re.compile(r"/lot/(\d+)")
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}


def _to_int(value):
    """Числа в листе - текст, десятичный разделитель - запятая ('23,5'),
    разделителя тысяч нет. Пустое/мусор -> None."""
    s = str(value or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def _load_cache():
    if not os.path.exists(DETAILS_CACHE_FILE):
        return {}
    with open(DETAILS_CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_cache(cache):
    tmp = DETAILS_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, DETAILS_CACHE_FILE)


def _title(obj, key):
    value = obj.get(key)
    return value.get("title") if isinstance(value, dict) else value


def fetch_details(url, session):
    """Карточка лота -> то, что нужно мини-аппу и чего нет в таблице."""
    html = main.fetch(url, session)
    payload = extract_combined_payload(html)
    lot, _ = find_json_value(payload, "lot", kind="object")
    if lot is None:
        raise ValueError("на странице не найден JSON лота")
    photos = []
    for pic in lot.get("pictures") or []:
        link = pic.get("link")
        if not link:
            continue
        ext = (pic.get("ext") or link.rsplit(".", 1)[-1]).lower()
        if ext in IMAGE_EXTS:
            photos.append({"full": link, "thumb": pic.get("thumb_link") or link})
    periods = [
        {"begin": p.get("begin"), "end": p.get("end"), "bid_end": p.get("bid_end"), "price": p.get("price")}
        for p in lot.get("bidding_periods") or []
    ]
    stages = lot.get("stages") or {}
    trade_form = lot.get("trade_form") or ""
    return {
        "photos": photos,
        "periods": periods,
        "trade_form": trade_form,
        # trade_form_id 5 на сайте - "публичное предложение"; проверяем и по
        # тексту, и по наличию графика - на случай смены id.
        "is_public_offer": bool(periods) or "публичн" in trade_form.lower() or lot.get("trade_form_id") == 5,
        "status": _title(lot, "status"),
        "platform": _title(lot, "marketplace"),
        # Длинное описание бывает ссылкой "$81" на отдельный чанк (nextjs_json.resolve_text_ref).
        "description": resolve_text_ref(payload, lot.get("information")),
        "applications_end": stages.get("end_bid_time"),
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _needs_refresh(entry):
    if not entry or entry.get("error"):
        return True
    try:
        fetched = datetime.datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, ValueError):
        return True
    return datetime.datetime.now() - fetched > datetime.timedelta(days=config.MINIAPP_DETAILS_REFRESH_DAYS)


def read_sheet():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    ws = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID).worksheet(SOURCE_SHEET)
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]


def _sheet_periods(text):
    """bidding_periods из листа ('[[bid_end, price], ...]') -> список пар."""
    try:
        pairs = json.loads(text) if text else []
    except ValueError:
        return []
    return [p for p in pairs if isinstance(p, list) and len(p) == 2]


def build_lot(row, details):
    lot_id = LOT_ID_RE.search(row.get("url") or "").group(1)
    # Пробег больше lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM - ошибка источника:
    # показываем оценку по году (как и оценивает такой лот Авто.ру).
    mileage = lot_metrics.plausible_mileage(row.get("mileage_km"))
    estimated = lot_metrics.plausible_mileage(row.get("estimated_mileage"))
    d = details or {}
    periods = _sheet_periods(row.get("bidding_periods")) or [
        [p.get("bid_end") or p.get("end"), p.get("price")] for p in d.get("periods") or []
        if p.get("bid_end") or p.get("end")
    ]
    trade_form = d.get("trade_form")
    is_public_offer = bool(periods) or bool(d.get("is_public_offer")) or bidding_schedule.is_public_offer(trade_form)
    if periods:
        # окончательный дедлайн: end_bid_time с карточки (не меняется) против
        # конца графика; без кэша - applications_end листа (текущий период)
        applications_end = bidding_schedule.final_deadline(
            d.get("applications_end") or row.get("applications_end"), json.dumps(periods))
    else:
        applications_end = row.get("applications_end") or d.get("applications_end")
    return {
        "lot_id": lot_id,
        "url": row.get("url"),
        "title": row.get("title"),
        # autoru_mark/autoru_model - чистые названия ("KIA", "SOLARIS"); brand/name
        # (Autodoc или разбор title) бывают вида "Audi A6 Av. 2,0 TDI" или кусок
        # фразы - только как запасной вариант. Дочистка - в бэкенде (lots.py).
        "brand": row.get("autoru_mark") or row.get("brand"),
        "model": row.get("autoru_model") or row.get("name"),
        "year": _to_int(row.get("year")) or _to_int(row.get("autoru_year")),
        "vin": row.get("vin") or None,
        "plate": row.get("plate") or None,
        # Настоящий пробег (лот / TRONK) важнее оценки по году выпуска;
        # оценку показываем со значком "~".
        "mileage_km": mileage if mileage is not None else estimated,
        "mileage_estimated": mileage is None and estimated is not None,
        "price_start": _to_int(row.get("price_start")),
        "price_current": _to_int(row.get("price_current")),
        "region": row.get("region") or None,
        "trade_form": trade_form,
        "is_public_offer": is_public_offer,
        "status": row.get("status") or d.get("status"),
        "platform": d.get("platform"),
        "applications_end": applications_end,
        "bidding_start": row.get("bidding_start") or None,
        "periods": periods,
        # Если карточку скачать не удалось - хотя бы первое фото из таблицы.
        "photos": d.get("photos") or ([{"full": row["photo_url"], "thumb": row["photo_url"]}]
                                      if row.get("photo_url") else []),
        "description": d.get("description"),
        "autoru_price_low": _to_int(row.get("autoru_price_low")),
        "autoru_price_high": _to_int(row.get("autoru_price_high")),
        "autoru_owners": _to_int(row.get("autoru_owners_count")),
        "estimate_uncertain": lot_metrics.estimate_is_uncertain(
            row.get("autoru_uncertainty_percent"), row.get("autoru_status")),
        # тип лота из листа (по title + описанию из lots); если колонки ещё
        # нет - считаем сами по title и описанию из карточки
        "lot_kind": row.get("lot_kind") or lot_metrics.lot_kind(
            (row.get("title") or "") + " " + (d.get("description") or "")),
    }


def run(dry_run=False):
    api_url = (config.MINIAPP_API_URL or "").rstrip("/")
    token = config.MINIAPP_IMPORT_TOKEN
    if not dry_run and (not api_url or not token):
        print("MINIAPP_API_URL / MINIAPP_IMPORT_TOKEN не заданы в local_secrets.py - выгрузку в мини-апп пропускаю.")
        return

    print(f"Читаю лист {SOURCE_SHEET}...")
    rows, seen = [], set()
    for r in read_sheet():
        m = LOT_ID_RE.search(r.get("url") or "")
        if m and m.group(1) not in seen:  # дубли по лоту - берём первую строку
            seen.add(m.group(1))
            rows.append(r)
    print(f"  лотов: {len(rows)}")

    cache = _load_cache()
    todo = [r for r in rows if _needs_refresh(cache.get(LOT_ID_RE.search(r["url"]).group(1)))]
    print(f"Карточек лотов для скачивания (новые + устаревший кэш): {len(todo)}")
    session = requests.Session()
    for i, row in enumerate(todo, start=1):
        lot_id = LOT_ID_RE.search(row["url"]).group(1)
        try:
            cache[lot_id] = fetch_details(row["url"], session)
            d = cache[lot_id]
            print(f"  [{i}/{len(todo)}] {lot_id}: фото {len(d['photos'])}, периодов {len(d['periods'])}")
        except Exception as e:  # сеть/вёрстка - лот всё равно выгрузим, с данными из таблицы
            cache[lot_id] = {**(cache.get(lot_id) or {}), "error": str(e)[:200]}
            print(f"  [{i}/{len(todo)}] {lot_id}: не удалось скачать карточку: {e}")
        if i % 20 == 0:
            _save_cache(cache)  # чтобы прерванный первый прогон не начинать заново
        time.sleep(config.DELAY_BETWEEN_LOT_REQUESTS)
    _save_cache(cache)

    payload = {"lots": [build_lot(r, cache.get(LOT_ID_RE.search(r["url"]).group(1))) for r in rows]}

    if dry_run:
        with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"--dry-run: ничего не отправлено, payload сохранён в {PREVIEW_FILE}")
        return

    print(f"Отправляю {len(payload['lots'])} лотов в {api_url}/api/import ...")
    try:
        resp = requests.post(f"{api_url}/api/import", json=payload,
                             headers={"X-Import-Token": token}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        print(f"  Не удалось выгрузить в мини-апп: {e} {detail[:300]}")
        print("  Мини-апп продолжит показывать прошлую выгрузку. Остальной пайплайн это не затрагивает.")
        return
    result = resp.json()
    print(f"  Готово: загружено {result.get('imported')}, ушли из листа (скрыты из ленты): {result.get('left_source')}")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
