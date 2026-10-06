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
    поиск агрегатора, сервер мини-аппа не принял выгрузку. В конце прогона,
    если что-то из этого было, - одно сообщение в Telegram (send_telegram).
    Всё прошло нормально - сообщения нет;
  - раз в неделю - короткая сводка (прогоны, траты), чтобы молчание бота
    не путать с тем, что прогоны просто не запускались (ПК был выключен).

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


def send_telegram(text):
    """Сообщение в личку config.NOTIFY_CHAT_ID. Ошибки печатаются, не бросаются:
    уведомление не должно ронять пайплайн. -> True, если отправлено."""
    chat_id = getattr(config, "NOTIFY_CHAT_ID", None)
    if not chat_id or config.TELEGRAM_BOT_TOKEN.startswith("ВСТАВЬТЕ"):
        print("Уведомление не отправлено: нет TELEGRAM_BOT_TOKEN или NOTIFY_CHAT_ID в local_secrets.py")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
                          timeout=30)
        if not r.ok:
            print(f"Уведомление не отправлено: Telegram ответил {r.status_code} {r.text[:200]}")
        return r.ok
    except requests.RequestException as e:
        print(f"Уведомление не отправлено: {e}")
        return False
