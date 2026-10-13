# -*- coding: utf-8 -*-
r"""
Авторизация пользователя мини-аппа - по Telegram initData, без логинов.

Telegram, открывая мини-апп, передаёт ему строку initData (данные
пользователя + auth_date + hash). Фронт шлёт её в каждом запросе в
заголовке "Authorization: tma <initData>". Бэкенд проверяет подпись
токеном бота (алгоритм - https://core.telegram.org/bots/webapps
#validating-data-received-via-the-mini-app):
    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
где data_check_string - все поля кроме hash, "key=value", отсортированные
по ключу и склеенные через "\n". Подделать initData без токена бота нельзя,
поэтому telegram_id из него можно считать подлинным.

ВЕБ-ВЕРСИЯ (honestlot.ru в обычном браузере, с 13.10.2026). initData там нет,
поэтому пользователь входит через Telegram Login Widget (validate_login_widget),
а сервер выдаёт свой токен входа (make_web_token) на WEB_TOKEN_DAYS дней:
подпись виджета действует сутки (LOGIN_MAX_AGE_SECONDS), входить каждый день
неудобно. Токен - "<base64 json>.<HMAC>", в нём telegram_id, username и имя
(touch_user перезаписывает их при каждом запросе - без них они бы стёрлись) и
срок. Ключ подписи - HONESTLOT_WEB_SECRET или производный от токена бота
(смена токена бота разлогинит веб-пользователей). Заголовок -
"Authorization: web <токен>". Пользователь тот же, что в мини-аппе: избранное общее.

Локальная разработка в обычном браузере (без Telegram): если задана
переменная окружения HONESTLOT_DEV_USER_ID, запросы БЕЗ initData
считаются запросами этого пользователя. На сервере её не задаём.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl

# initData подписан один раз при открытии мини-аппа и не обновляется, пока
# оно открыто - поэтому срок жизни щедрый, а не минуты.
MAX_AGE_SECONDS = 7 * 24 * 3600


START_PARAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AuthError(Exception):
    pass


def validate_init_data(init_data, bot_token, now=None):
    """Возвращает dict пользователя Telegram (id, username, first_name, ...)
    или бросает AuthError."""
    if not init_data:
        raise AuthError("нет initData")
    if not bot_token:
        raise AuthError("на сервере не задан токен бота")
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise AuthError("в initData нет hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise AuthError("неверная подпись initData")
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise AuthError("неверный auth_date")
    if (now or time.time()) - auth_date > MAX_AGE_SECONDS:
        raise AuthError("initData устарел - переоткройте мини-апп")
    try:
        user = json.loads(fields.get("user") or "{}")
    except json.JSONDecodeError:
        raise AuthError("неверное поле user")
    if not isinstance(user, dict) or not user.get("id"):
        raise AuthError("в initData нет пользователя")
    # Метка источника из ссылки t.me/<бот>?startapp=<метка> - тоже под
    # подписью, подделать нельзя. Telegram разрешает A-Z a-z 0-9 _ -, до 64.
    start_param = fields.get("start_param") or ""
    user["start_param"] = start_param[:64] if START_PARAM_RE.match(start_param) else None
    return user


# Вход на сайте через Telegram Login Widget (страница оплаты honestlot.ru/pay,
# billing.py): другой алгоритм подписи, чем у initData мини-аппа -
#   secret_key = SHA256(bot_token), hash = hex(HMAC_SHA256(secret_key, data_check_string)).
# Виджет работает только на домене, заданном боту в @BotFather (/setdomain).
LOGIN_MAX_AGE_SECONDS = 24 * 3600


def validate_login_widget(data, bot_token, now=None):
    """data - поля, которые виджет передал в onauth (id, first_name, username,
    photo_url, auth_date, hash). -> dict пользователя или AuthError."""
    if not isinstance(data, dict) or not data.get("hash"):
        raise AuthError("нет данных входа через Telegram")
    if not bot_token:
        raise AuthError("на сервере не задан токен бота")
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(data["hash"])):
        raise AuthError("неверная подпись входа через Telegram")
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise AuthError("неверный auth_date")
    if (now or time.time()) - auth_date > LOGIN_MAX_AGE_SECONDS:
        raise AuthError("вход устарел - войдите через Telegram ещё раз")
    return {"id": int(fields["id"]), "username": fields.get("username"), "first_name": fields.get("first_name")}


# Ссылка "Поделиться" с экрана лота: t.me/<бот>?startapp=lot<id>_<код>.
# Код - users.ref_code того, кто поделился (случайный, а не telegram_id:
# ссылку видит каждый получатель). Без кода - тоже ссылка на лот.
SHARE_PARAM_RE = re.compile(r"^lot(\d{1,15})(?:_([a-z0-9]{4,12}))?$")
SHARE_SOURCE = "share"


def split_start_param(start_param):
    """(source, ref_code) из start_param: для ссылки на лот source = "share"
    (иначе у каждого лота была бы своя "метка" и сводка по источникам
    рассыпалась бы), ref_code - код поделившегося или None. Остальные
    метки возвращаются как есть."""
    m = SHARE_PARAM_RE.match(start_param or "")
    if not m:
        return start_param or None, None
    return SHARE_SOURCE, m.group(2)


def user_from_header(authorization):
    """Разбирает заголовок Authorization. Возвращает dict пользователя."""
    if authorization and authorization.lower().startswith("web "):
        return check_web_token(authorization[4:].strip())
    init_data = ""
    if authorization and authorization.lower().startswith("tma "):
        init_data = authorization[4:].strip()
    if not init_data:
        dev_id = os.environ.get("HONESTLOT_DEV_USER_ID")
        if dev_id:
            return {"id": int(dev_id), "username": "dev", "first_name": "Dev", "start_param": None}
    return validate_init_data(init_data, os.environ.get("HONESTLOT_BOT_TOKEN", ""))


# ---------- веб-версия: токен входа (см. докстринг модуля) ----------

WEB_TOKEN_DAYS = 30
WEB_SOURCE = "web"  # источник для новых пользователей, пришедших через сайт


def _web_secret():
    secret = os.environ.get("HONESTLOT_WEB_SECRET")
    if secret:
        return secret.encode()
    return hashlib.sha256(b"honestlot-web:" + os.environ.get("HONESTLOT_BOT_TOKEN", "").encode()).digest()


def _web_sign(body):
    return hmac.new(_web_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]


def make_web_token(user, now=None):
    """user - dict из validate_login_widget. -> токен входа веб-версии."""
    payload = {"id": int(user["id"]), "u": user.get("username"), "n": user.get("first_name"),
               "exp": int((now or time.time()) + WEB_TOKEN_DAYS * 86400)}
    body = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{body}.{_web_sign(body)}"


def check_web_token(token, now=None):
    """-> dict пользователя (как у initData) или AuthError."""
    body, _, sig = (token or "").partition(".")
    if not body or not sig or not hmac.compare_digest(_web_sign(body), sig):
        raise AuthError("войдите через Telegram")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        uid = int(payload["id"])
    except (ValueError, KeyError, TypeError):
        raise AuthError("войдите через Telegram")
    if (now or time.time()) > payload.get("exp", 0):
        raise AuthError("вход устарел - войдите через Telegram ещё раз")
    return {"id": uid, "username": payload.get("u"), "first_name": payload.get("n"), "start_param": WEB_SOURCE}
