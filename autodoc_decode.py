#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VIN -> Autodoc -> Google Sheets

Что делает:
1. Открывает Google Sheets.
2. Берет VIN из столбца E.
3. Запрашивает Autodoc:
   https://web.autodoc.ru/api/catalog-original-service/catalog-original/vin-modifications?identifier=<VIN>
4. Разбирает ответ.
5. Пишет результат начиная с AZ.
6. Записывает Google Sheets пакетами.
7. Повторно запускаемый: уже заполненные результаты можно обновлять.
8. Ошибка одного VIN не останавливает обработку остальных.
9. Неизвестные поля ответа Autodoc не теряются:
   они автоматически становятся дополнительными колонками.

Требования:
    pip install requests google-api-python-client google-auth
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import config



# ============================================================
# CONFIG
# ============================================================

# ID таблицы хранится в local_secrets.py (не в git), берём через config
SPREADSHEET_ID = config.SPREADSHEET_ID

# Имя листа.
# None = взять первый лист таблицы (gid=0 в вашей ссылке).
WORKSHEET_NAME = "lots"

# JSON-файл Google Service Account
GOOGLE_CREDENTIALS_FILE = "service_account.json"

# VIN находится в E
VIN_COLUMN = 5

# Результат начинается с AZ
OUTPUT_COLUMN = 52

# На один Google Sheets batch
SHEETS_BATCH_SIZE = 200

# Одновременно обращаемся к Autodoc
MAX_WORKERS = 5

# HTTP
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
RETRY_BACKOFF = 1.5

# Безопасный максимум для одной ячейки.
# Google Sheets имеет лимит 50 000 символов.
MAX_CELL_CHARS = 45000

AUTODOC_URL = (
    "https://web.autodoc.ru/api/catalog-original-service/"
    "catalog-original/vin-modifications"
)

# Если True — принудительно переработать ВСЕ VIN.
#
# Обычный режим:
#     False
#
# Для полного перерасчета:
#     True
#
# После одного запуска вернуть False.
FORCE_REPROCESS_ALL = False


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# FIXED OUTPUT SCHEMA
# ============================================================

FIXED_HEADERS = [
    "brand",             # AZ
    "name",              # BA
    "date",              # BB
    "model",             # BC
    "market",            # BD
    "modification",      # BE
    "frames",            # BF
    "modelyearfrom",     # BG
    "modelyearto",       # BH
    "framecolor",        # BI
    "painttype",         # BJ
    "trimcolor",         # BK
    "options",           # BL
    "catalogCode",       # BM
    "vehicleId",         # BN
    "ssd",               # BO
    "modificationUrl",   # BP
    "api_status",        # BQ
]


# ============================================================
# UTILS
# ============================================================

def column_to_letter(column_number: int) -> str:
    """52 -> AZ"""

    result = ""

    while column_number:

        column_number, remainder = divmod(
            column_number - 1,
            26,
        )

        result = (
            chr(65 + remainder)
            + result
        )

    return result


def normalize_text(value: Any) -> str:
    """
    Приводит значение к строке.
    Не допускаем огромных значений для одной ячейки.
    """

    if value is None:
        return ""

    if isinstance(value, bool):
        text = (
            "TRUE"
            if value
            else "FALSE"
        )

    elif isinstance(
        value,
        (int, float),
    ):
        text = str(value)

    elif isinstance(value, str):
        text = value.strip()

    elif isinstance(value, list):

        text = " | ".join(
            normalize_text(item)
            for item in value
            if item is not None
        )

    elif isinstance(value, dict):

        text = "; ".join(
            f"{key}={normalize_text(val)}"
            for key, val in value.items()
        )

    else:

        text = str(value)

    if len(text) > MAX_CELL_CHARS:

        logger.warning(
            "Значение обрезано с %d до %d символов.",
            len(text),
            MAX_CELL_CHARS,
        )

        text = text[
            :MAX_CELL_CHARS
        ]

    return text


def normalize_header(value: str) -> str:
    """Приводит имя колонки к аккуратному виду."""

    value = str(value).strip()

    value = value.replace(
        "\n",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value


# ============================================================
# GOOGLE SHEETS
# ============================================================

def get_google_service():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = (
        Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=scopes,
        )
    )

    return build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def get_sheet_info(service) -> dict[str, Any]:

    response = (
        service.spreadsheets()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            fields=(
                "sheets(properties("
                "sheetId,"
                "title,"
                "index"
                "))"
            ),
        )
        .execute()
    )

    sheets = response.get(
        "sheets",
        [],
    )

    if not sheets:
        raise RuntimeError(
            "В таблице нет листов."
        )

    if WORKSHEET_NAME:

        for sheet in sheets:

            properties = (
                sheet["properties"]
            )

            if (
                properties["title"]
                == WORKSHEET_NAME
            ):
                return properties

        raise RuntimeError(
            f"Лист '{WORKSHEET_NAME}' не найден."
        )

    return sheets[0]["properties"]


def read_sheet(service, sheet_title: str):

    """
    Читаем до BQ.

    Нам нужны:
    E  = VIN
    AZ = результат
    BQ = api_status
    """

    range_name = (
        f"'{sheet_title}'!A:BQ"
    )

    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )

    return response.get(
        "values",
        [],
    )


# ============================================================
# VIN SELECTION
# ============================================================

def collect_vins(
    rows: list[list[str]],
    force_reprocess: bool,
) -> list[tuple[int, str]]:

    """
    Возвращает:

        [
            (row_number, VIN),
            ...
        ]

    В обычном режиме смотрим BQ:
        OK -> уже обработан
        ошибка -> повторяем

    При force_reprocess=True:
        обрабатываем всё.
    """

    result = []

    STATUS_INDEX = (
        OUTPUT_COLUMN
        + len(FIXED_HEADERS)
        - 2
    )

    # OUTPUT_COLUMN = 52 (AZ)
    # FIXED_HEADERS[16] = api_status
    # API_STATUS = BQ = index 68 в Python zero-based

    for row_number, row in enumerate(
        rows,
        start=1,
    ):

        # Строка заголовка
        if row_number == 1:
            continue

        # VIN находится в E
        if len(row) < VIN_COLUMN:
            continue

        vin = normalize_text(
            row[
                VIN_COLUMN - 1
            ]
        ).upper()

        if not vin:
            continue

        # Принудительный режим
        if force_reprocess:

            result.append(
                (
                    row_number,
                    vin,
                )
            )

            continue

        # Получаем api_status из BQ
        status = ""

        if len(row) > STATUS_INDEX:

            status = normalize_text(
                row[STATUS_INDEX]
            )

        # Успешно обработанные VIN не трогаем
        if status == "OK":
            continue

        # Пустые и ошибочные строки обрабатываем
        result.append(
            (
                row_number,
                vin,
            )
        )

    return result


# ============================================================
# AUTODOC REQUEST
# ============================================================

def create_session() -> requests.Session:

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140 Safari/537.36"
            ),
            "Accept": (
                "application/json, "
                "text/plain, */*"
            ),
        }
    )

    return session


def fetch_autodoc(
    vin: str,
    session: requests.Session,
) -> tuple[
    dict[str, Any] | None,
    str,
]:

    """
    Получает JSON от Autodoc.
    """

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = session.get(
                AUTODOC_URL,
                params={
                    "identifier": vin
                },
                timeout=REQUEST_TIMEOUT,
            )

            # Временные ошибки / rate limit
            if response.status_code in (
                429,
                500,
                502,
                503,
                504,
            ):

                if (
                    attempt
                    < MAX_RETRIES
                ):

                    delay = (
                        RETRY_BACKOFF
                        ** attempt
                    )

                    logger.warning(
                        "%s: HTTP %s. "
                        "Повтор через %.1f сек.",
                        vin,
                        response.status_code,
                        delay,
                    )

                    time.sleep(delay)

                    continue

            response.raise_for_status()

            data = response.json()

            return (
                data,
                "OK",
            )

        except requests.RequestException as exc:

            if (
                attempt
                < MAX_RETRIES
            ):

                delay = (
                    RETRY_BACKOFF
                    ** attempt
                )

                logger.warning(
                    "%s: %s. "
                    "Повтор через %.1f сек.",
                    vin,
                    exc,
                    delay,
                )

                time.sleep(delay)

                continue

            return (
                None,
                f"REQUEST_ERROR: {exc}",
            )

        except ValueError as exc:

            return (
                None,
                f"JSON_ERROR: {exc}",
            )

        except Exception as exc:

            return (
                None,
                f"ERROR: {exc}",
            )

    return (
        None,
        "UNKNOWN_ERROR",
    )


# ============================================================
# COMMON ATTRIBUTES
# ============================================================

def extract_common_attributes(
    data: dict[str, Any],
) -> dict[str, str]:

    """
    Autodoc:

    "commonAttributes": [
        {
            "key": "date",
            "name": "Дата выпуска",
            "value": "09.1994",
            ...
        }
    ]

    Используем строго:

        key -> value

    а НЕ:

        name -> value

    Это принципиально важно.
    """

    result = {}

    attributes = data.get(
        "commonAttributes",
        [],
    )

    if not isinstance(
        attributes,
        list,
    ):
        return result

    for item in attributes:

        if not isinstance(
            item,
            dict,
        ):
            continue

        key = item.get("key")

        if not key:
            continue

        value = item.get(
            "value"
        )

        result[
            normalize_header(
                str(key)
            )
        ] = normalize_text(
            value
        )

    return result


# ============================================================
# SAFE RECURSIVE SEARCH
# ============================================================

def find_specific_keys(
    obj: Any,
    keys: set[str],
) -> dict[str, Any]:

    """
    Рекурсивно ищет ТОЛЬКО конкретные ключи.

    Здесь безопасно искать:

        catalogCode
        vehicleId
        ssd
        modificationUrl

    Но НЕЛЬЗЯ таким способом искать "name".
    """

    found = {}

    if isinstance(
        obj,
        dict,
    ):

        for key, value in obj.items():

            if key in keys:

                found[key] = value

            # Если найдено — всё равно можно
            # проверить вложенные объекты.
            nested = find_specific_keys(
                value,
                keys,
            )

            found.update(
                nested
            )

    elif isinstance(
        obj,
        list,
    ):

        for item in obj:

            nested = find_specific_keys(
                item,
                keys,
            )

            found.update(
                nested
            )

    return found


# ============================================================
# OPTIONS
# ============================================================

def extract_options(
    data: dict[str, Any],
) -> list[str]:

    """
    Собирает опции, не используя вложенное "name"
    как название автомобиля.

    Поддерживает разные варианты структуры API.
    """

    options: list[str] = []

    def walk(obj: Any):

        if isinstance(
            obj,
            dict,
        ):

            for key, value in obj.items():

                key_lower = str(
                    key
                ).lower()

                if key_lower in {
                    "options",
                    "option",
                    "equipments",
                    "equipment",
                }:

                    collect_option_value(
                        value
                    )

                else:

                    walk(value)

        elif isinstance(
            obj,
            list,
        ):

            for item in obj:
                walk(item)

    def collect_option_value(
        value: Any,
    ):

        if isinstance(
            value,
            list,
        ):

            for item in value:

                if isinstance(
                    item,
                    str,
                ):

                    text = item.strip()

                    if text:
                        options.append(
                            text
                        )

                elif isinstance(
                    item,
                    dict,
                ):

                    # Для конкретной опции
                    # сначала value/description,
                    # а затем name.
                    text = (
                        item.get("value")
                        or item.get(
                            "description"
                        )
                        or item.get("name")
                    )

                    if text:

                        text = normalize_text(
                            text
                        )

                        if text:
                            options.append(
                                text
                            )

        elif isinstance(
            value,
            str,
        ):

            text = value.strip()

            if text:
                options.append(
                    text
                )

        elif isinstance(
            value,
            dict,
        ):

            text = (
                value.get("value")
                or value.get(
                    "description"
                )
                or value.get("name")
            )

            if text:

                text = normalize_text(
                    text
                )

                if text:
                    options.append(
                        text
                    )

    walk(data)

    # Убираем дубли
    result = []

    for option in options:

        if option not in result:

            result.append(
                option
            )

    return result


# ============================================================
# PARSER
# ============================================================

def parse_autodoc(
    vin: str,
    data: dict[str, Any] | None,
    status: str,
) -> dict[str, str]:

    """
    Финальный разбор ответа.

    Главный источник характеристик:
        commonAttributes

    Поэтому:
        key="date" -> date
        key="name" -> name
        key="model" -> model
        etc.

    Никакой рекурсивной записи "name".
    """

    result = {
        "brand": "",
        "name": "",
        "date": "",
        "model": "",
        "market": "",
        "modification": "",
        "frames": "",
        "modelyearfrom": "",
        "modelyearto": "",
        "framecolor": "",
        "painttype": "",
        "trimcolor": "",
        "options": "",
        "catalogCode": "",
        "vehicleId": "",
        "ssd": "",
        "modificationUrl": "",
        "api_status": status,
    }

    if not data:

        return result

    # ========================================================
    # 1. COMMON ATTRIBUTES
    # ========================================================

    common = extract_common_attributes(
        data
    )

    # Эти поля БЕРЕМ ИМЕННО ПО key
    for field in [
        "brand",
        "name",
        "date",
        "model",
        "market",
        "modification",
        "frames",
        "modelyearfrom",
        "modelyearto",
        "framecolor",
        "painttype",
        "trimcolor",
    ]:

        if field in common:

            result[field] = common[
                field
            ]

    # ========================================================
    # 2. FALLBACK ДЛЯ ОСНОВНЫХ ПОЛЕЙ
    # ========================================================

    # Если конкретное поле отсутствует в commonAttributes,
    # пробуем взять его из корня.
    #
    # ВАЖНО:
    # никаких рекурсивных поисков name/date здесь нет.

    root_fields = [
        "brand",
        "name",
        "date",
        "model",
        "market",
        "modification",
        "frames",
        "modelyearfrom",
        "modelyearto",
    ]

    for field in root_fields:

        if (
            not result[field]
            and field in data
        ):

            result[field] = normalize_text(
                data[field]
            )

    # ========================================================
    # 3. CATALOG FIELDS
    # ========================================================

    catalog_keys = {
        "catalogCode",
        "vehicleId",
        "ssd",
        "modificationUrl",
    }

    catalog = find_specific_keys(
        data,
        catalog_keys,
    )

    for key, value in catalog.items():

        result[key] = normalize_text(
            value
        )

    # ========================================================
    # 4. OPTIONS
    # ========================================================

    options = extract_options(
        data
    )

    if options:

        result["options"] = (
            " | ".join(options)
        )

        # До 20 отдельных опций
        for index, option in enumerate(
            options[:20],
            start=1,
        ):

            result[
                f"option_{index:02d}"
            ] = option

    return result


# ============================================================
# PROCESS ONE VIN
# ============================================================

def process_vin(
    vin: str,
) -> dict[str, str]:

    session = create_session()

    try:

        logger.info(
            "Запрос Autodoc: %s",
            vin,
        )

        data, status = fetch_autodoc(
            vin,
            session,
        )

        result = parse_autodoc(
            vin,
            data,
            status,
        )

        logger.info(
            "%s -> %s | name=%s | date=%s | model=%s",
            vin,
            status,
            result.get("name", ""),
            result.get("date", ""),
            result.get("model", ""),
        )

        return result

    finally:

        session.close()


# ============================================================
# HEADERS
# ============================================================

def build_headers(
    results: list[dict[str, str]],
) -> list[str]:

    """
    Сначала фиксированные поля.

    Потом любые дополнительные commonAttributes,
    которые встретились у автомобилей.
    """

    headers = list(
        FIXED_HEADERS
    )

    discovered = set()

    for result in results:

        discovered.update(
            result.keys()
        )

    # Дополнительные поля
    # (option_01 и т.п.)
    for key in sorted(
        discovered,
        key=str.lower,
    ):

        if key not in headers:

            headers.append(
                key
            )

    return headers


# ============================================================
# WRITE HEADERS
# ============================================================

def write_headers(
    service,
    sheet_title: str,
    headers: list[str],
):

    start_col = column_to_letter(
        OUTPUT_COLUMN
    )

    end_col = column_to_letter(
        OUTPUT_COLUMN
        + len(headers)
        - 1
    )

    range_name = (
        f"'{sheet_title}'!"
        f"{start_col}1:"
        f"{end_col}1"
    )

    body = {
        "valueInputOption": "RAW",
        "data": [
            {
                "range": range_name,
                "values": [
                    headers
                ],
            }
        ],
    }

    (
        service.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body,
        )
        .execute()
    )


# ============================================================
# WRITE BATCH
# ============================================================

def make_write_request(
    sheet_title: str,
    row_number: int,
    result: dict[str, str],
    headers: list[str],
):

    values = [
        normalize_text(
            result.get(
                header,
                "",
            )
        )
        for header in headers
    ]

    start_col = column_to_letter(
        OUTPUT_COLUMN
    )

    end_col = column_to_letter(
        OUTPUT_COLUMN
        + len(headers)
        - 1
    )

    range_name = (
        f"'{sheet_title}'!"
        f"{start_col}{row_number}:"
        f"{end_col}{row_number}"
    )

    return {
        "range": range_name,
        "values": [
            values
        ],
    }


def write_rows_batch(
    service,
    sheet_title: str,
    rows_to_write: list[
        tuple[int, dict[str, str]]
    ],
    headers: list[str],
):

    if not rows_to_write:
        return

    data = []

    for row_number, result in rows_to_write:

        data.append(
            make_write_request(
                sheet_title,
                row_number,
                result,
                headers,
            )
        )

    body = {
        "valueInputOption": "RAW",
        "data": data,
    }

    try:

        (
            service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=body,
            )
            .execute()
        )

        return

    except Exception as exc:

        logger.error(
            "Batch из %d строк не записался: %s",
            len(rows_to_write),
            exc,
        )

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------
        # Пробуем строки по одной.
        # Тогда одна проблемная строка не уничтожает batch.
        # ----------------------------------------------------

        for row_number, result in rows_to_write:

            single = make_write_request(
                sheet_title,
                row_number,
                result,
                headers,
            )

            try:

                (
                    service.spreadsheets()
                    .values()
                    .batchUpdate(
                        spreadsheetId=SPREADSHEET_ID,
                        body={
                            "valueInputOption": "RAW",
                            "data": [single],
                        },
                    )
                    .execute()
                )

            except Exception as row_exc:

                logger.error(
                    "ОШИБКА записи строки %d: %s",
                    row_number,
                    row_exc,
                )


# ============================================================
# HEADER CHECK
# ============================================================

def is_correct_schema(
    rows: list[list[str]],
) -> bool:

    """
    Проверяет, что AZ1 уже содержит "brand".

    Старый скрипт писал в AZ VIN,
    поэтому при первом запуске новой версии
    header != brand -> делаем полный пересчет.
    """

    if not rows:
        return False

    header = ""

    # AZ = 52-й столбец
    if len(rows[0]) >= OUTPUT_COLUMN:

        header = normalize_text(
            rows[0][
                OUTPUT_COLUMN - 1
            ]
        )

    return header == "brand"


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    logger.info(
        "Подключение к Google Sheets..."
    )

    service = get_google_service()

    sheet = get_sheet_info(
        service
    )

    sheet_title = sheet["title"]

    logger.info(
        "Используется лист: %s",
        sheet_title,
    )

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------

    rows = read_sheet(
        service,
        sheet_title,
    )

    if not rows:

        logger.info(
            "Лист пуст."
        )

        return

    # --------------------------------------------------------
    # SCHEMA CHECK
    # --------------------------------------------------------

    schema_ok = is_correct_schema(
        rows
    )

    if not schema_ok:

        logger.warning(
            "В AZ1 нет заголовка 'brand'."
        )

        logger.warning(
            "Обнаружена старая/неправильная "
            "схема результата."
        )

        logger.warning(
            "Будут переработаны все VIN."
        )

        force_reprocess = True

    else:

        force_reprocess = (
            FORCE_REPROCESS_ALL
        )

    # --------------------------------------------------------
    # VIN
    # --------------------------------------------------------

    vins = collect_vins(
        rows,
        force_reprocess,
    )

    total_vins = len(vins)

    logger.info(
        "VIN к обработке: %d",
        total_vins,
    )

    if total_vins == 0:

        logger.info(
            "Новых/ошибочных VIN нет."
        )

        return

    # --------------------------------------------------------
    # AUTODOC
    # --------------------------------------------------------

    results_by_row = {}

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for row_number, vin in vins:

            future = executor.submit(
                process_vin,
                vin,
            )

            futures[future] = (
                row_number,
                vin,
            )

        completed = 0

        for future in as_completed(
            futures
        ):

            row_number, vin = futures[
                future
            ]

            completed += 1

            try:

                result = future.result()

            except Exception as exc:

                logger.exception(
                    "Ошибка worker для %s",
                    vin,
                )

                result = {
                    "api_status":
                        f"WORKER_ERROR: {exc}",
                }

            # НЕ "vin" - в таблице уже есть колонка "vin" (E, исходный VIN
            # лота). Раньше этот же ключ "vin" попадал в build_headers()
            # как "неизвестное поле" и создавал ВТОРУЮ колонку "vin" в
            # хвосте (после api_status) - путаница и риск, что кто-то
            # прочитает не тот "vin" по имени колонки.
            result["vin_autodoc"] = vin

            results_by_row[
                row_number
            ] = result

            logger.info(
                "Обработано %d/%d",
                completed,
                total_vins,
            )

    # --------------------------------------------------------
    # HEADERS
    # --------------------------------------------------------

    ordered_results = [
        results_by_row[row_number]
        for row_number, _ in vins
    ]

    headers = build_headers(
        ordered_results
    )

    logger.info(
        "Количество колонок результата: %d",
        len(headers),
    )

    logger.info(
        "Результат начинается с %s",
        column_to_letter(
            OUTPUT_COLUMN
        ),
    )

    # Записываем заголовки
    write_headers(
        service,
        sheet_title,
        headers,
    )

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    items = sorted(
        results_by_row.items()
    )

    total = len(items)

    for start in range(
        0,
        total,
        SHEETS_BATCH_SIZE,
    ):

        batch = items[
            start:
            start + SHEETS_BATCH_SIZE
        ]

        logger.info(
            "Запись строк %d-%d из %d...",
            start + 1,
            start + len(batch),
            total,
        )

        write_rows_batch(
            service,
            sheet_title,
            batch,
            headers,
        )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    successful = sum(
        1
        for result in results_by_row.values()
        if result.get(
            "api_status"
        ) == "OK"
    )

    failed = total - successful

    elapsed = (
        time.time()
        - start_time
    )

    logger.info("=" * 70)
    logger.info("ГОТОВО")
    logger.info(
        "Обработано VIN: %d",
        total,
    )
    logger.info(
        "Успешно: %d",
        successful,
    )
    logger.info(
        "Ошибок: %d",
        failed,
    )
    logger.info(
        "Время: %.1f сек.",
        elapsed,
    )
    logger.info("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()