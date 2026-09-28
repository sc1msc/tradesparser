# -*- coding: utf-8 -*-
r"""
Единая точка входа для всего конвейера сбора/донаполнения/пересборки
данных - вместо того, чтобы помнить и вручную соблюдать порядок из восьми
скриптов, запускается один: python run_pipeline.py

Шаги (строго в этом порядке - порядок важен, см. ниже):
  1) main.py                    - сбор новых лотов + удаление истёкших
  2) fill_missing_mileage.py    - доливка пробега через TRONK (платно)
  3) build_lots_processed.py    - пересборка lots_processed из lots
  4) fill_missing_from_title.py - доливка brand/name/year из текста title
  5) build_lots_current_month.py- пересборка lots_current_month
  6) evaluate_autoru_browser.py - оценка через Авто.ру (браузер)
  7) build_lot_selections.py    - пересборка тематических подборок
  8) export_to_miniapp.py       - выгрузка лотов на сервер мини-аппа honestlot
                                  (не роняет пайплайн, если сервер недоступен)

Почему именно такой порядок и зачем он единым скриптом:
  - шаг 4 обязан идти МЕЖДУ шагом 3 и шагом 5: build_lots_processed.py
    (шаг 3) при каждом запуске полностью перезаписывает lots_processed
    из lots "с нуля" и не переносит то, что туда дописал шаг 4 - если
    между ними случайно запустить шаг 3 повторно, ручное/эвристическое
    donaполнение brand/name/year будет молча стёрто. Внутри одного
    прогона этого скрипта такое невозможно в принципе.
  - шаг 6 (evaluate_autoru_browser.py) читает mileage_km из
    lots_current_month, а не из lots - значит он обязан идти ПОСЛЕ
    шагов 2/3/5 (доливка пробега -> lots -> lots_processed ->
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
запрос к TRONK; шаг 6, запуск браузера) сохраняют собственные
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
import fill_missing_from_title
import fill_missing_mileage
import export_to_miniapp
import main

STEPS = [
    ("Сбор новых лотов + удаление истёкших", main),
    ("Доливка пробега через TRONK (платно)", fill_missing_mileage),
    ("Пересборка lots_processed", build_lots_processed),
    ("Доливка brand/name/year из title", fill_missing_from_title),
    ("Пересборка lots_current_month", build_lots_current_month),
    ("Оценка через Авто.ру (браузер)", evaluate_autoru_browser),
    ("Пересборка тематических подборок", build_lot_selections),
    ("Выгрузка в мини-апп honestlot", export_to_miniapp),  # закомментировать, чтобы не выгружать
]


def run():
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
            raise

    print(f"\n{'=' * 60}")
    print("Готово. Все шаги конвейера выполнены.")
    print("Данные готовы - для публикации в Telegram запустите отдельно: python send_digest.py")
    print("=" * 60)


if __name__ == "__main__":
    run()
