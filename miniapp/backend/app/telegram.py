# -*- coding: utf-8 -*-
r"""
Вызовы Telegram Bot API с сервера - через релей за рубежом.

С ВМ в Yandex Cloud api.telegram.org недоступен (блокировка у провайдера в
обе стороны, проверено 30.09.2026). Запросы идут на релей - Caddy на VPS в
Амстердаме (relay/setup.sh в корне репозитория), который пускает только IP
этой ВМ и пересылает запросы в api.telegram.org как есть. Адрес релея - в
переменной окружения HONESTLOT_TELEGRAM_API (без неё - напрямую в Telegram,
так работает локальный запуск на ПК).

Только стандартная библиотека: отдельная зависимость ради пары POST-запросов
не нужна.
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_API = "https://api.telegram.org"


class TelegramError(Exception):
    """Ошибка Bot API или связи. В тексте никогда нет токена бота."""

    def __init__(self, description, error_code=None, retry_after=None):
        super().__init__(description)
        self.error_code = error_code
        self.retry_after = retry_after


def api_base():
    return (os.environ.get("HONESTLOT_TELEGRAM_API") or DEFAULT_API).rstrip("/")


def call(method, http_timeout=15, bot_token=None, **params):
    """Метод Bot API -> поле result ответа. Ошибки -> TelegramError.

    http_timeout - таймаут самого HTTP-запроса в секундах. Называется не timeout,
    потому что timeout - параметр Bot API (getUpdates). bot_token - другой бот
    (бот уведомлений, watchdog._send); без него - @honestlot_bot (HONESTLOT_BOT_TOKEN).
    """
    token = bot_token or os.environ.get("HONESTLOT_BOT_TOKEN", "")
    if not token:
        raise TelegramError("HONESTLOT_BOT_TOKEN не задан")
    req = urllib.request.Request(
        f"{api_base()}/bot{token}/{method}",
        data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)  # Telegram отвечает JSON и на ошибки (400, 401, 409, 429)
        except ValueError:
            hint = " - релей не пускает этот IP?" if e.code == 403 else ""
            raise TelegramError(f"HTTP {e.code} от {api_base()}{hint}", e.code) from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise TelegramError(f"нет связи с {api_base()}: {reason}") from None
    if not body.get("ok"):
        raise TelegramError(
            body.get("description") or "неизвестная ошибка",
            body.get("error_code"),
            (body.get("parameters") or {}).get("retry_after"),
        )
    return body["result"]
