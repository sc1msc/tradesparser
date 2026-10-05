# -*- coding: utf-8 -*-
r"""
Бэкап базы мини-аппа: раз в сутки копия в <папка базы>/backups/, хранятся
KEEP последних. Плюс свежая копия по запросу ПК (GET /api/backup) - шаг 7
пайплайна складывает её на ПК (export_to_miniapp.download_backup), чтобы
копия жила не только на той же ВМ.

Почему так, а не cron или снимки диска Yandex Cloud: поток внутри
приложения выкладывается вместе с кодом (deploy.sh), на ВМ настраивать
нечего; снимки диска платные. База - несколько мегабайт, копия занимает
доли секунды и ВМ не нагружает.

Копия - через sqlite3 backup API, а не копированием файла: при WAL файл
базы сам по себе может быть несогласованным, backup даёт целостный снимок.

Восстановление (на сервере):
  cd ~/honestlot/miniapp && docker compose stop api
  cp data/backups/honestlot-YYYY-MM-DD.db data/honestlot.db && rm -f data/honestlot.db-wal data/honestlot.db-shm
  docker compose start api
"""
import datetime
import glob
import os
import sqlite3
import threading
import time

from . import db

KEEP = 7
BACKUP_HOUR_MSK = 4          # ночью, когда в мини-аппе никого нет
CHECK_EVERY_SECONDS = 3600
MSK = datetime.timezone(datetime.timedelta(hours=3))
PREFIX = "honestlot-"


def backup_dir():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "backups")


def snapshot(path):
    """Целостная копия базы в path (через временный файл - недописанная
    копия не подменит готовую)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    dst = sqlite3.connect(tmp)
    try:
        with db._lock:  # чтобы копия не пересекалась с импортом
            db.conn().backup(dst)
    finally:
        dst.close()
    os.replace(tmp, path)
    return path


def daily(now=None):
    """Ежедневная копия, если за сегодня её ещё нет и уже BACKUP_HOUR_MSK.
    Возвращает путь новой копии или None."""
    now = now or datetime.datetime.now(MSK)
    if now.hour < BACKUP_HOUR_MSK:
        return None
    path = os.path.join(backup_dir(), f"{PREFIX}{now.date().isoformat()}.db")
    if os.path.exists(path):
        return None
    snapshot(path)
    for old in sorted(glob.glob(os.path.join(backup_dir(), f"{PREFIX}*.db")))[:-KEEP]:
        os.remove(old)
    return path


def _loop():
    while True:
        try:
            path = daily()
            if path:
                print(f"Бэкап базы: {path}", flush=True)
        except Exception as e:  # бэкап не должен ронять приложение
            print(f"Бэкап базы не удался: {e}", flush=True)
        time.sleep(CHECK_EVERY_SECONDS)


def start():
    threading.Thread(target=_loop, name="db-backup", daemon=True).start()
