# -*- coding: utf-8 -*-
r"""
Хранилище мини-аппа - один файл SQLite (путь - переменная окружения
HONESTLOT_DB, по умолчанию miniapp/backend/data/honestlot.db).

Почему SQLite, а не Postgres из спецификации: лотов сотни (при расширении
на всю страну - до 5-10 тыс.), пишет в базу только импорт раз в сутки плюс
редкие клики "в избранное". Отдельный сервер БД на таком объёме - лишние
деньги и администрирование, а бэкап - это просто копия файла. Весь SQL
здесь - обычный, без SQLite-специфики, кроме "INSERT ... ON CONFLICT"
(есть и в Postgres) - переезд, если понадобится, затронет только этот файл.

Таблицы:
  lots      - витрина лотов. Источник истины - Google-таблица (лист
              lots_current_month) + карточка лота на сайте торгов; сюда
              всё приходит через POST /api/import (export_to_miniapp.py).
              Лоты, пропавшие из листа, НЕ удаляются (in_source = 0):
              на них могут ссылаться избранные.
  users     - пользователи Telegram (telegram_id из подписанного initData).
              source - откуда пришёл: параметр startapp ссылки вида
              t.me/honestlot_bot?startapp=<метка> (в initData - start_param,
              подписан Telegram). Первый известный источник не
              перезаписывается; last_source - метка последнего входа по ссылке.
              Ссылки "Поделиться" на лот дают source = "share" (auth.split_start_param);
              ref_code - случайный код пользователя для его ссылок "Поделиться",
              referred_by - telegram_id того, по чьей ссылке человек пришёл
              (только для новых: уже знакомого пользователя ссылка не "приводит").
  favorites - избранное: (telegram_id, lot_id) + vin машины - избранное
              следует за машиной (см. lots.favorites_list).
  events    - минимальная аналитика: open (открыл мини-апп), lot_view
              (открыл карточку лота), fav_add (в избранное), source_click
              (перешёл на сайт торгов - самый сильный сигнал интереса),
              share (нажал "Поделиться" на экране лота).
              Сводка - python -m app.stats (miniapp/backend/app/stats.py).
"""
import json
import os
import secrets
import sqlite3
import threading

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "honestlot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    lot_id            TEXT PRIMARY KEY,
    url               TEXT,
    title             TEXT,
    brand             TEXT,
    model             TEXT,
    year              INTEGER,
    vin               TEXT,
    plate             TEXT,
    mileage_km        INTEGER,
    mileage_estimated INTEGER NOT NULL DEFAULT 0,
    price_start       INTEGER,
    price_current     INTEGER,
    region            TEXT,
    trade_form        TEXT,
    is_public_offer   INTEGER NOT NULL DEFAULT 0,
    status            TEXT,
    platform          TEXT,
    applications_end  TEXT,
    bidding_start     TEXT,
    periods           TEXT,
    photos            TEXT,
    description       TEXT,
    autoru_price_low  INTEGER,
    autoru_price_high INTEGER,
    autoru_owners     INTEGER,
    estimate_uncertain INTEGER NOT NULL DEFAULT 0,
    lot_kind          TEXT,
    status_checked_at TEXT,
    in_source         INTEGER NOT NULL DEFAULT 1,
    first_seen_at     TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id   INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    source        TEXT,
    last_source   TEXT,
    ref_code      TEXT,
    referred_by   INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    type        TEXT NOT NULL,
    lot_id      TEXT,
    source      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_created ON events (created_at);

CREATE TABLE IF NOT EXISTS favorites (
    telegram_id INTEGER NOT NULL,
    lot_id      TEXT NOT NULL,
    vin         TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (telegram_id, lot_id)
);
"""

# Поля лота, которые принимает импорт (всё остальное в JSON игнорируется).
# periods/photos - списки, храним как JSON-текст.
LOT_FIELDS = [
    "url", "title", "brand", "model", "year", "vin", "plate",
    "mileage_km", "mileage_estimated", "price_start", "price_current",
    "region", "trade_form", "is_public_offer", "status", "platform",
    "applications_end", "bidding_start", "periods", "photos", "description",
    "autoru_price_low", "autoru_price_high", "autoru_owners", "estimate_uncertain",
    "lot_kind",
]
JSON_FIELDS = {"periods", "photos"}
FLAG_FIELDS = {"mileage_estimated", "is_public_offer", "estimate_uncertain"}

# Колонки, добавленные после первого запуска на сервере: CREATE TABLE IF NOT
# EXISTS их в существующую базу не добавит - досоздаём ALTER TABLE.
MIGRATIONS = {
    "lots": [("estimate_uncertain", "INTEGER NOT NULL DEFAULT 0"), ("lot_kind", "TEXT"),
             ("status_checked_at", "TEXT")],
    "favorites": [("vin", "TEXT")],
    "users": [("source", "TEXT"), ("last_source", "TEXT"), ("ref_code", "TEXT"), ("referred_by", "INTEGER")],
}
# Индексы по колонкам из MIGRATIONS - после ALTER TABLE, не в SCHEMA: на
# старой базе SCHEMA выполняется, когда этих колонок ещё нет.
POST_MIGRATION_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS users_ref_code ON users (ref_code)"

EVENT_TYPES = {"open", "lot_view", "fav_add", "source_click", "share"}

# Код для ссылок "Поделиться": без похожих 0/o, 1/l/i. 6 знаков - ~10^9
# вариантов, совпадение при генерации всё равно проверяется (UNIQUE).
REF_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
REF_LENGTH = 6

_lock = threading.Lock()


def db_path():
    return os.environ.get("HONESTLOT_DB") or DEFAULT_DB_PATH


def connect():
    path = db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.execute(POST_MIGRATION_SQL)
    conn.commit()
    return conn


_conn = None


def conn():
    """Одно соединение на процесс (uvicorn с одним воркером). Запись - под
    _lock, чтобы импорт и клики "в избранное" не пересекались."""
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def row_to_lot(row):
    lot = dict(row)
    for f in JSON_FIELDS:
        lot[f] = json.loads(lot[f]) if lot.get(f) else []
    return lot


def all_lots():
    return [row_to_lot(r) for r in conn().execute("SELECT * FROM lots")]


def import_lots(lots, now_iso):
    """Upsert всех пришедших лотов; лоты, которых в этом импорте нет,
    помечаются in_source = 0 (но не удаляются). Всё в одной транзакции -
    если импорт упадёт на середине, витрина останется прежней."""
    placeholders = ", ".join(["?"] * (len(LOT_FIELDS) + 3))
    columns = ", ".join(["lot_id"] + LOT_FIELDS + ["first_seen_at", "updated_at"])
    updates = ", ".join(f"{f} = excluded.{f}" for f in LOT_FIELDS)
    sql = (
        f"INSERT INTO lots ({columns}, in_source) VALUES ({placeholders}, 1) "
        f"ON CONFLICT(lot_id) DO UPDATE SET {updates}, "
        f"updated_at = excluded.updated_at, in_source = 1"
    )
    ids = []
    with _lock:
        c = conn()
        with c:
            for lot in lots:
                values = []
                for f in LOT_FIELDS:
                    v = lot.get(f)
                    if f in JSON_FIELDS:
                        v = json.dumps(v or [], ensure_ascii=False)
                    elif f in FLAG_FIELDS:
                        v = 1 if v else 0
                    values.append(v)
                c.execute(sql, [str(lot["lot_id"])] + values + [now_iso, now_iso])
                ids.append(str(lot["lot_id"]))
            if ids:
                marks = ", ".join(["?"] * len(ids))
                cur = c.execute(f"UPDATE lots SET in_source = 0 WHERE in_source = 1 AND lot_id NOT IN ({marks})", ids)
            else:
                cur = c.execute("UPDATE lots SET in_source = 0 WHERE in_source = 1")
    return len(ids), cur.rowcount


def touch_user(telegram_id, username, first_name, now_iso, start_param=None, ref_code=None):
    """start_param - метка из ссылки ?startapp=... (None при входе через
    кнопку меню), уже разобранная auth.split_start_param. source - первый
    известный источник, не перезаписывается. ref_code - код из ссылки
    "Поделиться": referred_by пишется только при создании пользователя."""
    with _lock:
        c = conn()
        with c:
            referred_by = None
            if ref_code:
                row = c.execute("SELECT telegram_id FROM users WHERE ref_code = ?", (ref_code,)).fetchone()
                if row and row["telegram_id"] != telegram_id:
                    referred_by = row["telegram_id"]
            c.execute(
                "INSERT INTO users (telegram_id, username, first_name, created_at, last_seen_at, "
                "source, last_source, referred_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(telegram_id) DO UPDATE SET "
                "username = excluded.username, first_name = excluded.first_name, "
                "last_seen_at = excluded.last_seen_at, "
                "source = COALESCE(users.source, excluded.source), "
                "last_source = COALESCE(excluded.last_source, users.last_source)",
                (telegram_id, username, first_name, now_iso, now_iso, start_param, start_param, referred_by),
            )


def user_ref_code(telegram_id):
    """Код пользователя для ссылок "Поделиться" - создаётся при первом
    запросе и дальше не меняется (иначе разосланные ссылки потеряют автора)."""
    with _lock:
        c = conn()
        row = c.execute("SELECT ref_code FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row and row["ref_code"]:
            return row["ref_code"]
        while True:
            code = "".join(secrets.choice(REF_ALPHABET) for _ in range(REF_LENGTH))
            try:
                with c:
                    c.execute("UPDATE users SET ref_code = ? WHERE telegram_id = ?", (code, telegram_id))
                return code
            except sqlite3.IntegrityError:  # такой код уже у кого-то есть
                continue


def log_event(telegram_id, event_type, now_iso, lot_id=None, source=None):
    if event_type not in EVENT_TYPES:
        return
    with _lock:
        c = conn()
        with c:
            c.execute(
                "INSERT INTO events (telegram_id, type, lot_id, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (telegram_id, event_type, lot_id, source, now_iso),
            )


def favorite_rows(telegram_id):
    """[(lot_id, vin)] избранного пользователя, новые сверху."""
    rows = conn().execute(
        "SELECT lot_id, vin FROM favorites WHERE telegram_id = ? ORDER BY created_at DESC", (telegram_id,)
    )
    return [(r["lot_id"], r["vin"]) for r in rows]


def all_favorite_rows():
    return [(r["lot_id"], r["vin"]) for r in conn().execute("SELECT DISTINCT lot_id, vin FROM favorites")]


def add_favorite(telegram_id, lot_id, vin, now_iso):
    with _lock:
        c = conn()
        with c:
            c.execute(
                "INSERT OR IGNORE INTO favorites (telegram_id, lot_id, vin, created_at) VALUES (?, ?, ?, ?)",
                (telegram_id, lot_id, vin, now_iso),
            )


def remove_favorite(telegram_id, lot_id, vin=None):
    """Убирает лот и - если у него есть машина - все её лоты из избранного:
    избранное следует за машиной, снимать звёздочку тоже нужно с машины."""
    with _lock:
        c = conn()
        with c:
            c.execute("DELETE FROM favorites WHERE telegram_id = ? AND (lot_id = ? OR (vin IS NOT NULL AND vin = ?))",
                      (telegram_id, lot_id, vin or ""))


def update_statuses(items, now_iso):
    """Статусы лотов, перечитанные с сайта (lots.watchlist): [{lot_id, status}]."""
    with _lock:
        c = conn()
        with c:
            for it in items:
                c.execute("UPDATE lots SET status = COALESCE(?, status), status_checked_at = ? WHERE lot_id = ?",
                          (it.get("status") or None, now_iso, str(it["lot_id"])))
    return len(items)
