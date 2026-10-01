# -*- coding: utf-8 -*-
r"""
Ответы бота @honestlot_bot на сообщения - через вебхук, без исходящих
запросов к Telegram.

Почему так. С сервера в Yandex Cloud не проходят соединения к
api.telegram.org (проверено 30.09.2026), поэтому обычная схема "сервер сам
вызывает sendMessage" не работает. Но Telegram позволяет ответить прямо в
теле ответа на вебхук: сервер возвращает JSON {"method": "sendMessage",
...}, и Telegram выполняет его сам. Исходящих соединений не нужно.
Вебхук включает и проверяет скрипт с ПК (miniapp/set_webhook.py): там
Telegram доступен.

Защита: Telegram присылает заголовок X-Telegram-Bot-Api-Secret-Token со
значением, заданным при setWebhook (переменная окружения
HONESTLOT_WEBHOOK_SECRET). Запросы без него отклоняются.

Что умеет: на любое личное сообщение (в том числе /start) - приветствие с
кнопкой, которая открывает мини-апп. Не всем очевидно, что лоты открываются
маленькой кнопкой меню слева от поля ввода.
"""
import hmac
import os

WELCOME = (
    "👋 Это HonestLot — выгодные машины с банкротных торгов в Москве и МО.\n\n"
    "Нажмите «Открыть лоты» ниже или кнопку «Лоты» слева от поля ввода сообщения.\n\n"
    "Внутри: цена против рыночной оценки, дедлайн подачи заявки, график снижения цены, "
    "фильтры и избранное."
)
BUTTON = "Открыть лоты"


def secret_ok(header_value):
    expected = os.environ.get("HONESTLOT_WEBHOOK_SECRET", "")
    return bool(expected) and hmac.compare_digest(expected, header_value or "")


def app_url():
    domain = os.environ.get("DOMAIN", "").split(",")[0].strip()
    return f"https://{domain}" if domain else None


def reply(update):
    """Update от Telegram -> метод Bot API для ответа в теле вебхука или None."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or "text" not in msg:
        return None  # группы, каналы, стикеры и прочее - молчим
    answer = {"method": "sendMessage", "chat_id": chat["id"], "text": WELCOME}
    url = app_url()
    if url:
        answer["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON, "web_app": {"url": url}}]]}
    return answer
