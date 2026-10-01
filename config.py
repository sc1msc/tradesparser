# -*- coding: utf-8 -*-
"""Настройки бота. Правьте под себя."""

# --- Секреты (ключи API, токены, ID таблицы) - в local_secrets.py, который не хранится в git ---
# Шаблон: local_secrets.example.py. Если файла нет - подставляются заглушки
# "ВСТАВЬТЕ...", на которые уже проверяют скрипты TRONK.
try:
    from local_secrets import TRONK_API_KEY, TELEGRAM_BOT_TOKEN, SPREADSHEET_ID
except ImportError:
    TRONK_API_KEY = "ВСТАВЬТЕ_КЛЮЧ_TRONK"
    TELEGRAM_BOT_TOKEN = "ВСТАВЬТЕ_ТОКЕН_БОТА"
    SPREADSHEET_ID = "ВСТАВЬТЕ_ID_ТАБЛИЦЫ"

# Мини-апп honestlot (export_to_miniapp.py): адрес сервера и ключ импорта.
# Необязательные - если их нет в local_secrets.py, выгрузка в мини-апп
# просто пропускается.
try:
    from local_secrets import MINIAPP_API_URL, MINIAPP_IMPORT_TOKEN
except ImportError:
    MINIAPP_API_URL = ""
    MINIAPP_IMPORT_TOKEN = ""
# Бот мини-аппа (@honestlot_bot) - только для miniapp/set_webhook.py.
try:
    from local_secrets import MINIAPP_BOT_TOKEN, MINIAPP_WEBHOOK_SECRET
except ImportError:
    MINIAPP_BOT_TOKEN = ""
    MINIAPP_WEBHOOK_SECRET = ""

# --- Google Sheets ---
SERVICE_ACCOUNT_FILE = "service_account.json"   # путь к скачанному ключу
# SPREADSHEET_ID - в local_secrets.py (см. блок секретов выше)
WORKSHEET_NAME = "lots"                          # название листа (вкладки) внутри таблицы

# --- Фильтр поиска на сайте торгов ---
# categorie_childs[0]=2 -> "Легковой транспорт" (взято из вашего примера ссылки)
# regions[0]=50 -> Московская область, regions[1]=77 -> г. Москва
SEARCH_PARAMS = {
    "categorie_childs[0]": 2,
    "regions[0]": 50,
    "regions[1]": 77,
    "trades-section[0]": "bankrupt",
    "history_only": 0,
}
MAX_PAGES = 20          # сколько страниц поиска обходить за один запуск (защита от бесконечного цикла)

# Лоты, у которых приём заявок закончился этим числом дней назад (и раньше),
# удаляются из таблицы "lots" в начале каждого запуска main.py.
EXPIRED_LOT_DAYS = 3

# --- Задержки между запросами (в секундах), чтобы не долбить сайты слишком часто ---
DELAY_BETWEEN_LOT_REQUESTS = 2.0
DELAY_BETWEEN_SEARCH_PAGES = 2.0

# --- Обновление статуса и графика публичных предложений (main.py, шаг 4) ---
# Запросы к сайту бесплатные, но каждый - DELAY_BETWEEN_LOT_REQUESTS секунд
# (200 лотов ~ 7 минут). Не влезшие в лимит проверяются в следующий запуск
# (первыми - те, кого дольше всего не проверяли).
PUBLIC_OFFER_REFRESH_MAX_PER_RUN = 300
# Лот перечитывается, если с прошлой проверки агрегатор сделал ночное
# обновление (AGGREGATOR_NIGHTLY_UPDATE - чуть позже, чем оно обычно
# заканчивается: по updated_at карточек это ~04:00-04:20) или прошло больше
# PUBLIC_OFFER_REFRESH_HOURS часов (днём агрегатор тоже закрывает отдельные
# торги). Итого: первый запуск за день проверяет всё, повторный через пару
# часов - ничего, вечерний - всё ещё раз. См. main._status_is_fresh.
AGGREGATOR_NIGHTLY_UPDATE = "04:30"
PUBLIC_OFFER_REFRESH_HOURS = 8

# --- Доливка photo_url для уже собранных лотов (backfill_photo_urls.py) ---
PHOTO_BACKFILL_MAX_PER_RUN = 200

# --- Оценка через TRONK (data.tronk.info) - ПЛАТНЫЙ API ---
# Ключ доступа (TRONK_API_KEY) - в local_secrets.py, см. начало файла.
TRONK_REGION_ID = None   # необязательно; справочник регионов - метод offersregion
# Жёсткий лимит платных запросов за ОДИН запуск evaluate_tronk.py.
# Это единственная реальная защита от случайного слива бюджета - держите
# число небольшим и повышайте осознанно, когда убедитесь, что всё работает верно.
TRONK_MAX_PER_RUN = 10
DELAY_BETWEEN_TRONK_REQUESTS = 1.5

# --- Доливка пробега (fill_missing_mileage.py) - тоже ПЛАТНО, но методы ---
# --- специально под пробег и на порядок дешевле, чем полная оценка -------
# --- avgpricebyvin. См. tronk_mileage.py.
#   "probeg"  - ~1.10 руб/запрос, одно самое свежее показание
#   "probeg2" - ~2.10 руб/запрос, история из нескольких источников (точнее)
MILEAGE_METHOD = "probeg"
MILEAGE_MAX_PER_RUN = 1000
DELAY_BETWEEN_MILEAGE_REQUESTS = 0.5

# Средний годовой пробег, км. Используется в двух местах:
#   1) досчитать показание TRONK (probeg/probeg2) от его даты до сегодня
#      (fill_missing_mileage.py);
#   2) грубая оценка по году выпуска - ТОЛЬКО если пробега нет ни с
#      карточки лота, ни из TRONK (evaluate_autoru_browser.py,
#      evaluate_avito_browser.py).
ANNUAL_MILEAGE_KM = 16600

# --- Оценка на Авито через эмуляцию браузера (evaluate_avito_browser.py) ---
# Не деньги, но всё равно защита от бана: жёсткий лимит лотов за один запуск.
AVITO_BROWSER_MAX_PER_RUN = 15
DELAY_BETWEEN_AVITO_BROWSER_REQUESTS = 5.0
# headless=False настоятельно рекомендуется: реальное окно браузера выглядит
# заметно "человечнее" для антибота (Qrator), чем headless-режим. Держите
# False, пока не убедитесь, что headless тоже проходит без банов.
AVITO_BROWSER_HEADLESS = False

# --- Оценка на Авто.ру через эмуляцию браузера (evaluate_autoru_browser.py) ---
# Лотов немного, торопиться некуда - лучше медленнее, но надёжнее.
AUTORU_MAX_PER_RUN = 300
DELAY_BETWEEN_AUTORU_REQUESTS = 3.0
AUTORU_HEADLESS = False  # см. комментарий выше про Avito - та же логика

# --- Дайджест в Telegram-канал (send_digest.py) ---
# TELEGRAM_BOT_TOKEN - в local_secrets.py, см. начало файла.
TELEGRAM_CHANNEL_ID = "@honestlot"
DIGEST_TEASER_COUNT = 3   # сколько лотов реально уйдёт в канал
DIGEST_PHOTO_POOL_SIZE = 7  # сколько лотов с фото набрать в пул для ручного отбора
DIGEST_FULL_COUNT = 100   # сколько лотов максимум положить в Telegraph-страницу (lots_top_gap сам по себе топ-50)

# --- Мини-апп honestlot (export_to_miniapp.py) ---
# Карточку лота на сайте торгов (все фото, график периодов публичного
# предложения, статус) перекачиваем, если кэш старше стольких дней.
MINIAPP_DETAILS_REFRESH_DAYS = 7
