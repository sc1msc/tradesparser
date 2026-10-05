# -*- coding: utf-8 -*-
r"""
API мини-аппа honestlot (FastAPI) + раздача статики фронтенда.

Эндпоинты (все /api/* кроме /api/import требуют Telegram initData в
заголовке "Authorization: tma <initData>", см. auth.py):
  GET    /api/lots               - лента: фильтры, сортировка, пагинация
                                   (limit=0 - только число результатов,
                                   для кнопки "Показать N лотов")
  GET    /api/facets             - варианты для экрана фильтров
  GET    /api/lots/{id}          - карточка лота целиком
  GET    /api/favorites          - избранное текущего пользователя
  PUT    /api/favorites/{id}     - добавить в избранное
  DELETE /api/favorites/{id}     - убрать из избранного
  GET    /api/me                 - код пользователя для ссылок "Поделиться"
                                   (t.me/<бот>?startapp=lot<id>_<код>, см. auth.split_start_param)
  POST   /api/events             - событие для аналитики: {"type": "open"} при
                                   старте, {"type": "source_click", "lot_id"} при
                                   переходе на сайт торгов, {"type": "share", "lot_id", "place"}
                                   при "Поделиться" (остальное пишет сервер)
  GET    /api/watchlist          - (ключ импорта) лоты из избранного, чей итог
                                   торгов ещё неизвестен - ПК перечитывает их на сайте
  POST   /api/lot-status         - (ключ импорта) статусы, перечитанные с сайта
  POST   /api/import             - загрузка лотов с ПК (export_to_miniapp.py),
                                   защищён ключом X-Import-Token
                                   (переменная окружения HONESTLOT_IMPORT_TOKEN)
  GET    /api/backup             - (ключ импорта) свежая копия базы для ПК;
                                   ежедневные копии сервер делает сам (backup.py)

Фронтенд (miniapp/frontend) раздаётся этим же приложением с корня "/" -
один процесс на всё, отдельный веб-сервер для статики не нужен (на
сервере перед ним стоит только Caddy ради HTTPS).

Запуск локально (из корня репозитория, см. miniapp/README.md):
  python -m uvicorn app.main:app --app-dir miniapp/backend --reload
"""
import contextlib
import datetime
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, backup, db, lots

FRONTEND_DIR = os.environ.get("HONESTLOT_FRONTEND_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend"
)
MAX_PAGE = 50

@contextlib.asynccontextmanager
async def lifespan(_app):
    backup.start()  # ежедневная копия базы - фоновым потоком
    yield


app = FastAPI(title="honestlot", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _now_iso():
    return datetime.datetime.now(lots.MSK).isoformat(timespec="seconds")


def current_user(authorization, with_source=False):
    try:
        user = auth.user_from_header(authorization)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    source, ref_code = auth.split_start_param(user.get("start_param"))
    db.touch_user(int(user["id"]), user.get("username"), user.get("first_name"), _now_iso(),
                  source, ref_code)
    return (int(user["id"]), source) if with_source else int(user["id"])


@app.get("/api/lots")
def api_lots(request: Request, authorization: str = Header(default="")):
    uid = current_user(authorization)
    params = dict(request.query_params)
    try:
        offset = max(0, int(params.get("offset", 0)))
        limit = min(MAX_PAGE, max(0, int(params.get("limit", 20))))
    except ValueError:
        raise HTTPException(status_code=400, detail="offset/limit должны быть числами")
    return lots.search(params, lots.Favs(db.favorite_rows(uid)), offset=offset, limit=limit)


@app.get("/api/facets")
def api_facets(authorization: str = Header(default="")):
    uid = current_user(authorization)
    return lots.facets(lots.Favs(db.favorite_rows(uid)))


@app.get("/api/lots/{lot_id}")
def api_lot(lot_id: str, authorization: str = Header(default="")):
    uid = current_user(authorization)
    lot = lots.get(lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail="лот не найден")
    db.log_event(uid, "lot_view", _now_iso(), lot_id=lot_id)
    return lots.detail(lot, lots.now_msk(), lots.Favs(db.favorite_rows(uid)))


@app.get("/api/favorites")
def api_favorites(authorization: str = Header(default="")):
    uid = current_user(authorization)
    return {"items": lots.favorites_list(lots.Favs(db.favorite_rows(uid)))}


@app.put("/api/favorites/{lot_id}")
def api_favorite_add(lot_id: str, authorization: str = Header(default="")):
    uid = current_user(authorization)
    lot = lots.get(lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail="лот не найден")
    db.add_favorite(uid, lot_id, lot["car"], _now_iso())
    db.log_event(uid, "fav_add", _now_iso(), lot_id=lot_id)
    return {"ok": True}


@app.delete("/api/favorites/{lot_id}")
def api_favorite_remove(lot_id: str, authorization: str = Header(default="")):
    uid = current_user(authorization)
    lot = lots.get(lot_id)
    db.remove_favorite(uid, lot_id, lot["car"] if lot else None)
    return {"ok": True}


@app.get("/api/me")
def api_me(authorization: str = Header(default="")):
    uid = current_user(authorization)
    return {"ref": db.user_ref_code(uid)}


class EventPayload(BaseModel):
    type: str
    lot_id: str | None = None
    place: str | None = None


# откуда нажали "Поделиться": иконка вверху, кнопка внизу, уведомление после ♡
SHARE_PLACES = {"top", "bottom", "toast"}


@app.post("/api/events")
def api_event(payload: EventPayload, authorization: str = Header(default="")):
    uid, start_param = current_user(authorization, with_source=True)
    # с фронта принимаем только то, что сервер сам не видит
    if payload.type not in ("open", "source_click", "share"):
        raise HTTPException(status_code=400, detail="неизвестный тип события")
    # events.source: для open - метка источника, для share - место кнопки
    source = start_param if payload.type == "open" else None
    if payload.type == "share" and payload.place in SHARE_PLACES:
        source = payload.place
    db.log_event(uid, payload.type, _now_iso(), lot_id=payload.lot_id, source=source)
    return {"ok": True}


def _check_import_token(token):
    expected = os.environ.get("HONESTLOT_IMPORT_TOKEN", "")
    if not expected or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="неверный ключ импорта")


@app.get("/api/watchlist")
def api_watchlist(x_import_token: str = Header(default="")):
    _check_import_token(x_import_token)
    return {"lots": lots.watchlist()}


class StatusPayload(BaseModel):
    lots: list[dict]


@app.post("/api/lot-status")
def api_lot_status(payload: StatusPayload, x_import_token: str = Header(default="")):
    _check_import_token(x_import_token)
    n = db.update_statuses([x for x in payload.lots if x.get("lot_id")], _now_iso())
    lots.invalidate()
    return {"updated": n}


class ImportPayload(BaseModel):
    lots: list[dict]


@app.post("/api/import")
def api_import(payload: ImportPayload, x_import_token: str = Header(default="")):
    expected = os.environ.get("HONESTLOT_IMPORT_TOKEN", "")
    if not expected or not hmac.compare_digest(expected, x_import_token):
        raise HTTPException(status_code=403, detail="неверный ключ импорта")
    bad = [i for i, lot in enumerate(payload.lots) if not lot.get("lot_id")]
    if bad:
        raise HTTPException(status_code=400, detail=f"нет lot_id у записей: {bad[:10]}")
    imported, hidden = db.import_lots(payload.lots, _now_iso())
    lots.invalidate()
    return {"imported": imported, "left_source": hidden}


@app.get("/api/backup")
def api_backup(x_import_token: str = Header(default="")):
    _check_import_token(x_import_token)
    path = backup.snapshot(os.path.join(backup.backup_dir(), "download.db"))
    return FileResponse(path, media_type="application/octet-stream", filename="honestlot.db")


@app.get("/api/health")
def health():
    return {"ok": True, "lots": len(lots.load())}


# --- фронтенд ---
# index.html отдаём без кэша: после выкладки новой версии Telegram должен
# сразу подхватить новые ссылки на app.js/style.css (у них ?v=... в index).
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
