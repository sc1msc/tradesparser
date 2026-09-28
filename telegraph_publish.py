# -*- coding: utf-8 -*-
r"""
Публикация страницы в Telegraph (встроенный в Telegram сервис статей -
открывается мгновенно внутри приложения, без своего хостинга).

Аккаунт создаётся один раз автоматически (анонимный, не привязан к
телеграм-аккаунту) и кэшируется в telegraph_token.txt рядом со скриптом -
при повторных запусках токен переиспользуется, новый аккаунт не плодится.
"""
import json
import os
import requests

TELEGRAPH_API = "https://api.telegra.ph"
TOKEN_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegraph_token.txt")


def get_or_create_account(short_name="TorgiAvto", author_name="Торги.Авто"):
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token

    resp = requests.post(
        f"{TELEGRAPH_API}/createAccount",
        data={"short_name": short_name, "author_name": author_name},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegraph createAccount вернул ошибку: {result}")

    token = result["result"]["access_token"]
    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def create_page(title, content_nodes, author_name="Торги.Авто"):
    """
    content_nodes - список узлов формата Telegraph (строки или
    {"tag":..., "attrs":..., "children":[...]}). Возвращает URL
    опубликованной страницы (https://telegra.ph/...).
    """
    token = get_or_create_account(author_name=author_name)
    resp = requests.post(
        f"{TELEGRAPH_API}/createPage",
        data={
            "access_token": token,
            "title": title,
            "author_name": author_name,
            "content": json.dumps(content_nodes, ensure_ascii=False),
            "return_content": "false",
        },
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegraph createPage вернул ошибку: {result}")
    return result["result"]["url"]
