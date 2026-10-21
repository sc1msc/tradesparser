# -*- coding: utf-8 -*-
r"""
Фото машины из документов торгов ЦДТ (раздел «Документы и дополнительные материалы»), с 21.10.2026.

Зачем. У части лотов ЦДТ фото нет ни в карточке лота, ни на странице торгов: организатор кладёт их
документом «Фото ТС» - обычно PDF, где на каждой странице снимок (лот 7173123: 7 фото 1080x810). Это
оригиналы без водяных знаков, а у агрегатора у таких лотов либо его копии со знаком, либо ничего
(у 57 лотов ЦДТ ленты фото не было нигде, 21.10.2026). Решение владельца: брать.

Как. Открытый API ЦДТ (тот же, что у браузера, ключ не нужен):
  Trade/public/<номер торгов>                     -> docs: [{name, id}]
  Doc/public/?DocId=<id>&tradeId=<номер торгов>   -> items: [{fileName, docFileId}]
  Doc/public/file?DocId=..&FileId=..&tradeId=..   -> сам файл (PDF или картинка)
Берём документы, в названии которых есть «фото», и не берём сканы (ПТС, СТС, паспорт, договор...):
там те же страницы, но документы. Из PDF вынимаем картинки (pypdf), мелкие (печати, логотипы - меньше
MIN_SIDE) отбрасываем. Каждое фото сохраняем у себя (DIR рядом с базой) с превью THUMB_SIDE, отдаём
GET /docimg/<имя> (main.py) - браузер пользователя к ЦДТ не ходит.

Вызывается из etp_collect.photo_pass для лотов ЦДТ, у которых на странице торгов фото нет.
"""
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request

from . import db, status_refresh

API = "https://webapi.torgi.cdtrf.ru"
# документ с фото: «Фото ТС», «Фотографии», и просто «авто» / «автомобиль» / «ТС» (380609: авто.pdf)
PHOTO_DOC_RE = re.compile(r"фото|foto|photo|изображ|снимк|^\s*(авто|автомобиль|тс|транспортное средство|машина)\s*$", re.I)
# документы-бумаги: их не берём, даже если внутри картинки (сканы)
SCAN_DOC_RE = re.compile(r"птс|стс|паспорт|свидетельств|договор|заявк|сообщени|положени|отч[её]т|выписк|сч[её]т|"
                         r"протокол|приказ|определени|решени|доверенн|реквизит|оценк|(?:^|\W)акт(?:\W|$)", re.I)
IMAGE_FILE_RE = re.compile(r"\.(jpe?g|png|webp|heic)$", re.I)
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_PHOTOS = 20       # на лот
MIN_SIDE = 300        # меньше по короткой стороне - печать, логотип, иконка
THUMB_SIDE = 480
NAME_RE = re.compile(r"^[0-9a-f]{40}(?:_t)?\.jpg$")


def photo_dir():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "doc_photos")


def _get(url, as_json=False):
    """Запрос к API ЦДТ: пауза площадки после отказов (status_refresh.check_paused) и учёт 403/429."""
    h = status_refresh.check_paused(url)
    req = urllib.request.Request(url, headers={"User-Agent": status_refresh.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=status_refresh.HOST_TIMEOUT.get(h, 90)) as resp:
            data = resp.read(MAX_FILE_BYTES + 1)
    except urllib.error.HTTPError as e:
        status_refresh.note_response(h, e.code)
        raise
    status_refresh.note_response(h, 200)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("файл больше 40 МБ")
    return json.loads(data.decode("utf-8")) if as_json else data


def photo_files(trade_id, get=_get):
    """Файлы с фото машины в документах торгов -> [(doc_id, file_id, file_name)]: все файлы документа-фото
    (по названию), а из документов с другим названием (кроме бумаг) - только файлы-картинки."""
    trade = get(f"{API}/Trade/public/{trade_id}", as_json=True) or {}
    out = []
    for doc in trade.get("docs") or []:
        name = doc.get("name") or ""
        if SCAN_DOC_RE.search(name):
            continue
        photo_doc = bool(PHOTO_DOC_RE.search(name))
        meta = get(f"{API}/Doc/public/?DocId={doc['id']}&tradeId={trade_id}", as_json=True) or {}
        for item in meta.get("items") or []:
            fname = item.get("fileName") or ""
            if item.get("docFileId") and (photo_doc or IMAGE_FILE_RE.search(fname)):
                out.append((doc["id"], item["docFileId"], fname))
    return out


def images_from_file(data):
    """Байты файла -> список JPEG-картинок (байты). PDF - вложенные изображения; картинка - она сама."""
    from PIL import Image  # только на сервере (requirements.txt), ПК этот модуль не импортирует
    if data[:5] == b"%PDF-":
        import pypdf
        out = []
        for page in pypdf.PdfReader(io.BytesIO(data)).pages:
            for im in page.images:
                try:
                    out.append(_to_jpeg(Image.open(io.BytesIO(im.data))))
                except Exception:
                    continue  # картинка в редком формате - пропускаем
        return [x for x in out if x]
    try:
        jpg = _to_jpeg(Image.open(io.BytesIO(data)))
    except Exception:
        return []  # не картинка (doc, zip) - не разбираем
    return [jpg] if jpg else []


def _to_jpeg(img, side=None):
    """PIL-картинка -> JPEG (байты), уменьшенная до side по длинной стороне; мелкая - None."""
    if min(img.size) < MIN_SIDE and side is None:
        return None
    img = img.convert("RGB")
    if side:
        img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def save(jpeg):
    """Фото и превью на диск -> {full, thumb} (адреса /docimg/...). Имя - хэш содержимого: повтор не множит."""
    from PIL import Image
    os.makedirs(photo_dir(), exist_ok=True)
    name = hashlib.sha1(jpeg).hexdigest()
    full, thumb = f"{name}.jpg", f"{name}_t.jpg"
    if not os.path.exists(os.path.join(photo_dir(), full)):
        with open(os.path.join(photo_dir(), thumb), "wb") as f:
            f.write(_to_jpeg(Image.open(io.BytesIO(jpeg)), THUMB_SIDE))
        with open(os.path.join(photo_dir(), full), "wb") as f:
            f.write(jpeg)
    return {"full": f"/docimg/{full}", "thumb": f"/docimg/{thumb}"}


def cdt_photos(trade_id, get=_get):
    """Фото машины из документов торгов ЦДТ -> [{full, thumb}] (пусто - документов-фото нет)."""
    out = []
    for doc_id, file_id, _name in photo_files(trade_id, get):
        data = get(f"{API}/Doc/public/file?DocId={doc_id}&FileId={file_id}&tradeId={trade_id}")
        for jpeg in images_from_file(data):
            out.append(save(jpeg))
            if len(out) >= MAX_PHOTOS:
                return out
    return out


def path(name):
    """Файл фото по имени из адреса /docimg/<name> или None (имя не наше)."""
    if not NAME_RE.match(name or ""):
        return None
    p = os.path.join(photo_dir(), name)
    return p if os.path.exists(p) else None
