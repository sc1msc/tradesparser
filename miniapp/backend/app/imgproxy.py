# -*- coding: utf-8 -*-
r"""
Фото площадок, которые не пускают зарубежные адреса, - через наш сервер (GET /img?u=<адрес фото>).

Зачем. МЭТС отвечает 403 всем, кто заходит не с российского адреса (проверено 16.10.2026). Фото
лотов МЭТС в мини-аппе грузит браузер пользователя, и у пользователя с VPN они не открывались бы.
Сервер стоит в России: он скачивает фото сам, кладёт в кэш на диске и отдаёт пользователю.
Какие площадки - etp_lots.PROXY_PHOTO_HOSTS; адреса фото переписывает lots._public_photo.

Только фото этих площадок и только из папки фото (ALLOWED_PREFIXES): иначе сервер стал бы открытым
прокси для чего угодно. Кэш - CACHE_DIR рядом с базой, файл на адрес; старше CACHE_DAYS дней -
удаляется (cleanup, вызывается после прохода etp_collect). Фото лота почти не меняются, поэтому
браузеру разрешено держать его у себя месяц.
"""
import hashlib
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import db, status_refresh

ALLOWED_PREFIXES = {"m-ets.ru": "/download/"}
MAX_BYTES = 8 * 1024 * 1024
CACHE_DAYS = 45
FETCH_TIMEOUT = 20
BROWSER_CACHE_SECONDS = 30 * 24 * 3600
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class Refused(Exception):
    """Адрес не из разрешённых (сервер не открытый прокси)."""


def cache_dir():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "img_cache")


def allowed(url):
    try:
        p = urlsplit(url or "")
    except ValueError:
        return False
    prefix = ALLOWED_PREFIXES.get((p.hostname or "").lower())
    return p.scheme == "https" and prefix is not None and p.path.startswith(prefix) and ".." not in p.path


def media_type(url):
    return TYPES.get(os.path.splitext(urlsplit(url).path)[1].lower(), "image/jpeg")


def get(url):
    """Путь к файлу фото в кэше (скачивает, если его нет). Refused - адрес не разрешён;
    urllib.error.URLError / ValueError - площадка не отдала фото."""
    if not allowed(url):
        raise Refused(url)
    os.makedirs(cache_dir(), exist_ok=True)
    path = os.path.join(cache_dir(), hashlib.sha1(url.encode("utf-8")).hexdigest())
    if os.path.exists(path):
        return path
    req = urllib.request.Request(url, headers={"User-Agent": status_refresh.USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        if not (resp.headers.get_content_type() or "").startswith("image/"):
            raise ValueError(f"не фото: {resp.headers.get_content_type()}")
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("фото больше 8 МБ")
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def cleanup(now=None):
    """Удаляет из кэша файлы старше CACHE_DAYS дней. -> сколько удалено."""
    now = now or time.time()
    removed = 0
    try:
        names = os.listdir(cache_dir())
    except OSError:
        return 0
    for name in names:
        path = os.path.join(cache_dir(), name)
        try:
            if now - os.path.getmtime(path) > CACHE_DAYS * 86400:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed
