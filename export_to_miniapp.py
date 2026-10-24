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

После выгрузки - итоги торгов для избранного: сервер отдаёт список лотов из
избранного (и лотов избранных машин), у которых приём заявок закончился, а
окончательного статуса ещё нет (GET /api/watchlist); их карточки
перечитываются с сайта, статусы уходят на сервер (POST /api/lot-status).
Таких лотов единицы-десятки, перепроверка не чаще раза в сутки на лот.

В конце - копия базы мини-аппа на ПК (GET /api/backup) в BACKUP_DIR, хранятся
BACKUP_KEEP последних. Сервер и сам делает копию раз в сутки, но на той же ВМ:
если пропадёт диск, останется копия здесь. В базе невосстановимое -
пользователи, избранное, статистика; лоты восстановимы новой выгрузкой.

Лоты, собранные прямо с площадок (номер от etp_lots.ETP_ID_BASE, url - страница лота на
ЭТП): карточки у агрегатора у них нет, фото, график и описание кладёт в кэш шаг 1
(main.pull_etp_lots) из того, что прочитал сервер, - здесь их карточки не скачиваются, и
их итоги для избранного проверяет сам сервер (status_refresh.py).

Лоты-призраки. Агрегатор иногда создаёт страницу лота по ошибке и потом
удаляет её (01.10.2026 - лот 7159530, дубль Renault Logan с другой ценой).
Такая страница отдаётся с кодом 200, но без данных лота и с общим
заголовком "Торги России" - как страница несуществующего лота. Если так
было при двух проверках с разницей не меньше GHOST_CONFIRM_HOURS часов,
лот в мини-апп больше не выгружается (сервер скроет его из ленты). Две
проверки - чтобы кратковременный сбой сайта не скрыл живые лоты.

Если в local_secrets.py не заданы MINIAPP_API_URL / MINIAPP_IMPORT_TOKEN -
шаг ничего не делает (пайплайн работает как раньше). Если сервер
недоступен - шаг печатает ошибку и НЕ роняет пайплайн: мини-апп просто
покажет вчерашние данные. Убрать шаг из пайплайна - закомментировать
одну строку в STEPS в run_pipeline.py.

Отдельный запуск: python export_to_miniapp.py
  (--dry-run - всё собрать, но не отправлять; сохранит payload в
   miniapp_export_preview.json для проверки; --force - отправить, даже если выгрузка
   скрыла бы больше половины ленты: сервер такую не принимает без этого флага)
"""
import datetime
import glob
import json
import os
import re
import sqlite3
import sys
import time

import gspread
import requests
from google.oauth2.service_account import Credentials

import automation
import bidding_schedule
import config
import etp_lots
import etp_status
import lot_metrics
import main
from nextjs_json import extract_combined_payload, find_json_value, resolve_text_ref

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SOURCE_SHEET = "lots_current_month"
DETAILS_CACHE_FILE = "miniapp_details_cache.json"
DAMAGE_CACHE_FILE = "damage_check_cache.json"  # вердикты проверки фото (check_damage_photos.py)
PREVIEW_FILE = "miniapp_export_preview.json"
LOT_ID_RE = re.compile(r"/lot/(\d+)")
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
GHOST_CONFIRM_HOURS = 6
GENERIC_TITLE = "Торги России"  # заголовок страницы, когда лота на сайте нет
BACKUP_DIR = "miniapp_backups"
BACKUP_KEEP = 7


class LotNotFound(Exception):
    """Страница лота есть, но лота на ней нет (призрак или удалённый лот)."""


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


# Ссылка на лот на самой ЭТП - туда ведёт кнопка «Открыть лот на сайте торгов» (etp_status.etp_link).
etp_link = etp_status.etp_link


def fetch_details(url, session):
    """Карточка лота -> то, что нужно мини-аппу и чего нет в таблице."""
    html = main.fetch(url, session)
    payload = extract_combined_payload(html)
    lot, _ = find_json_value(payload, "lot", kind="object")
    if lot is None:
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        if title and title.group(1).strip() == GENERIC_TITLE:
            raise LotNotFound("лота нет на сайте")
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
        "etp_url": etp_link(lot),
        "efrsb_url": etp_status.efrsb_link(lot),  # объявление на ЕФРСБ: кнопка лота «вне ЭТП» ведёт сюда
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def lot_id_of(row):
    """Номер лота строки листа: колонка lot_id; в lots_current_month её нет - из ссылки: у лотов
    агрегатора /lot/<номер>, у лотов с площадок - по адресу страницы на площадке (etp_lots)."""
    lot_id = str(row.get("lot_id") or "").strip()
    if lot_id.isdigit():
        return lot_id
    m = LOT_ID_RE.search(row.get("url") or "")
    return m.group(1) if m else etp_lots.lot_id_from_url(row.get("url"))


def _hours_since(value):
    try:
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(value)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def is_ghost(entry):
    """Лот подтверждённо пропал с сайта: две проверки с разницей >= GHOST_CONFIRM_HOURS."""
    if not entry or entry.get("not_found_checks", 0) < 2:
        return False
    since = _hours_since(entry.get("not_found_since"))
    return since is not None and since >= GHOST_CONFIRM_HOURS


def _needs_refresh(entry, lot_id=None):
    if etp_lots.is_etp_lot_id(lot_id):
        return False  # лот с площадки: кэш заполняет main.pull_etp_lots, у агрегатора карточки нет
    if entry and entry.get("not_found_checks"):
        # подозрение на призрак - перепроверяем, но не чаще чем через GHOST_CONFIRM_HOURS
        if is_ghost(entry):
            return False
        last = _hours_since(entry.get("not_found_checked_at"))
        return last is None or last >= GHOST_CONFIRM_HOURS
    if not entry or entry.get("error"):
        return True
    if "efrsb_url" not in entry and not entry.get("etp_url"):
        return True  # лот «вне ЭТП», скачанный до 17.10.2026: нужна ссылка на ЕФРСБ для кнопки
    try:
        fetched = datetime.datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, ValueError):
        return True
    return datetime.datetime.now() - fetched > datetime.timedelta(days=config.MINIAPP_DETAILS_REFRESH_DAYS)


# Обрыв соединения с Google посреди прогона (21.10.2026 так не прочитался vin_cache, и выгрузка ушла
# без ДТП) - повторяем чтение с паузой.
SHEET_READ_ATTEMPTS = 3
SHEET_READ_PAUSE_SEC = 30


def read_sheet(name=SOURCE_SHEET):
    for attempt in range(1, SHEET_READ_ATTEMPTS + 1):
        try:
            creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            ws = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID).worksheet(name)
            values = ws.get_all_values()
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == SHEET_READ_ATTEMPTS:
                raise
            print(f"  Google: лист {name} не прочитался ({str(e)[:100]}), повтор через {SHEET_READ_PAUSE_SEC} с")
            time.sleep(SHEET_READ_PAUSE_SEC)
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


def _mileage_source(row, mileage, estimated):
    """lot / report / estimate / None. TRONK спрашивают только у лотов без пробега в описании
    (fill_missing_mileage.py), поэтому статус ok - пробег из отчёта."""
    if mileage is None:
        return "estimate" if estimated is not None else None
    return "report" if (row.get("mileage_probeg_status") or "").strip() == "ok" else "lot"


def read_dtp():
    """ДТП по VIN из справочника vin_cache (их покупает fill_dtp.py, шаг 7): {VIN: строка справочника}.
    Справочник недоступен - None: выгрузка уходит без поля dtp, и сервер оставляет лотам прежние ДТП
    (db.import_lots), а не стирает их, как 21.10.2026."""
    try:
        rows = read_sheet("vin_cache")
    except Exception as e:
        automation.alert(f"Выгрузка в мини-апп: справочник vin_cache не прочитался ({e}) - ДТП новых машин "
                         f"не выгружены, у остальных на сервере остались прежние.")
        return None
    return {(r.get("vin") or "").strip().upper(): r for r in rows if (r.get("dtp_status") or "").strip() == "ok"}


def _letters(value):
    return re.sub(r"[^A-ZА-ЯЁ]", "", (value or "").upper())


def _same_brand(marka, brand):
    """Марка из ответа TRONK - та же машина, что в лоте? Модель у TRONK бывает обобщённой («Прочие
    модели Mazda»), поэтому только марка, и мягко: расхождение - только когда обе латиницей и ни одна
    не начинается с другой («ВАЗ» против «LADA» не сравниваем)."""
    a, b = _letters(marka), _letters(brand)
    if not a or not b or not (a.isascii() and b.isascii()):
        return True
    return a.startswith(b[:4]) or b.startswith(a[:4])


def dtp_payload(rec, brand):
    """Строка справочника -> {count, as_of, accidents: [{date, type, region, scheme}]} или None (нет данных).
    ДТП чужой марки (опечатка в VIN у организатора) отбрасываем; если отброшены все - «нет данных»,
    а не «ДТП не найдены»."""
    if not rec:
        return None
    try:
        accidents = json.loads(rec.get("dtp_accidents") or "[]")
    except ValueError:
        return None
    kept = [a for a in accidents if _same_brand(a.get("marka"), brand)]
    if accidents and not kept:
        return None
    return {
        "count": len(kept),
        "as_of": (rec.get("dtp_as_of") or "")[:10] or None,
        "accidents": [{k: a.get(k) for k in ("date", "type", "region", "scheme")} for a in kept],
    }


def build_lot(row, details, damage=None, dtp=None):
    lot_id = lot_id_of(row)
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
    lot = {
        "lot_id": lot_id,
        "url": row.get("url"),
        "title": row.get("title"),
        # autoru_mark/autoru_model - чистые названия ("KIA", "SOLARIS"); brand/name
        # (Autodoc или разбор title) бывают вида "Audi A6 Av. 2,0 TDI" или кусок
        # фразы - только как запасной вариант. Дочистка - в бэкенде (lots.py).
        "brand": row.get("autoru_mark") or row.get("brand"),
        "model": row.get("autoru_model") or row.get("name"),
        # откуда марка/модель и что было разобрано из названия: бэкенд по лотам
        # с Авто.ру собирает словарь моделей и привязывает к нему модели лотов
        # без оценки ("Фокус", "219010 Granta" -> Focus, Granta), см. lots.py
        "model_source": "autoru" if row.get("autoru_mark") else "title",
        "title_brand": row.get("brand") or None,
        "title_model": row.get("name") or None,
        "year": _to_int(row.get("year")) or _to_int(row.get("autoru_year")),
        "vin": row.get("vin") or None,
        "plate": row.get("plate") or None,
        # Настоящий пробег (лот / TRONK) важнее оценки по году выпуска;
        # оценку показываем со значком "~".
        "mileage_km": mileage if mileage is not None else estimated,
        "mileage_estimated": mileage is None and estimated is not None,
        # откуда пробег: lot - из описания лота, report - показание из отчёта TRONK, пересчитанное на
        # сегодня (+ANNUAL_MILEAGE_KM в год), estimate - расчёт по году выпуска; дата показания отчёта
        "mileage_source": _mileage_source(row, mileage, estimated),
        "mileage_record_date": (row.get("mileage_probeg_date") or "")[:10] or None
        if _mileage_source(row, mileage, estimated) == "report" else None,
        "price_start": _to_int(row.get("price_start")),
        "price_current": _to_int(row.get("price_current")),
        "region": row.get("region") or None,
        "trade_form": trade_form,
        "is_public_offer": is_public_offer,
        "status": row.get("status") or d.get("status"),
        "platform": d.get("platform") or row.get("platform") or None,
        # ссылка на лот на ЭТП (карточки, скачанные до 15.10.2026, - без неё); устаревшие (старый поиск
        # Профита) - в рабочий вид
        "etp_url": etp_status.normalize_etp_url(d.get("etp_url") or row.get("etp_url")) or None,
        "efrsb_url": d.get("efrsb_url"),
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
        # характеристики модификации по данным оценки (autoru_valuation.parse_specs)
        "engine_type": row.get("autoru_engine_type") or None,
        "displacement": _to_int(row.get("autoru_displacement")),
        "power": _to_int(row.get("autoru_power")),
        "drive": row.get("autoru_drive") or None,
        "transmission": row.get("autoru_transmission") or None,
        # кузов - только из оценки (код Авто.ру и подпись), разбор из текста не делаем: типы дублировались бы
        "body_type": row.get("autoru_body_type") or None,
        "body": row.get("autoru_body") or None,
        "estimate_uncertain": lot_metrics.estimate_is_uncertain(
            row.get("autoru_uncertainty_percent"), row.get("autoru_status")),
        # тип лота из листа (по title + описанию из lots); если колонки ещё
        # нет - считаем сами по title и описанию из карточки
        "lot_kind": row.get("lot_kind") or lot_metrics.lot_kind(
            (row.get("title") or "") + " " + (d.get("description") or "")),
        # проверка фото (check_damage_photos.py): total - тотальные повреждения,
        # мини-апп прячет такие лоты галочкой "Скрыть битые"
        "photo_verdict": (damage or {}).get("verdict"),
        "photo_signs": (damage or {}).get("signs") or [],
    }
    # ДТП по VIN (fill_dtp.py -> vin_cache): None - не проверяли или данных нет; count 0 - «ДТП не найдены».
    # Справочник не прочитался (dtp is None) - поля нет вовсе: сервер оставит прежнее значение.
    if dtp is not None:
        lot["dtp"] = dtp_payload(dtp.get((row.get("vin") or "").strip().upper()),
                                 row.get("autoru_mark") or row.get("brand"))
    return lot


def refresh_watchlist(api_url, token, session, cache):
    """Итоги торгов для лотов из избранного (см. докстринг модуля). Ошибки
    печатаются и не роняют пайплайн."""
    headers = {"X-Import-Token": token}
    try:
        resp = requests.get(f"{api_url}/api/watchlist", headers=headers, timeout=60)
        resp.raise_for_status()
        # итоги лотов с площадок сервер проверяет сам, на площадке (status_refresh.py)
        watch = [w for w in resp.json().get("lots", []) if w.get("url") and not etp_lots.is_etp_lot_id(w.get("lot_id"))]
    except requests.RequestException as e:
        print(f"  Не удалось получить список избранного для перепроверки: {e}")
        return
    print(f"Лотов из избранного без итога торгов: {len(watch)}")
    if not watch:
        return
    statuses = []
    for i, w in enumerate(watch, start=1):
        try:
            details = fetch_details(w["url"], session)
            cache[str(w["lot_id"])] = details
            statuses.append({"lot_id": w["lot_id"], "status": details.get("status")})
            print(f"  [{i}/{len(watch)}] {w['lot_id']}: {details.get('status')}")
        except LotNotFound:
            statuses.append({"lot_id": w["lot_id"], "status": "Лот удалён с сайта"})
            print(f"  [{i}/{len(watch)}] {w['lot_id']}: лота нет на сайте")
        except Exception as e:
            print(f"  [{i}/{len(watch)}] {w['lot_id']}: не удалось перечитать: {e}")
        time.sleep(config.DELAY_BETWEEN_LOT_REQUESTS)
    _save_cache(cache)
    if not statuses:
        return
    try:
        resp = requests.post(f"{api_url}/api/lot-status", json={"lots": statuses}, headers=headers, timeout=60)
        resp.raise_for_status()
        print(f"  Статусы обновлены на сервере: {resp.json().get('updated')}")
    except requests.RequestException as e:
        print(f"  Не удалось отправить статусы: {e}")


def download_backup(api_url, token):
    """Копия базы мини-аппа на ПК: одна на день (повторный прогон в тот же
    день её перезапишет), BACKUP_KEEP последних. Перед сохранением - проверка
    целостности, чтобы битая загрузка не вытеснила хорошую копию. Ошибки
    печатаются и не роняют пайплайн."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"honestlot-{datetime.date.today().isoformat()}.db")
    tmp = path + ".tmp"
    try:
        with requests.get(f"{api_url}/api/backup", headers={"X-Import-Token": token}, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(1 << 16):
                    f.write(chunk)
        con = sqlite3.connect(tmp)
        try:
            check = con.execute("PRAGMA integrity_check").fetchone()[0]
            users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            favs = con.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
        finally:
            con.close()
        if check != "ok":
            raise ValueError(f"копия повреждена: {check}")
        os.replace(tmp, path)
    except (requests.RequestException, sqlite3.Error, ValueError, OSError) as e:
        automation.alert(f"Копия базы мини-аппа не скачалась: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return
    for old in sorted(glob.glob(os.path.join(BACKUP_DIR, "honestlot-*.db")))[:-BACKUP_KEEP]:
        os.remove(old)
    print(f"Копия базы мини-аппа: {path} ({os.path.getsize(path) // 1024} КБ, "
          f"пользователей {users}, в избранном {favs})")


def run(dry_run=False, force=False):
    api_url = (config.MINIAPP_API_URL or "").rstrip("/")
    token = config.MINIAPP_IMPORT_TOKEN
    if not dry_run and (not api_url or not token):
        print("MINIAPP_API_URL / MINIAPP_IMPORT_TOKEN не заданы в local_secrets.py - выгрузку в мини-апп пропускаю.")
        return

    print(f"Читаю лист {SOURCE_SHEET}...")
    rows, seen, no_id = [], set(), []
    for r in read_sheet():
        lot_id = lot_id_of(r)
        if not lot_id:
            no_id.append(r)
        elif lot_id not in seen:  # дубли по лоту - берём первую строку
            seen.add(lot_id)
            rows.append(r)
    print(f"  лотов: {len(rows)}")
    if no_id:
        # Так 16.10.2026 молча не ушли в мини-апп 148 лотов с площадок (номер брали только из ссылки
        # агрегатора). Строку без номера выгрузить нельзя - значит, ссылка нового вида.
        automation.alert(f"Выгрузка в мини-апп: у {len(no_id)} строк среза не определился номер лота, они не "
                         f"выгружены (например, {(no_id[0].get('url') or 'без ссылки')[:80]}). Нужна правка "
                         f"export_to_miniapp.lot_id_of / etp_lots.lot_id_from_url.")

    cache = _load_cache()
    todo = [r for r in rows if _needs_refresh(cache.get(lot_id_of(r)), lot_id_of(r))]
    print(f"Карточек лотов для скачивания (новые + устаревший кэш): {len(todo)}")
    session = requests.Session()
    cards = main.CardFailures("Мини-апп, карточки лотов")
    for i, row in enumerate(todo, start=1):
        lot_id = lot_id_of(row)
        try:
            cache[lot_id] = fetch_details(row["url"], session)
            d = cache[lot_id]
            cards.ok()
            print(f"  [{i}/{len(todo)}] {lot_id}: фото {len(d['photos'])}, периодов {len(d['periods'])}")
        except LotNotFound:
            cards.ok()  # сайт ответил - лота на нём нет
            entry = dict(cache.get(lot_id) or {})
            now_iso = datetime.datetime.now().isoformat(timespec="seconds")
            entry["not_found_checks"] = entry.get("not_found_checks", 0) + 1
            entry.setdefault("not_found_since", now_iso)
            entry["not_found_checked_at"] = now_iso
            cache[lot_id] = entry
            print(f"  [{i}/{len(todo)}] {lot_id}: лота нет на сайте (проверка {entry['not_found_checks']})")
        except Exception as e:  # сеть/вёрстка - лот всё равно выгрузим, с данными из таблицы
            cache[lot_id] = {**(cache.get(lot_id) or {}), "error": str(e)[:200]}
            print(f"  [{i}/{len(todo)}] {lot_id}: не удалось скачать карточку: {e}")
            if cards.fail(e):
                # сайт лежит: остальные лоты уйдут с данными таблицы и старого кэша,
                # их карточки скачаются в следующий прогон
                print("  карточки не читаются - дальше не качаю")
                break
        if i % 20 == 0:
            _save_cache(cache)  # чтобы прерванный первый прогон не начинать заново
        time.sleep(config.DELAY_BETWEEN_LOT_REQUESTS)
    _save_cache(cache)
    cards.report(len(todo))

    ghosts = [r for r in rows if is_ghost(cache.get(lot_id_of(r)))]
    if ghosts:
        print(f"Лоты, пропавшие с сайта (не выгружаю): {', '.join(lot_id_of(r) for r in ghosts)}")
    ghost_ids = {id(r) for r in ghosts}
    damage = {}
    if os.path.exists(DAMAGE_CACHE_FILE):
        with open(DAMAGE_CACHE_FILE, encoding="utf-8") as f:
            damage = json.load(f)
    dtp = read_dtp()
    payload = {"lots": [build_lot(r, cache.get(lot_id_of(r)), damage.get(lot_id_of(r)), dtp)
                        for r in rows if id(r) not in ghost_ids]}
    print(f"  с данными о ДТП: {sum(1 for lot in payload['lots'] if lot.get('dtp') is not None)}")

    if dry_run:
        with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"--dry-run: ничего не отправлено, payload сохранён в {PREVIEW_FILE}")
        return

    print(f"Отправляю {len(payload['lots'])} лотов в {api_url}/api/import ...")
    try:
        resp = requests.post(f"{api_url}/api/import" + ("?force=1" if force else ""), json=payload,
                             headers={"X-Import-Token": token}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        detail = getattr(getattr(e, "response", None), "text", "")
        automation.alert(f"Выгрузка в мини-апп не прошла: {e} {detail[:200]}".strip())
        print("  Мини-апп продолжит показывать прошлую выгрузку. Остальной пайплайн это не затрагивает.")
        download_backup(api_url, token)  # пользователи и избранное копируются и без выгрузки
        return
    result = resp.json()
    print(f"  Готово: загружено {result.get('imported')}, ушли из листа (скрыты из ленты): {result.get('left_source')}")
    refresh_watchlist(api_url, token, session, cache)
    download_backup(api_url, token)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv, force="--force" in sys.argv)
