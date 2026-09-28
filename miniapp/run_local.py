# -*- coding: utf-8 -*-
r"""
Локальный запуск мини-аппа для проверки в обычном браузере (без Telegram):
    python miniapp/run_local.py            -> http://localhost:8000
    python miniapp/run_local.py --import   -> ещё и загрузить в локальную базу
                                              miniapp_export_preview.json
                                              (его делает export_to_miniapp.py --dry-run)

Режим разработки: HONESTLOT_DEV_USER_ID=1 - запросы без Telegram initData
считаются запросами пользователя с id 1 (на сервере эта переменная НЕ
задаётся). Ключ импорта локально - "dev". База - miniapp/backend/data/.
"""
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "miniapp", "backend")]
os.environ.setdefault("HONESTLOT_DEV_USER_ID", "1")
os.environ.setdefault("HONESTLOT_IMPORT_TOKEN", "dev")

import requests  # noqa: E402
import uvicorn  # noqa: E402

PORT = int(os.environ.get("PORT", "8000"))


def import_preview():
    path = os.path.join(ROOT, "miniapp_export_preview.json")
    for _ in range(50):
        try:
            requests.get(f"http://127.0.0.1:{PORT}/api/health", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.2)
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    r = requests.post(f"http://127.0.0.1:{PORT}/api/import", json=payload,
                      headers={"X-Import-Token": os.environ["HONESTLOT_IMPORT_TOKEN"]}, timeout=60)
    print("Импорт:", r.status_code, r.text[:200])


if __name__ == "__main__":
    if "--import" in sys.argv:
        threading.Thread(target=import_preview, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT)
