# -*- coding: utf-8 -*-
r"""
Вебхук бота @honestlot_bot: включить, проверить, выключить. Запускается с
ПК, а не с сервера: с сервера Telegram недоступен (см. backend/app/bot.py).

    python miniapp/set_webhook.py set     - включить вебхук на сервер мини-аппа
    python miniapp/set_webhook.py info    - состояние: адрес, очередь, последняя ошибка
    python miniapp/set_webhook.py delete  - выключить (бот снова молчит)

Нужно в local_secrets.py:
    MINIAPP_BOT_TOKEN      - токен @honestlot_bot (тот же, что HONESTLOT_BOT_TOKEN на сервере)
    MINIAPP_WEBHOOK_SECRET - тот же, что HONESTLOT_WEBHOOK_SECRET на сервере
    MINIAPP_API_URL        - адрес сервера (уже есть)

Вебхук доходит, только если Telegram может открыть соединение с сервером.
Исходящие соединения сервера к Telegram заблокированы - если блокировка
режет и ответы, getWebhookInfo покажет ошибку соединения (команда info).
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

API = "https://api.telegram.org/bot{token}/{method}"


def call(method, **params):
    token = getattr(config, "MINIAPP_BOT_TOKEN", "")
    if not token:
        sys.exit("В local_secrets.py не задан MINIAPP_BOT_TOKEN - токен @honestlot_bot.")
    resp = requests.post(API.format(token=token, method=method), json=params, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        sys.exit(f"Telegram ответил ошибкой: {data.get('description')}")
    return data.get("result")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "set":
        secret = getattr(config, "MINIAPP_WEBHOOK_SECRET", "")
        base = (config.MINIAPP_API_URL or "").rstrip("/")
        if not secret or not base:
            sys.exit("Нужны MINIAPP_WEBHOOK_SECRET и MINIAPP_API_URL в local_secrets.py.")
        call("setWebhook", url=f"{base}/api/telegram/webhook", secret_token=secret,
             allowed_updates=["message"], drop_pending_updates=True)
        print("Вебхук включён. Напишите боту /start и через минуту проверьте: python miniapp/set_webhook.py info")
    elif cmd == "delete":
        call("deleteWebhook")
        print("Вебхук выключен.")
    else:
        info = call("getWebhookInfo")
        print(f"Адрес: {info.get('url') or '(вебхук выключен)'}")
        print(f"Ждут доставки: {info.get('pending_update_count', 0)}")
        if info.get("last_error_message"):
            print(f"Последняя ошибка: {info['last_error_message']}")
        elif info.get("url"):
            print("Ошибок доставки нет.")


if __name__ == "__main__":
    main()
