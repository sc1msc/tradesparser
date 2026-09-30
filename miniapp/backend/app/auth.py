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

Локальная разработка в обычном браузере (без Telegram): если задана
переменная окружения HONESTLOT_DEV_USER_ID, запросы БЕЗ initData
считаются запросами этого пользователя. На сервере её не задаём.
"""
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


def user_from_header(authorization):
    """Разбирает заголовок Authorization. Возвращает dict пользователя."""
    init_data = ""
    if authorization and authorization.lower().startswith("tma "):
        init_data = authorization[4:].strip()
    if not init_data:
        dev_id = os.environ.get("HONESTLOT_DEV_USER_ID")
        if dev_id:
            return {"id": int(dev_id), "username": "dev", "first_name": "Dev", "start_param": None}
    return validate_init_data(init_data, os.environ.get("HONESTLOT_BOT_TOKEN", ""))
