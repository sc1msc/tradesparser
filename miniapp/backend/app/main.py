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
  POST   /api/web-login          - вход в веб-версию (honestlot.ru в браузере): данные
                                   Telegram Login Widget -> токен входа (auth.py)
  GET    /api/me                 - код пользователя для ссылок "Поделиться"
                                   (t.me/<бот>?startapp=lot<id>_<код>, см. auth.split_start_param)
  POST   /api/events             - событие для аналитики: {"type": "open"} при
                                   старте, {"type": "source_click", "lot_id"} при
                                   переходе на сайт торгов, {"type": "share", "lot_id", "place"}
                                   при "Поделиться", {"type": "paywall"/"paywall_go", "place":
                                   "filters"/"favs"} - веб-версия без Pro показала предложение Pro /
                                   нажали "Перейти на Pro" (остальное пишет сервер)
  GET    /api/lot-statuses       - (ключ импорта) статусы торгов, которые сервер прочитал
                                   сам на агрегаторе и ЭТП (status_refresh.py) - ПК пишет их в лист
  POST   /api/notify             - (ключ импорта) уведомление пайплайна с ПК -> администратору
                                   через бота уведомлений (с ПК Telegram без VPN закрыт)
  GET    /img?u=<адрес>          - фото площадки, которая не пускает зарубежные адреса (МЭТС), через
                                   наш сервер (imgproxy.py); только разрешённые адреса
  GET    /api/stats/photos       - (ключ импорта) сколько лотов ленты с какими фото (сводка с ПК)
  GET    /api/etp-lots           - (ключ импорта) лоты, которые сервер сам собрал с площадок
                                   (etp_collect.py) - ПК дописывает новые в лист lots
  GET    /api/watchlist          - (ключ импорта) лоты из избранного, чей итог
                                   торгов ещё неизвестен - ПК перечитывает их на сайте
  POST   /api/lot-status         - (ключ импорта) статусы, перечитанные с сайта
  POST   /api/import             - загрузка лотов с ПК (export_to_miniapp.py),
                                   защищён ключом X-Import-Token
                                   (переменная окружения HONESTLOT_IMPORT_TOKEN)
  /api/pay/*, /pay/             - подписка Pro: оплата на сайте, автопродление, отмена
                                   (billing.py; выключено, пока HONESTLOT_PAYMENTS_ENABLED не "1")
  GET    /api/backup             - (ключ импорта) свежая копия базы для ПК;
                                   ежедневные копии сервер делает сам (backup.py)
  GET    /api/searches           - сохранённые поиски (Pro; searches.py), настройки уведомлений
  GET    /api/searches/preview   - имя и число лотов для окна «Сохранить поиск» (параметры как у ленты)
  POST   /api/searches           - сохранить поиск {params, name?, notify?}
  POST   /api/searches/{id}/open - поиск открыт: его новые лоты просмотрены
  PATCH  /api/searches/{id}      - переименовать, поменять фильтры, включить/выключить уведомления
  DELETE /api/searches/{id}      - удалить
  GET/POST /api/notify/settings  - каналы уведомлений (notify.py): {tg, fav_events, email_on}
  POST   /api/notify/email       - почта для писем {email}: ссылка подтверждения
  GET    /notify/confirm?t=      - подтверждение почты (ссылка из письма)
  GET/POST /notify/unsubscribe?t= - отписка от писем (страница с кнопкой; POST - и из почты)
  (поиски и уведомления выключены, пока не задан HONESTLOT_SAVED_SEARCHES, см. searches.py)

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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (auth, backup, billing, db, docphotos, etp_collect, imgproxy, lots, notify, searches, site, status_refresh,
               watchdog)

FRONTEND_DIR = os.environ.get("HONESTLOT_FRONTEND_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend"
)
MAX_PAGE = 50

@contextlib.asynccontextmanager
async def lifespan(_app):
    backup.start()    # ежедневная копия базы - фоновым потоком
    watchdog.start()  # давно нет выгрузки с ПК - сообщение администратору
    billing.start()   # автопродление подписок (только если оплата включена)
    status_refresh.start()  # статус торгов: агрегатор и ЭТП несколько раз в день
    etp_collect.start()     # новые лоты прямо с площадок, вместе с агрегатором
    notify.start()          # уведомления по сохранённым поискам и избранному (если включены)
    yield


app = FastAPI(title="honestlot", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(billing.router)
app.include_router(site.router)  # /pro, /offer, /privacy, /requisites - страницы для ЮKassa


def _now_iso():
    return datetime.datetime.now(lots.MSK).isoformat(timespec="seconds")


def current_user(authorization, with_source=False):
    try:
        user = auth.user_from_header(authorization)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    source, ref_code = auth.split_start_param(user.get("start_param"))
    if db.touch_user(int(user["id"]), user.get("username"), user.get("first_name"), _now_iso(),
                     source, ref_code):
        billing.claim_trial(int(user["id"]))  # новый пользователь - пробный Pro (до подарка по ссылке)
    billing.claim_pending(int(user["id"]), user.get("username"))  # подарок Pro на ник, если ждал первого входа
    if source not in (None, auth.SHARE_SOURCE, auth.WEB_SOURCE):
        billing.claim_promo(int(user["id"]), source)  # подарочная ссылка автора курса (edu_...)
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


class WebLoginPayload(BaseModel):
    user: dict  # поля, которые Telegram Login Widget передал в onauth (id, ..., auth_date, hash)
    start: str | None = None  # ?startapp=lot<id>_<код> из ссылки «Поделиться» веб-версии


@app.post("/api/web-login")
def api_web_login(payload: WebLoginPayload):
    """Вход в веб-версию: данные виджета Telegram -> токен входа на 30 дней (auth.py)."""
    try:
        user = auth.validate_login_widget(payload.user, os.environ.get("HONESTLOT_BOT_TOKEN", ""))
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    # пришёл по ссылке «Поделиться» из веб-версии - как в мини-аппе: источник share и кто пригласил;
    # другие метки из адреса не принимаем, иначе любой мог бы вписать себе источник
    source, ref_code = auth.split_start_param(payload.start)
    if source != auth.SHARE_SOURCE and not billing.promo(source):  # подарочная ссылка автора курса - тоже
        source, ref_code = auth.WEB_SOURCE, None
    if db.touch_user(int(user["id"]), user.get("username"), user.get("first_name"), _now_iso(), source, ref_code):
        billing.claim_trial(int(user["id"]))
    billing.claim_pending(int(user["id"]), user.get("username"))
    if source != auth.SHARE_SOURCE:
        billing.claim_promo(int(user["id"]), source)
    return {"token": auth.make_web_token(user), "first_name": user.get("first_name"), "username": user.get("username")}


@app.get("/api/me")
def api_me(authorization: str = Header(default="")):
    uid = current_user(authorization)
    me = {"ref": db.user_ref_code(uid)}
    gift = billing.promo_notice(uid)  # «вам подарен Pro» по ссылке автора курса - один раз
    if gift:
        me["gift"] = gift
    trial = billing.trial_notice(uid)  # «вам открыт Pro на 14 дней» новому пользователю - один раз
    if trial:
        me["trial"] = trial
    if billing.enabled():
        # только признак Pro: что он даёт, пока не решено (wiki/monetization.md)
        me["pro"] = billing.is_pro(uid)
    if searches.enabled_for(uid):
        me["searches"] = True  # сохранённые поиски и уведомления (включаются HONESTLOT_SAVED_SEARCHES)
    return me


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
    if payload.type not in ("open", "source_click", "share", "paywall", "paywall_go", "notify_open"):
        raise HTTPException(status_code=400, detail="неизвестный тип события")
    # events.source: для open - метка источника, для share - место кнопки
    source = start_param if payload.type == "open" else None
    if payload.type == "share" and payload.place in SHARE_PLACES:
        source = payload.place
    if payload.type in ("paywall", "paywall_go") and payload.place in ("filters", "favs", "searches"):
        source = payload.place  # что пытались открыть без Pro
    if payload.type == "notify_open" and payload.place in ("notify", "email"):
        source = payload.place  # открыли мини-апп из уведомления в Telegram / из письма
    db.log_event(uid, payload.type, _now_iso(), lot_id=payload.lot_id, source=source)
    return {"ok": True}


def _check_import_token(token):
    expected = os.environ.get("HONESTLOT_IMPORT_TOKEN", "")
    if not expected or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="неверный ключ импорта")


@app.get("/api/lot-statuses")
def api_lot_statuses(x_import_token: str = Header(default="")):
    """Статусы, которые сервер прочитал сам (status_refresh.py) - ПК пишет их в лист lots в шаге 1."""
    _check_import_token(x_import_token)
    return {"lots": status_refresh.statuses()}


class NotifyPayload(BaseModel):
    text: str


@app.post("/api/notify")
def api_notify(payload: NotifyPayload, x_import_token: str = Header(default="")):
    """Уведомление пайплайна с ПК (automation.send_telegram): ПК идёт в Telegram без VPN, а
    api.telegram.org из России закрыт - сервер пересылает через релей, как свои уведомления."""
    _check_import_token(x_import_token)
    chat_id = watchdog.admin_chat_id()
    if not chat_id:
        raise HTTPException(status_code=503, detail="HONESTLOT_ADMIN_CHAT_ID не задан")
    try:
        watchdog._send(chat_id, payload.text[:4000])
    except Exception as e:  # релей/Telegram - ПК попробует отправить напрямую
        raise HTTPException(status_code=502, detail=f"Telegram: {str(e)[:200]}")
    return {"sent": True}


@app.get("/api/etp-lots")
def api_etp_lots(x_import_token: str = Header(default="")):
    """Лоты, собранные сервером с площадок (etp_collect.py) - ПК дописывает новые в лист lots в шаге 1."""
    _check_import_token(x_import_token)
    return {"lots": etp_collect.export()}


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


IMPORT_GUARD_MIN_FEED = 100  # на маленькой ленте (локальный запуск, первые выгрузки) проверка не нужна


class ImportPayload(BaseModel):
    lots: list[dict]


@app.post("/api/import")
def api_import(payload: ImportPayload, x_import_token: str = Header(default=""), force: bool = False):
    expected = os.environ.get("HONESTLOT_IMPORT_TOKEN", "")
    if not expected or not hmac.compare_digest(expected, x_import_token):
        raise HTTPException(status_code=403, detail="неверный ключ импорта")
    bad = [i for i, lot in enumerate(payload.lots) if not lot.get("lot_id")]
    if bad:
        raise HTTPException(status_code=400, detail=f"нет lot_id у записей: {bad[:10]}")
    # Выгрузка - весь срез: чего в ней нет, уходит из ленты. Срез, по ошибке собранный наполовину
    # (сбой пересборки, ссылки нового вида без номера лота - так 16.10.2026 пропали 148 лотов),
    # скрыл бы половину ленты. Такую выгрузку не принимаем (ПК пришлёт тревогу); если сокращение
    # настоящее - выгрузить с ?force=1 (python export_to_miniapp.py --force).
    feed = db.feed_lot_ids()
    leaving = len(feed - {str(lot["lot_id"]) for lot in payload.lots})
    if not force and len(feed) >= IMPORT_GUARD_MIN_FEED and leaving * 2 > len(feed):
        raise HTTPException(status_code=409, detail=f"выгрузка скрыла бы {leaving} из {len(feed)} лотов ленты - "
                                                    f"не принята; если так и надо - выгрузить с --force")
    imported, hidden = db.import_lots(payload.lots, _now_iso())
    lots.invalidate()
    notify.kick()  # новые лоты - сразу проход уведомлений по сохранённым поискам
    return {"imported": imported, "left_source": hidden}


# ---------- сохранённые поиски и уведомления (searches.py, notify.py) ----------

class SearchPayload(BaseModel):
    params: dict | None = None
    name: str | None = None
    notify: bool | None = None


class NotifySettingsPayload(BaseModel):
    tg: bool | None = None
    fav_events: bool | None = None
    email_on: bool | None = None


class EmailPayload(BaseModel):
    email: str


def _searches_user(authorization):
    uid = current_user(authorization)
    if not searches.enabled_for(uid):
        raise HTTPException(status_code=404)
    return uid


def _searches_state(uid):
    return {"items": searches.list_for(uid), "limit": searches.MAX_PER_USER, "pro": searches.can_create(uid),
            "settings": notify.settings(uid)}


@app.get("/api/searches")
def api_searches(authorization: str = Header(default="")):
    return _searches_state(_searches_user(authorization))


@app.get("/api/searches/preview")
def api_search_preview(request: Request, authorization: str = Header(default="")):
    _searches_user(authorization)
    return searches.preview(dict(request.query_params))


@app.post("/api/searches/{search_id}/open")
def api_search_open(search_id: int, authorization: str = Header(default="")):
    """Пользователь открыл поиск: его «новые» лоты становятся просмотренными."""
    uid = _searches_user(authorization)
    if not searches.mark_opened(uid, search_id, _now_iso()):
        raise HTTPException(status_code=404, detail="поиск не найден")
    return {"ok": True}


@app.post("/api/searches")
def api_search_create(payload: SearchPayload, authorization: str = Header(default="")):
    uid = _searches_user(authorization)
    if not searches.can_create(uid):
        raise HTTPException(status_code=403, detail="Сохранённые поиски - в HonestLot Pro")
    try:
        sid = searches.create(uid, payload.params or {}, _now_iso(), payload.name, payload.notify is not False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    notify.touch_pass(uid, _now_iso())
    db.log_event(uid, "search_save", _now_iso())
    return {"id": sid, **_searches_state(uid)}


@app.patch("/api/searches/{search_id}")
def api_search_update(search_id: int, payload: SearchPayload, authorization: str = Header(default="")):
    uid = _searches_user(authorization)
    try:
        searches.update(uid, search_id, _now_iso(), name=payload.name, params=payload.params, notify=payload.notify)
    except KeyError:
        raise HTTPException(status_code=404, detail="поиск не найден")
    return _searches_state(uid)


@app.delete("/api/searches/{search_id}")
def api_search_delete(search_id: int, authorization: str = Header(default="")):
    uid = _searches_user(authorization)
    if not searches.delete(uid, search_id):
        raise HTTPException(status_code=404, detail="поиск не найден")
    return _searches_state(uid)


@app.get("/api/notify/settings")
def api_notify_settings(authorization: str = Header(default="")):
    return notify.settings(_searches_user(authorization))


@app.post("/api/notify/settings")
def api_notify_settings_set(payload: NotifySettingsPayload, authorization: str = Header(default="")):
    uid = _searches_user(authorization)
    if payload.tg is not None:
        notify.set_tg(uid, payload.tg, _now_iso())
    if payload.fav_events is not None:
        notify.set_fav_events(uid, payload.fav_events, _now_iso())
    if payload.email_on is not None:
        notify.set_email_on(uid, payload.email_on, _now_iso())
    return notify.settings(uid)


@app.post("/api/notify/email")
def api_notify_email(payload: EmailPayload, authorization: str = Header(default="")):
    uid = _searches_user(authorization)
    try:
        status = notify.request_email(uid, payload.email, _now_iso())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": status, **notify.settings(uid)}


@app.get("/notify/confirm", response_class=HTMLResponse)
def notify_confirm(t: str = ""):
    if notify.confirm(t, _now_iso()) is None:
        return HTMLResponse(site.message_page("Ссылка устарела", "Откройте HonestLot и укажите почту для "
                                              "уведомлений ещё раз - придёт новая ссылка."), status_code=400)
    return site.message_page("Почта подтверждена", "Раз в день сюда будут приходить новые лоты по "
                             "сохранённым поискам и изменения в избранном. Отписаться можно по ссылке в письме.")


@app.get("/notify/unsubscribe", response_class=HTMLResponse)
def notify_unsubscribe_page(t: str = ""):
    return site.message_page("Отписаться от писем HonestLot", "Письма с новыми лотами и изменениями в "
                             "избранном перестанут приходить. Уведомления в Telegram это не отключит.",
                             form_button="Отписаться")


@app.post("/notify/unsubscribe", response_class=HTMLResponse)
def notify_unsubscribe(t: str = ""):
    if notify.unsubscribe(t, _now_iso()) is None:
        return HTMLResponse(site.message_page("Ссылка не подошла", "Отключить письма можно в HonestLot: "
                                              "«Поиски» → «Уведомления»."), status_code=400)
    return site.message_page("Письма отключены", "Включить их снова можно в HonestLot: «Поиски» → «Уведомления».")


@app.get("/img")
def img(u: str = ""):
    """Фото МЭТС и других площадок из etp_lots.PROXY_PHOTO_HOSTS - через сервер (imgproxy.py)."""
    try:
        path = imgproxy.get(u)
    except imgproxy.Refused:
        raise HTTPException(status_code=404, detail="нет такого фото")
    except Exception as e:  # площадка не отдала фото
        raise HTTPException(status_code=502, detail=f"фото не загрузилось: {type(e).__name__}")
    return FileResponse(path, media_type=imgproxy.media_type(u),
                        headers={"Cache-Control": f"public, max-age={imgproxy.BROWSER_CACHE_SECONDS}"})


@app.get("/docimg/{name}")
def docimg(name: str):
    """Фото машины, вынутое из документов торгов ЦДТ (docphotos.py) и сохранённое у нас."""
    path = docphotos.path(name)
    if not path:
        raise HTTPException(status_code=404, detail="нет такого фото")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=2592000"})


@app.get("/api/stats/photos")
def api_photo_stats(x_import_token: str = Header(default="")):
    """Сколько лотов ленты с какими фото (lots.photo_sources) - для еженедельной сводки с ПК."""
    _check_import_token(x_import_token)
    return lots.photo_sources()


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
    # веб-версия закрыта от поисковиков (решение владельца 13.10.2026): лоты живут недолго,
    # а в поиске должны быть страницы сайта (/pro, оферта), а не лента
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"),
                        headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex, nofollow"})


# Страницы оплаты (frontend/pay/) - только когда оплата включена (billing.enabled).
@app.get("/pay")
def pay_root():
    # без "/" на конце относительные ссылки страниц (pay.css, pay.js) ведут мимо папки
    if not billing.enabled():
        raise HTTPException(status_code=404)
    return RedirectResponse("/pay/", status_code=301)


@app.get("/pay/")
@app.get("/pay/{name}")
def pay_page(name: str = "index.html"):
    path = os.path.join(FRONTEND_DIR, "pay", os.path.basename(name))
    if not billing.enabled() or not os.path.isfile(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"} if path.endswith(".html") else None)


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
