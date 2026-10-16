# -*- coding: utf-8 -*-
r"""
Автоматический режим пайплайна: run_pipeline.py --auto (его запускает
Планировщик заданий Windows через run_pipeline_auto.bat).

Зачем. Пайплайн гоняется каждый день, а руками - лишняя работа: он сам
спрашивает "yes/да" перед платными шагами и запуском браузера. В
автоматическом режиме:
  - подтверждения проходят сами (confirm), но деньги ограничены: лимиты
    за запуск (config.*_MAX_PER_RUN) и месячный бюджет TRONK
    (config.TRONK_MONTHLY_BUDGET_RUB, траты - из учёта расходов expenses.py);
  - всё, на что раньше смотрел человек, копится в alerts(): упал шаг, кончился
    бюджет TRONK, мало денег на счету TRONK, Авто.ру просит капчу, сломан
    поиск агрегатора или сайт торгов не отвечает (main.CardFailures), сервер
    мини-аппа не принял выгрузку. В конце прогона,
    если что-то из этого было, - одно сообщение в Telegram (send_telegram).
    Всё прошло нормально - сообщения нет;
  - раз в неделю - короткая сводка (прогоны, траты), чтобы молчание бота
    не путать с тем, что прогоны просто не запускались (ПК был выключен).
    Прогон, который не запустился вовсе, отсюда не сообщить - это делает
    сервер мини-аппа (miniapp/backend/app/watchdog.py): нет выгрузки
    больше 36 часов - он пишет сам.

Куда пишем: бот config.TELEGRAM_BOT_TOKEN (служебный @honest_torgi_bot - не
публичный @honestlot_bot), получатель - config.NOTIFY_CHAT_ID (Telegram id,
в local_secrets.py). С ПК Telegram доступен; с ВМ в Yandex Cloud - нет
(блокировка провайдера), поэтому автозапуск - на ПК, а не на сервере.

Без --auto всё работает как раньше: confirm() спрашивает через input(),
alert() только печатает.
"""
import requests

import config

AUTO = False  # run_pipeline.py --auto ставит True
_alerts = []


def confirm(prompt):
    """Подтверждение перед платным/интерактивным шагом. В автоматическом
    режиме - "да" без вопроса (деньги ограничивают лимиты и бюджет)."""
    if AUTO:
        print(f"{prompt}yes (автоматический режим)")
        return True
    return input(prompt).strip().lower() in ("yes", "y", "да")


def alert(text):
    """Проблема, о которой надо сообщить человеку (в конце прогона - в Telegram)."""
    print(f"\n!!! {text}")
    _alerts.append(text)


def alerts():
    return list(_alerts)


def _hide_token(text):
    """Токен бота - часть адреса запроса и попадает в текст ошибки requests: в лог его не пишем."""
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "") or ""
    return text.replace(token, "<токен>") if len(token) > 10 else text


def send_via_server(text):
    """Через сервер мини-аппа (POST /api/notify) - он пересылает администратору ботом уведомлений
    через релей. Так уведомления доходят и без VPN: из России api.telegram.org закрыт, и с 11.10.2026
    до 16.10.2026 ни одно уведомление с ПК не дошло. -> True, если сервер отправил."""
    api_url = (getattr(config, "MINIAPP_API_URL", "") or "").rstrip("/")
    token = getattr(config, "MINIAPP_IMPORT_TOKEN", "")
    if not api_url or not token:
        return False
    try:
        r = requests.post(f"{api_url}/api/notify", json={"text": text[:4000]}, headers={"X-Import-Token": token},
                          timeout=30)
        if not r.ok:
            print(f"Уведомление через сервер не отправлено: {r.status_code} {r.text[:200]}")
        return r.ok
    except requests.RequestException as e:
        print(f"Уведомление через сервер не отправлено: {str(e)[:200]}")
        return False


def send_telegram(text):
    """Уведомление владельцу: сначала через сервер мини-аппа (send_via_server), не вышло - напрямую
    ботом config.TELEGRAM_BOT_TOKEN в config.NOTIFY_CHAT_ID (работает только с VPN). Ошибки
    печатаются, не бросаются: уведомление не должно ронять пайплайн. -> True, если отправлено."""
    if send_via_server(text):
        return True
    chat_id = getattr(config, "NOTIFY_CHAT_ID", None)
    if not chat_id or config.TELEGRAM_BOT_TOKEN.startswith("ВСТАВЬТЕ"):
        print("Уведомление не отправлено: нет TELEGRAM_BOT_TOKEN или NOTIFY_CHAT_ID в local_secrets.py")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
                          timeout=30)
        if not r.ok:
            print(f"Уведомление не отправлено: Telegram ответил {r.status_code} {_hide_token(r.text[:200])}")
        return r.ok
    except requests.RequestException as e:
        print(f"Уведомление не отправлено: {_hide_token(str(e))}")
        return False
