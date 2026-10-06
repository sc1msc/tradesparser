# -*- coding: utf-8 -*-
r"""
Единая точка входа для всего конвейера сбора/донаполнения/пересборки
данных - вместо того, чтобы помнить и вручную соблюдать порядок из семи
скриптов, запускается один: python run_pipeline.py

Шаги (строго в этом порядке - порядок важен, см. ниже):
  1) main.py                    - сбор новых лотов + удаление истёкших
  2) fill_missing_mileage.py    - доливка пробега через TRONK (платно)
  3) build_lots_processed.py    - пересборка lots_processed из lots (и там
                                  же доливка brand/name/year из текста title,
                                  см. fill_missing_from_title.fill_rows)
  4) build_lots_current_month.py- пересборка lots_current_month
  5) evaluate_autoru_browser.py - оценка через Авто.ру (браузер)
  6) build_lot_selections.py    - пересборка тематических подборок
  7) export_to_miniapp.py       - выгрузка лотов на сервер мини-аппа honestlot
                                  (не роняет пайплайн, если сервер недоступен)

Почему именно такой порядок и зачем он единым скриптом:
  - доливка brand/name/year из title раньше была отдельным шагом между
    шагами 3 и 4, и отдельный запуск build_lots_processed.py молча стирал
    её результат (29.09 так и случилось). Теперь она внутри шага 3 -
    порядок нарушить нельзя.
  - шаг 5 (evaluate_autoru_browser.py) читает mileage_km из
    lots_current_month, а не из lots - значит он обязан идти ПОСЛЕ
    шагов 2/3/4 (доливка пробега -> lots -> lots_processed ->
    lots_current_month), иначе увидит пустой/устаревший пробег и
    посчитает его по грубой формуле (год выпуска) вместо настоящего
    значения. Строгий порядок в этом файле устраняет этот риск.
  - evaluate_tronk.py и evaluate_avito_browser.py сюда сознательно не
    включены: их результат (tronk_price_*, avito_price_*) сейчас нигде
    дальше по пайплайну не читается (единственная используемая рыночная
    оценка - autoru_price_low/high). Остаются отдельными ручными
    инструментами на случай, если понадобится сверка.
  - send_digest.py тоже не включён - это отдельное осознанное действие
    "опубликовать": там свой интерактивный выбор подборки, его нет
    смысла звать автоматически при каждой сборке данных.

Платные и требующие интерактивного подтверждения шаги (сейчас - шаг 2,
запрос к TRONK; шаг 5, запуск браузера) сохраняют собственные
подтверждения ("yes"/"да") - этот скрипт их не обходит и не дублирует.
Если на любом шаге отказаться от подтверждения - тот шаг просто ничего
не сделает и выполнение продолжится дальше по цепочке.

Каждый шаг можно по-прежнему запускать отдельно (python main.py и т.д.) -
этот файл не заменяет, а лишь вызывает их run() по очереди.
"""
import datetime
import glob
import json
import os
import sys
import time
import traceback

import automation
import build_lot_selections
import build_lots_current_month
import build_lots_processed
import config
import evaluate_autoru_browser
import expenses
import fill_missing_mileage
import export_to_miniapp
import main

STEPS = [
    ("Сбор новых лотов + удаление истёкших", main),
    ("Доливка пробега через TRONK (платно)", fill_missing_mileage),
    ("Пересборка lots_processed", build_lots_processed),
    ("Пересборка lots_current_month", build_lots_current_month),
    ("Оценка через Авто.ру (браузер)", evaluate_autoru_browser),
    ("Пересборка тематических подборок", build_lot_selections),
    ("Выгрузка в мини-апп honestlot", export_to_miniapp),  # закомментировать, чтобы не выгружать
]

# Автоматический режим (--auto, см. automation.py): логи, история прогонов,
# защита от двух одновременных запусков.
LOG_DIR = "logs"
LOCK_FILE = os.path.join(LOG_DIR, "pipeline.lock")
RUNS_FILE = os.path.join(LOG_DIR, "runs.jsonl")          # строка на прогон - для еженедельной сводки
SUMMARY_FILE = os.path.join(LOG_DIR, "last_summary.txt")  # когда последний раз слали сводку
LOCK_STALE_HOURS = 8  # прогон дольше - считаем, что он завис, и лок не уважаем


def _expenses_start():
    """Учёт расходов (expenses.py): постоянные расходы месяца и снимок баланса
    TRONK. Ошибки учёта пайплайн не останавливают."""
    try:
        expenses.ensure_fixed_costs()
        bal = expenses.snapshot_tronk_balance()
        if bal is not None:
            print(f"Баланс TRONK: {bal:.2f} руб.")
    except Exception as e:
        print(f"Учёт расходов: {e}")


def _expenses_end():
    try:
        expenses.build_report()
        print(expenses.summary_text())
        low = expenses.low_balance_text()
        if low:
            automation.alert(low)
    except Exception as e:
        print(f"Учёт расходов: не удалось собрать сводку ({e})")


def run():
    _expenses_start()
    total = len(STEPS)
    for i, (title, module) in enumerate(STEPS, start=1):
        print(f"\n{'=' * 60}")
        print(f"Шаг {i}/{total}: {title} ({module.__name__}.py)")
        print("=" * 60)
        try:
            module.run()
        except Exception as e:
            print(f"\nШаг {i}/{total} ({module.__name__}.py) упал с ошибкой: {e}")
            print("Дальнейшие шаги не выполняются.")
            automation.alert(f"Упал шаг {i}/{total} ({module.__name__}.py): {e}. Дальнейшие шаги не выполнены.")
            _expenses_end()
            raise

    print(f"\n{'=' * 60}")
    print("Готово. Все шаги конвейера выполнены.")
    _expenses_end()
    print("Данные готовы - для публикации в Telegram запустите отдельно: python send_digest.py")
    print("=" * 60)


# ---------- автоматический режим ----------

class _Tee:
    """Печать и в консоль, и в файл лога прогона."""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text):
        for out in (self.stream, self.log):
            try:
                out.write(text)
                out.flush()
            except (OSError, ValueError, UnicodeEncodeError, AttributeError):
                pass
        return len(text)

    def flush(self):
        pass


def _take_lock():
    """-> True, если можно запускаться (другой прогон не идёт)."""
    if os.path.exists(LOCK_FILE) and time.time() - os.path.getmtime(LOCK_FILE) < LOCK_STALE_HOURS * 3600:
        return False
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {datetime.datetime.now().isoformat(timespec='seconds')}\n")
    return True


def _cleanup_logs():
    cutoff = time.time() - config.PIPELINE_LOG_DAYS * 86400
    for path in glob.glob(os.path.join(LOG_DIR, "pipeline-*.log")):
        if os.path.getmtime(path) < cutoff:
            os.remove(path)


def _weekly_summary(now):
    """Сводка раз в config.PIPELINE_SUMMARY_DAYS дней: прогоны и траты. -> текст или None."""
    try:
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            last = datetime.datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        last = None
    if last and now - last < datetime.timedelta(days=config.PIPELINE_SUMMARY_DAYS):
        return None
    since = now - datetime.timedelta(days=config.PIPELINE_SUMMARY_DAYS)
    runs = []
    if os.path.exists(RUNS_FILE):
        with open(RUNS_FILE, encoding="utf-8") as f:
            runs = [r for r in map(json.loads, f) if datetime.datetime.fromisoformat(r["started"]) >= since]
    ok = sum(1 for r in runs if r["ok"] and not r["alerts"])
    days = len({datetime.datetime.fromisoformat(r["started"]).date() for r in runs})
    lines = [f"HonestLot: сводка за {config.PIPELINE_SUMMARY_DAYS} дн.",
             f"Прогонов: {len(runs)} (дней с прогоном: {days} из {config.PIPELINE_SUMMARY_DAYS}), без проблем: {ok}."]
    try:
        rows = expenses._rows()
        spent = sum(r["_amount"] for r in expenses._spends(rows) if r["_when"] >= since and r["вид"] == expenses.KIND_SPEND)
        lines.append(f"Потрачено на API за неделю: {spent:.0f} руб. "
                     f"(TRONK за месяц: {expenses.month_spent('TRONK', now):.0f} из {config.TRONK_MONTHLY_BUDGET_RUB} руб.)")
        bal = expenses.last_tronk_balance(rows)
        if bal is not None:
            lines.append(f"Баланс TRONK: {bal:.0f} руб.")
    except Exception as e:
        lines.append(f"(учёт расходов недоступен: {e})")
    return "\n".join(lines)


def run_auto():
    """run() без вопросов, с логом в logs/ и уведомлением в Telegram, если что-то не так."""
    automation.AUTO = True
    os.makedirs(LOG_DIR, exist_ok=True)
    started = datetime.datetime.now()
    if not _take_lock():
        print(f"Предыдущий прогон ещё идёт ({LOCK_FILE}) - выхожу.")
        return
    log_path = os.path.join(LOG_DIR, f"pipeline-{started:%Y-%m-%d_%H%M}.log")
    log = open(log_path, "w", encoding="utf-8")
    sys.stdout, sys.stderr = _Tee(sys.__stdout__, log), _Tee(sys.__stderr__, log)
    ok = True
    try:
        print(f"Автоматический прогон {started:%d.%m.%Y %H:%M}, лог: {os.path.abspath(log_path)}")
        run()
    except Exception:
        ok = False
        traceback.print_exc()
    finally:
        minutes = (datetime.datetime.now() - started).total_seconds() / 60
        problems = automation.alerts()
        try:
            with open(RUNS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"started": started.isoformat(timespec="seconds"), "ok": ok,
                                    "minutes": round(minutes, 1), "alerts": problems}, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"История прогонов не записана: {e}")
        if problems:
            head = f"HonestLot: прогон {started:%d.%m %H:%M} - " + ("с проблемами" if ok else "УПАЛ")
            automation.send_telegram(head + "\n\n" + "\n".join(f"• {p}" for p in problems)
                                     + f"\n\nЛог: {os.path.abspath(log_path)}")
        summary = _weekly_summary(datetime.datetime.now())
        if summary and automation.send_telegram(summary):
            with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
                f.write(datetime.datetime.now().isoformat(timespec="seconds"))
        _cleanup_logs()
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        log.close()
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    if "--test-notify" in sys.argv:  # проверка уведомлений, без прогона
        print("отправлено" if automation.send_telegram(
            "HonestLot: проверка уведомлений. Сюда будут приходить сообщения, если автоматический "
            "прогон упал или упёрся в лимит, и раз в неделю - короткая сводка.") else "не отправлено")
    elif "--auto" in sys.argv:
        run_auto()
    else:
        run()
