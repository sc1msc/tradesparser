# -*- coding: utf-8 -*-
r"""
Сторож выгрузок: если с ПК давно не было выгрузки лотов (POST /api/import),
сервер сам пишет администратору в Telegram.

Зачем. Уведомления пайплайна (automation.py на ПК) шлёт сам прогон - и
только если прогон вообще запустился и дошёл до конца. ПК выключен, сломалось
окружение .venv, отключена задача Планировщика, Python упал до отправки -
сообщений нет, а мини-апп тихо показывает устаревшие лоты. Сервер это видит
по своей базе: время последней выгрузки - самое свежее updated_at лота (его
ставит только импорт).

Как. Фоновый поток в процессе api (как backup.py; у сервиса bot базы нет)
раз в CHECK_EVERY_SECONDS смотрит, сколько часов назад была выгрузка.
Больше STALE_HOURS (прогон раз в сутки: пропущен один и прошло ещё полдня) -
сообщение в HONESTLOT_ADMIN_CHAT_ID через бота уведомлений (telegram.py,
через релей; см. _send); пока выгрузки нет - напоминание раз в REPEAT_HOURS; выгрузка
пришла - одно сообщение об этом. Не отправилось (релей, Telegram) -
повтор при следующей проверке. Состояние - в памяти: после перезапуска
сервера напоминание может прийти раньше срока, это не страшно.

Тот же поток раз в месяц присылает сводку по справочнику марок и моделей (catalog.monthly_check).

Без HONESTLOT_ADMIN_CHAT_ID в .env сторож выключен (так и при локальном
запуске на ПК). Получатель должен хотя бы раз нажать "Старт" у бота уведомлений.
Пайплайн остановлен нарочно (отпуск) - убрать переменную из .env и
перезапустить api, иначе напоминания будут приходить каждый день.
"""
import datetime
import os
import threading
import time

from . import db, telegram

STALE_HOURS = 36
REPEAT_HOURS = 24
CHECK_EVERY_SECONDS = 3600
MSK = datetime.timezone(datetime.timedelta(hours=3))

_state = {"alerted_at": None}  # когда последний раз писали "выгрузки нет"


def admin_chat_id():
    return os.environ.get("HONESTLOT_ADMIN_CHAT_ID", "").strip()


def last_import():
    """Время последней выгрузки (самое свежее updated_at лота) или None."""
    row = db.conn().execute("SELECT MAX(updated_at) FROM lots").fetchone()
    try:
        dt = datetime.datetime.fromisoformat(row[0])
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MSK)


def _send(chat_id, text):
    """Сообщение администратору. Все уведомления - сторожа, проверки статусов, сбора лотов с
    площадок и пайплайна с ПК (POST /api/notify) - идут через отдельного бота уведомлений
    (HONESTLOT_NOTIFY_BOT_TOKEN, решение владельца 16.10.2026), чтобы не смешиваться с ботом
    пользователей. Без этой переменной - через @honestlot_bot, как раньше."""
    telegram.call("sendMessage", bot_token=os.environ.get("HONESTLOT_NOTIFY_BOT_TOKEN", "").strip() or None,
                  chat_id=chat_id, text=text, disable_web_page_preview=True)


def check(now=None, send=_send):
    """Одна проверка. -> текст отправленного сообщения или None. Ошибка
    отправки (TelegramError) пробрасывается, состояние не меняется -
    следующая проверка попробует снова."""
    chat_id = admin_chat_id()
    if not chat_id:
        return None
    last = last_import()
    if last is None:
        return None  # лотов в базе нет - выгрузок ещё не было, сторожить нечего
    now = now or datetime.datetime.now(MSK)
    hours = (now - last).total_seconds() / 3600
    alerted = _state["alerted_at"]
    when = last.astimezone(MSK).strftime("%d.%m %H:%M")
    if hours > STALE_HOURS:
        if alerted is not None and now - alerted < datetime.timedelta(hours=REPEAT_HOURS):
            return None
        text = (f"HonestLot: выгрузки лотов с ПК не было {hours:.0f} ч (последняя - {when} МСК), "
                f"мини-апп показывает устаревшие данные.\n\nПроверьте ПК: включён ли, работает ли задача "
                f"Планировщика \\HonestLot\\Pipeline, что в logs/ последнего прогона.")
        send(chat_id, text)
        _state["alerted_at"] = now
        return text
    if alerted is not None:
        text = f"HonestLot: выгрузка с ПК снова пришла ({when} МСК)."
        send(chat_id, text)
        _state["alerted_at"] = None
        return text
    return None


def _loop():
    from . import catalog  # здесь: catalog импортирует watchdog
    while True:
        try:
            if check():
                print("Сторож выгрузок: сообщение администратору отправлено", flush=True)
        except Exception as e:  # сторож не должен ронять приложение
            print(f"Сторож выгрузок: проверка не удалась: {e}", flush=True)
        try:  # раз в месяц - сводка по справочнику марок и моделей (catalog.py)
            if catalog.monthly_check():
                print("Проверка справочника: сводка администратору отправлена", flush=True)
        except Exception as e:
            print(f"Проверка справочника не удалась: {e}", flush=True)
        time.sleep(CHECK_EVERY_SECONDS)


def start():
    if not admin_chat_id():
        print("Сторож выгрузок выключен: нет HONESTLOT_ADMIN_CHAT_ID", flush=True)
        return
    threading.Thread(target=_loop, name="import-watchdog", daemon=True).start()
