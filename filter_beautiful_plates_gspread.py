#!/usr/bin/env python3
"""
Скрипт делает срез таблицы автомобилей с "красивыми" / "особыми" номерами,
используя официальный Google Sheets API (через gspread), без экспорта в CSV.

Что делает:
  1. Подключается к Google Sheets по API (через сервисный аккаунт).
  2. Читает нужный лист как есть (без промежуточного файла).
  3. Загружает регулярки из plates_series.txt (SPECIAL_SERIES + BEAUTIFUL_PATTERNS).
  4. Проверяет столбец "plate" на совпадение с любой из регулярок.
  5. Результат:
       - записывает новую вкладку "beautiful_plates" прямо в ту же
         Google-таблицу (перезаписывая её при повторном запуске);
       - плюс сохраняет beautiful_plates.xlsx локально — на всякий случай.

===========================================================================
НАСТРОЙКА ДОСТУПА (один раз, займёт минут 5-10)
===========================================================================

1. Заходите в Google Cloud Console: https://console.cloud.google.com/
2. Создаёте проект (или берёте существующий).
3. В разделе "APIs & Services" → "Library" включаете два API:
     - Google Sheets API
     - Google Drive API
4. "APIs & Services" → "Credentials" → "Create Credentials" → "Service account".
   Даёте любое имя, роль можно не назначать (не нужна для доступа к конкретной
   таблице).
5. Открываете созданный сервисный аккаунт → вкладка "Keys" → "Add Key" →
   "Create new key" → JSON. Скачается файл вида
   "my-project-1234-abcdef123456.json" — сохраните его рядом со скриптом
   и переименуйте, например, в service_account.json.
6. Внутри JSON-файла есть поле "client_email" — вида
   "имя@проект.iam.gserviceaccount.com". Скопируйте этот адрес.
7. Откройте вашу Google-таблицу → кнопка "Настройки доступа" (Share) →
   вставьте этот email → выдайте права "Редактор" (нужно, чтобы скрипт мог
   записать вкладку с результатом; если хотите только читать — хватит
   "Читатель", но тогда закомментируйте блок записи в таблицу ниже).

pip install gspread google-auth pandas openpyxl

===========================================================================
"""

import re
import importlib.util
import importlib.machinery
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config

# ============================== CONFIG ===================================

# ID таблицы хранится в local_secrets.py (не в git), берём через config
SHEET_ID = config.SPREADSHEET_ID
GID = 917772508  # id конкретного листа (вкладки) с исходными данными

SERVICE_ACCOUNT_FILE = Path(__file__).with_name("service_account.json")
PATTERNS_FILE = Path(__file__).with_name("plates_series.txt")

PLATE_COLUMN = "plate"

RESULT_WORKSHEET_NAME = "beautiful_plates"  # вкладка, куда запишется срез
WRITE_BACK_TO_SHEET = True  # False — если сервисному аккаунту дан только "Читатель"

OUTPUT_XLSX = Path(__file__).with_name("beautiful_plates.xlsx")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ===========================================================================


def load_patterns(path: Path) -> dict[str, re.Pattern]:
    """Загружает SPECIAL_SERIES и BEAUTIFUL_PATTERNS из .txt файла как модуль."""
    loader = importlib.machinery.SourceFileLoader("plates_series", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    patterns: dict[str, str] = {}
    patterns.update(getattr(module, "SPECIAL_SERIES", {}))
    patterns.update(getattr(module, "BEAUTIFUL_PATTERNS", {}))

    if not patterns:
        raise ValueError(
            f"В файле {path} не найдено ни SPECIAL_SERIES, ни BEAUTIFUL_PATTERNS"
        )
    return {name: re.compile(pattern) for name, pattern in patterns.items()}


def match_plate(plate: str, patterns: dict[str, re.Pattern]) -> str | None:
    """Возвращает имя первого совпавшего паттерна или None."""
    if not isinstance(plate, str) or not plate.strip():
        return None
    plate = plate.strip().upper().replace(" ", "").replace("Ё", "Е")
    for name, regex in patterns.items():
        if regex.match(plate):
            return name
    return None


def open_worksheet_by_gid(spreadsheet: gspread.Spreadsheet, gid: int) -> gspread.Worksheet:
    for ws in spreadsheet.worksheets():
        if ws.id == gid:
            return ws
    raise ValueError(f"Вкладка с gid={gid} не найдена в таблице")


def main() -> None:
    if not SERVICE_ACCOUNT_FILE.exists():
        raise SystemExit(
            f"Не найден файл ключа сервисного аккаунта: {SERVICE_ACCOUNT_FILE}\n"
            "См. инструкцию по настройке в начале файла скрипта."
        )

    patterns = load_patterns(PATTERNS_FILE)
    print(f"Загружено паттернов: {len(patterns)}")

    creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SHEET_ID)
    source_ws = open_worksheet_by_gid(spreadsheet, GID)

    records = source_ws.get_all_records()  # список словарей, заголовки из первой строки
    df = pd.DataFrame(records)
    print(f"Строк в исходной таблице: {len(df)}")

    if PLATE_COLUMN not in df.columns:
        raise SystemExit(
            f"В таблице нет столбца '{PLATE_COLUMN}'. "
            f"Доступные столбцы: {list(df.columns)}"
        )

    df["match_pattern"] = df[PLATE_COLUMN].apply(lambda p: match_plate(p, patterns))
    result = df[df["match_pattern"].notna()].copy()
    print(f"Найдено машин с красивыми/особыми номерами: {len(result)}")

    # --- локальная копия на всякий случай ---
    result.to_excel(OUTPUT_XLSX, index=False)
    print(f"Локально сохранено: {OUTPUT_XLSX}")

    # --- запись результата обратно в Google-таблицу новой вкладкой ---
    if WRITE_BACK_TO_SHEET:
        try:
            existing = spreadsheet.worksheet(RESULT_WORKSHEET_NAME)
            spreadsheet.del_worksheet(existing)
        except gspread.exceptions.WorksheetNotFound:
            pass

        result_ws = spreadsheet.add_worksheet(
            title=RESULT_WORKSHEET_NAME,
            rows=len(result) + 1,
            cols=max(len(result.columns), 1),
        )
        result_ws.update(
            [result.columns.tolist()] + result.astype(str).values.tolist()
        )
        print(f"Результат записан во вкладку '{RESULT_WORKSHEET_NAME}' той же таблицы")


if __name__ == "__main__":
    main()
