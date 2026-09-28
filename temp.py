import requests
import sys
import json

import config

# ----------------------------------------------------------------------
# Настройки
# ----------------------------------------------------------------------
BASE_URL = "https://data.tronk.info/probeg.ashx"

# Ключ берётся из local_secrets.py (через config.py)
API_KEY = config.TRONK_API_KEY

# VIN из вашего запроса
VIN = "W0L0SDL0886126552"

# Таймаут ожидания ответа (секунды)
TIMEOUT = 15


def main():
    # Параметры GET-запроса
    params = {
        "key": API_KEY,
        "vin": VIN,
    }

    try:
        # Отправляем GET-запрос
        response = requests.get(
            BASE_URL,
            params=params,
            timeout=TIMEOUT,
            headers={"User-Agent": "Python-requests/2.31"},
        )
        # Проверяем HTTP-статус (4xx, 5xx вызовут исключение)
        response.raise_for_status()

        # Пытаемся разобрать ответ как JSON
        try:
            data = response.json()
            print("Ответ сервера (JSON):")
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            # Если сервер вернул не JSON, выводим как текст
            print("Ответ сервера (текст):")
            print(response.text)

    except requests.exceptions.Timeout:
        print(f"Ошибка: превышен таймаут {TIMEOUT} секунд.", file=sys.stderr)
    except requests.exceptions.HTTPError as e:
        print(f"Ошибка HTTP: {e}", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()