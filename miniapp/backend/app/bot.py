# -*- coding: utf-8 -*-
r"""
Бот @honestlot_bot: отдельный процесс (сервис bot в docker-compose), который
сам забирает сообщения из Telegram (long polling, getUpdates) через релей -
см. telegram.py. Вебхук не нужен: соединения идут только с сервера наружу.

Что умеет сейчас: на любое личное сообщение (в том числе /start) -
приветствие с кнопкой, которая открывает мини-апп. Не всем очевидно, что лоты
открываются маленькой кнопкой меню слева от поля ввода.

Дальше сюда же - ответ на pre_checkout_query при оплате (за 10 секунд, иначе
Telegram отменит платёж) и команды для уведомлений.

Запуск: python -m app.bot (в контейнере - командой сервиса bot).
Журнал: docker compose logs -f bot. Тексты сообщений и данные пользователей в
журнал не пишем.
"""
import logging
import os
import time

from . import telegram

log = logging.getLogger("honestlot.bot")

WELCOME = (
    "👋 Это HonestLot — выгодные машины с банкротных торгов в Москве и МО.\n\n"
    "Нажмите «Открыть лоты» ниже или кнопку «Лоты» слева от поля ввода сообщения.\n\n"
    "Внутри: цена против рыночной оценки, дедлайн подачи заявки, график снижения цены, "
    "фильтры и избранное."
)
BUTTON = "Открыть лоты"
POLL_TIMEOUT = 50          # секунд держит запрос getUpdates, если новых сообщений нет
MAX_RETRY_DELAY = 300      # пауза между повторами при ошибках растёт до 5 минут


def app_url():
    domain = os.environ.get("DOMAIN", "").split(",")[0].strip()
    return f"https://{domain}" if domain else None


def reply(update):
    """Update от Telegram -> (метод, параметры) ответа или None, если молчим."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or "text" not in msg:
        return None  # группы, каналы, стикеры и прочее - молчим
    params = {"chat_id": chat["id"], "text": WELCOME}
    url = app_url()
    if url:
        params["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON, "web_app": {"url": url}}]]}
    return "sendMessage", params


def connect():
    """Ждём, пока Telegram станет доступен; снимаем вебхук (с ним getUpdates не работает)."""
    delay = 5
    while True:
        try:
            me = telegram.call("getMe")
            telegram.call("deleteWebhook")
            return me
        except telegram.TelegramError as e:
            log.warning("Нет связи с Telegram (%s), повтор через %s с", e, delay)
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    me = connect()
    log.info("Бот @%s слушает Telegram через %s", me.get("username"), telegram.api_base())
    offset, delay = None, 5
    while True:
        params = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = telegram.call("getUpdates", http_timeout=POLL_TIMEOUT + 15, **params)
            delay = 5
        except telegram.TelegramError as e:
            wait = e.retry_after or delay
            log.warning("getUpdates: %s, повтор через %s с", e, wait)
            time.sleep(wait)
            delay = min(delay * 2, MAX_RETRY_DELAY)
            continue
        for update in updates:
            # Сдвигаем offset до обработки: апдейт, на котором падаем, не должен
            # приходить снова и снова.
            offset = update["update_id"] + 1
            try:
                answer = reply(update)
                if answer:
                    telegram.call(answer[0], **answer[1])
            except telegram.TelegramError as e:
                log.warning("Ответ на апдейт %s не отправлен: %s", update["update_id"], e)
            except Exception:
                log.exception("Ошибка при обработке апдейта %s", update["update_id"])


if __name__ == "__main__":
    run()
