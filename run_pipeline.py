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
import build_lot_selections
import build_lots_current_month
import build_lots_processed
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
            _expenses_end()
            raise

    print(f"\n{'=' * 60}")
    print("Готово. Все шаги конвейера выполнены.")
    _expenses_end()
    print("Данные готовы - для публикации в Telegram запустите отдельно: python send_digest.py")
    print("=" * 60)


if __name__ == "__main__":
    run()
