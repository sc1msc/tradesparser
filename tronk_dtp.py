# -*- coding: utf-8 -*-
"""
ДТП по VIN через ПЛАТНЫЙ метод TRONK dtp («ДТП по VIN (кэш)», ~0.4 руб/запрос на 19.10.2026).
Документация: https://data.tronk.info/docs/dtp

Метод отдаёт то, что уже есть в базе TRONK (данные Госавтоинспекции, собранные раньше), а не
спрашивает Госавтоинспекцию в момент запроса: дата requestDate - когда TRONK последний раз
обновлял машину. Поэтому в мини-аппе пишем «по данным на …».

Три исхода (проверено пробными запросами 19.10.2026):
  - данные есть, ДТП были:  error=false, dtpData.hasDtp=true, dtpData.accident=[{type, date
    "20.04.2024 12:40", region, marka, model, schemeUrl}, ...];
  - данные есть, ДТП нет:   error=false, hasDtp=false, accident=[] -> «ДТП не найдены»;
  - данных по машине нет:   error=true, error_msg «Не удалось получить данные по VIN:...» -> блок
    в мини-аппе не показываем (это не «чистая машина»).
schemeUrl - схема повреждений Госавтоинспекции (контур машины с зонами или точками удара),
https://data.tronk.info/img.ashx?mode=sr&id=<номер>; открывается без ключа. Номера маленькие -
это общие шаблоны, поэтому храним только номер, а картинку отдаёт наш сервер через /img (кэш).
Модель в ответе бывает обобщённой («Прочие модели Mazda») - сверять с лотом можно только марку.

ВАЖНО: каждый вызов get_dtp() - платный запрос. Модуль вызывает только fill_dtp.py (шаг конвейера
с лимитом и месячным бюджетом).
"""
import datetime
import re

import requests

ENDPOINT = "https://data.tronk.info/dtp.ashx"
METHOD = "dtp"
# Цена, если прайс TRONK (метод profile) не ответил; проверено списанием 19.10.2026.
PRICE_PER_REQUEST_RUB = 0.4
SCHEME_ID_RE = re.compile(r"[?&]id=(\d+)")
NO_DATA_RE = re.compile(r"не удалось получить данные", re.I)


def get_dtp(api_key, vin, timeout=60):
    """ОДИН платный запрос к TRONK. Возвращает JSON ответа как есть."""
    resp = requests.get(ENDPOINT, params={"key": api_key, "vin": vin}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _iso(value, with_time=True):
    """'20.04.2024 12:40' / '11.06.2024 14:46:12' -> '2024-04-20T12:40' / '2024-06-11'."""
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.datetime.strptime(str(value or "").strip(), fmt)
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%dT%H:%M") if with_time else dt.strftime("%Y-%m-%d")
    return None


def scheme_id(url):
    m = SCHEME_ID_RE.search(url or "")
    return int(m.group(1)) if m else None


def parse(raw):
    """Ответ TRONK -> {status: ok | no_data | error: <текст>, accidents: [...], as_of: 'YYYY-MM-DD'}.
    accidents - от нового к старому: {date, type, region, marka, model, scheme (номер схемы или None)}."""
    if not isinstance(raw, dict):
        return {"status": "error: ответ не JSON", "accidents": [], "as_of": None}
    if raw.get("error"):
        msg = str(raw.get("error_msg") or "ошибка без описания")
        return {"status": "no_data" if NO_DATA_RE.search(msg) else f"error: {msg[:150]}",
                "accidents": [], "as_of": None}
    data = raw.get("dtpData") or {}
    items = data.get("accident") or []
    if isinstance(items, dict):  # одна запись - на всякий случай и объектом
        items = [items]
    accidents = []
    for a in items:
        if not isinstance(a, dict):
            continue
        accidents.append({
            "date": _iso(a.get("date")),
            "type": (a.get("type") or "").strip() or None,
            "region": (a.get("region") or "").strip() or None,
            "marka": (a.get("marka") or "").strip() or None,
            "model": (a.get("model") or "").strip() or None,
            "scheme": scheme_id(a.get("schemeUrl")),
        })
    accidents.sort(key=lambda a: a["date"] or "", reverse=True)
    return {"status": "ok", "accidents": accidents, "as_of": _iso(data.get("requestDate"), with_time=False)}
