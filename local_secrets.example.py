# -*- coding: utf-8 -*-
"""Шаблон секретов. Скопируйте в local_secrets.py (рядом с config.py)
и впишите настоящие значения - local_secrets.py в git не попадает."""

# Ключ TRONK - личный кабинет https://lk.tronk.info/
TRONK_API_KEY = "ВСТАВЬТЕ_КЛЮЧ_TRONK"
# Токен Telegram-бота - от @BotFather
TELEGRAM_BOT_TOKEN = "ВСТАВЬТЕ_ТОКЕН_БОТА"
# ID Google-таблицы - из её URL: docs.google.com/spreadsheets/d/<ID>/edit
SPREADSHEET_ID = "ВСТАВЬТЕ_ID_ТАБЛИЦЫ"
# Мини-апп honestlot: адрес сервера (например "https://51-250-10-20.sslip.io")
# и ключ импорта - тот же, что HONESTLOT_IMPORT_TOKEN на сервере.
# Необязательные: без них export_to_miniapp.py просто ничего не делает.
MINIAPP_API_URL = ""
MINIAPP_IMPORT_TOKEN = ""
# Ключ Claude API (check_damage_photos.py, проверка фото) - console.anthropic.com.
# Необязательный: без него SDK возьмёт переменную окружения ANTHROPIC_API_KEY.
ANTHROPIC_API_KEY = ""
