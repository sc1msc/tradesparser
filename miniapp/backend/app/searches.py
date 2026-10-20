# -*- coding: utf-8 -*-
r"""
Сохранённые поиски (Pro, решение владельца 18.10.2026): фильтры ленты под именем, по которым сервер
присылает новые лоты (notify.py).

Что хранится. Поиск - те же параметры, что у ленты (GET /api/lots: q, brands, models, year_from...;
FILTER_KEYS), в JSON. Совпадение лота с поиском считает та же функция, что и ленту (lots._matches), -
лот, о котором пришло уведомление, пользователь увидит и в ленте с этими фильтрами. Сортировка и
страница не хранятся. Имя можно не задавать: тогда оно собирается из фильтров (describe) при каждом
показе - так в нём всегда актуальные подписи марок и моделей.

ПОВТОРОВ НЕТ (главное требование владельца). О машине пользователь узнаёт один раз: таблица notify_seen
- (пользователь, машина), машина - VIN (lot["car"]) или "lot:<номер>" у лота без VIN. Поэтому:
  - одна машина на нескольких площадках (параллельные лоты) - одно уведомление: лента показывает её
    одной карточкой, поиск видит одну;
  - машина подошла под два поиска пользователя - одно уведомление, по первому поиску;
  - машину выставили снова (торги не состоялись) - по поиску не присылаем, а если она в избранном -
    придёт событие избранного «выставлена снова» (notify.py); машины из избранного поиск пропускает;
  - лот, который уже был в выдаче, когда поиск сохранили или поменяли (baseline), - не новость:
    при сохранении все подходящие сейчас машины отмечаются как известные;
  - лот подошёл позже - подешевел до бюджета (публичное предложение), вырос процент к рынку - это
    новость, она придёт (машина ещё не известна пользователю).
Отметка ставится в одной транзакции с событием (INSERT OR IGNORE по ключу (пользователь, машина)), до
отправки - два прохода не могут прислать одно и то же.

Включение. HONESTLOT_SAVED_SEARCHES в .env: пусто - выключено (API отвечает 404, интерфейса нет),
"all" - всем, список telegram_id или @ников через запятую - только им (проверка на сервере перед
запуском для всех; ник ищется в users.username - человек должен хоть раз открыть приложение).

«Новые» у поиска (вкладка «Поиски», метка «новый» на карточке) - лоты из уведомлений этого поиска
(notify_events), пришедшие после того, как пользователь последний раз открывал поиск (opened_at), и
всё ещё подходящие под него.
Создать поиск может только пользователь с Pro (при включённой оплате); у кого Pro кончился, поиски
остаются, но уведомления не приходят (notify.py).
"""
import json
import os

from . import billing, db, lots

MAX_PER_USER = 10
FILTER_KEYS = ("q", "brands", "models", "year_from", "year_to", "price_from", "price_to", "mileage_to",
               "regions", "kinds", "trade", "gap_min", "owners_to", "dtp_to", "hide_damaged", "fuel", "gearbox", "drive",
               "vol_from", "vol_to", "power_from", "power_to")
MAX_NAME = 60
DEFAULT_PRICE_FROM = 300000  # «Цена от 300 тыс.» - начальный фильтр ленты (emptyFilters в app.js)

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    name        TEXT,               -- имя от пользователя; NULL - собирается из фильтров (describe)
    params      TEXT NOT NULL,      -- JSON: параметры ленты (FILTER_KEYS)
    notify      INTEGER NOT NULL DEFAULT 1,  -- присылать новые лоты
    opened_at   TEXT,               -- когда пользователь последний раз открыл поиск (для «новых»)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS saved_searches_user ON saved_searches(telegram_id);

-- машины, о которых пользователь уже знает: из выдачи при сохранении поиска (baseline) или из уведомления
CREATE TABLE IF NOT EXISTS notify_seen (
    telegram_id INTEGER NOT NULL,
    car_key     TEXT NOT NULL,      -- VIN или "lot:<номер>"
    lot_id      TEXT,
    search_id   INTEGER,
    reason      TEXT NOT NULL,      -- baseline / notified
    created_at  TEXT NOT NULL,
    PRIMARY KEY (telegram_id, car_key)
);
"""

_schema_ready = False


def conn():
    global _schema_ready
    c = db.conn()
    if not _schema_ready:
        with db._lock:
            c.executescript(SCHEMA)
            if "opened_at" not in {r[1] for r in c.execute("PRAGMA table_info(saved_searches)")}:
                c.execute("ALTER TABLE saved_searches ADD COLUMN opened_at TEXT")  # базы до 19.10.2026
            c.commit()
        _schema_ready = True
    return c


def _allowed_ids():
    return os.environ.get("HONESTLOT_SAVED_SEARCHES", "").strip()


def enabled():
    return bool(_allowed_ids())


def enabled_for(telegram_id):
    value = _allowed_ids()
    if not value:
        return False
    if value == "all":
        return True
    allowed = {x.strip().lower() for x in value.split(",") if x.strip()}
    if str(telegram_id) in allowed:
        return True
    names = {x[1:] for x in allowed if x.startswith("@")}
    if not names:
        return False
    row = db.conn().execute("SELECT username FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    return bool(row and row[0] and row[0].lower() in names)


def can_create(telegram_id):
    """Поиски - для Pro. Без оплаты (локальный запуск) - всем, у кого включено."""
    return not billing.enabled() or billing.is_pro(telegram_id)


def clean_params(params):
    """Только фильтры ленты, строками, без пустых и без сортировки/страницы."""
    out = {}
    for key in FILTER_KEYS:
        value = (params or {}).get(key)
        if value in (None, "", [], False):
            continue
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        value = str(value).strip()[:100 if key == "q" else 2000]
        if value:
            out[key] = value
    return out


def car_key(lot):
    return lot["car"] or f"lot:{lot['lot_id']}"


def matching(params, pairs=None):
    """Открытые лоты (карточки ленты), подходящие под поиск: [(item, lot)]."""
    f = lots.parse_filters(params)
    pairs = pairs if pairs is not None else lots.open_items(lots.Favs([]))
    return [(it, lot) for it, lot in pairs if lots._matches(it, lot, f)]


# ---------- имя поиска из фильтров ----------

TRADE_TEXT = {lots.TRADE_AUCTION: "аукцион", lots.TRADE_PUBLIC_OFFER: "публичное предложение"}


def _money(value):
    v = float(value)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " млн"
    if v >= 1000:
        return f"{round(v / 1000)} тыс."
    return f"{round(v)}"


def _range(lo, hi, fmt, unit=""):
    unit = f" {unit}" if unit else ""
    if lo and hi:
        return f"{fmt(lo)}–{fmt(hi)}{unit}"
    if lo:
        return f"от {fmt(lo)}{unit}"
    if hi:
        return f"до {fmt(hi)}{unit}"
    return ""


def _labels():
    brands, models = {}, {}
    for lot in lots.load():
        if lot["brand_key"]:
            brands.setdefault(lot["brand_key"], lot["brand_label"])
            if lot["model_key"]:
                models.setdefault((lot["brand_key"], lot["model_key"]), lot["model_label"])
    return brands, models


def describe(params):
    """Фильтры -> короткое имя: «Toyota Camry, RAV4 · 2015–2020 · до 1,5 млн ₽ · от 20% ниже рынка»."""
    p = clean_params(params)
    split = lambda v: [x for x in (v or "").split(",") if x]
    brand_labels, model_labels = _labels()
    chosen = {}
    for item in split(p.get("models")):
        if "|" in item:
            b, m = item.split("|", 1)
            chosen.setdefault(lots._norm_key(b), []).append(lots._norm_key(m))
    parts = []
    names = []
    for b in [lots._norm_key(x) for x in split(p.get("brands"))] + [b for b in chosen if b not in
                                                                     {lots._norm_key(x) for x in split(p.get("brands"))}]:
        label = brand_labels.get(b) or lots.pretty_name(b)
        ms = [model_labels.get((b, m)) or lots.pretty_name(m) for m in chosen.get(b, [])]
        names.append(f"{label} {', '.join(ms)}" if ms else label)
    if names:
        parts.append("; ".join(names))
    if p.get("q"):
        parts.append(f"«{p['q']}»")
    num = lambda v: float(v) if v else None
    years = _range(num(p.get("year_from")), num(p.get("year_to")), lambda v: str(int(v)), "г.")
    if years:
        parts.append(years)
    price_from = num(p.get("price_from"))
    if price_from == DEFAULT_PRICE_FROM:
        price_from = None  # начальный фильтр ленты - в имени только шум
    price = _range(price_from, num(p.get("price_to")), _money, "₽")
    if price:
        parts.append(price)
    if p.get("mileage_to"):
        parts.append(f"пробег до {_money(p['mileage_to'])} км")
    if p.get("gap_min"):
        parts.append(f"от {int(float(p['gap_min']))}% ниже рынка")
    if p.get("dtp_to") not in (None, ""):
        n = int(float(p["dtp_to"]))
        parts.append("без ДТП" if n == 0 else f"до {n} ДТП")
    if p.get("owners_to"):
        n = int(float(p["owners_to"]))
        parts.append("1 владелец" if n == 1 else f"до {n} владельцев")
    for key in ("fuel", "gearbox", "drive"):
        if p.get(key):
            parts.append(", ".join(split(p[key])))
    vol = _range(num(p.get("vol_from")), num(p.get("vol_to")), lambda v: f"{v:.1f}".replace(".", ","), "л")
    if vol:
        parts.append(vol)
    power = _range(num(p.get("power_from")), num(p.get("power_to")), lambda v: str(int(v)), "л.с.")
    if power:
        parts.append(power)
    if p.get("trade"):
        parts.append(", ".join(TRADE_TEXT.get(t, t) for t in split(p["trade"])))
    if p.get("regions"):
        parts.append(", ".join(r.replace("г. ", "") for r in split(p["regions"])))  # «г. Москва» -> «Москва»
    if p.get("kinds") == "multilot":
        parts.append("мультилоты")
    return " · ".join(parts) or "Все лоты"


# ---------- хранение ----------

def _row(r, pairs, fresh):
    params = json.loads(r["params"])
    found = matching(params, pairs)
    # новые - машины из уведомлений этого поиска после последнего открытия, если всё ещё подходят
    new_ids = [lot["lot_id"] for _, lot in found if car_key(lot) in fresh.get(r["id"], ())]
    return {"id": r["id"], "name": r["name"] or describe(params), "custom_name": bool(r["name"]),
            "filters": describe(params), "params": params, "notify": bool(r["notify"]),
            "total": len(found), "new_ids": new_ids, "created_at": r["created_at"]}


def _fresh_cars(telegram_id, rows):
    """{id поиска: машины из уведомлений после opened_at} (таблица событий - notify.py)."""
    opened = {r["id"]: r["opened_at"] or r["created_at"] for r in rows}
    out = {}
    try:
        events = conn().execute("SELECT search_id, car_key, created_at FROM notify_events "
                                "WHERE telegram_id = ? AND kind = 'search'", (telegram_id,)).fetchall()
    except Exception:  # таблицы ещё нет - уведомлений не было
        return out
    for e in events:
        if e["search_id"] in opened and e["created_at"] > opened[e["search_id"]]:
            out.setdefault(e["search_id"], set()).add(e["car_key"])
    return out


def list_for(telegram_id):
    rows = conn().execute("SELECT * FROM saved_searches WHERE telegram_id = ? ORDER BY id", (telegram_id,)).fetchall()
    pairs = lots.open_items(lots.Favs([])) if rows else []
    fresh = _fresh_cars(telegram_id, rows)
    return [_row(r, pairs, fresh) for r in rows]


def preview(params):
    """Окно «Сохранить поиск»: имя из фильтров и сколько лотов подходит сейчас."""
    params = clean_params(params)
    return {"name": describe(params), "total": len(matching(params)), "params": params}


def mark_opened(telegram_id, search_id, now_iso):
    with db._lock:
        c = conn()
        with c:
            n = c.execute("UPDATE saved_searches SET opened_at = ? WHERE id = ? AND telegram_id = ?",
                          (now_iso, search_id, telegram_id)).rowcount
    return bool(n)


def get(telegram_id, search_id):
    return conn().execute("SELECT * FROM saved_searches WHERE id = ? AND telegram_id = ?",
                          (search_id, telegram_id)).fetchone()


def baseline(telegram_id, params, now_iso, search_id=None):
    """Все подходящие сейчас машины - известные: о них не уведомляем (пользователь видит их в выдаче)."""
    rows = [(telegram_id, car_key(lot), lot["lot_id"], search_id, "baseline", now_iso)
            for _, lot in matching(params)]
    with db._lock:
        c = conn()
        with c:
            c.executemany("INSERT OR IGNORE INTO notify_seen (telegram_id, car_key, lot_id, search_id, reason, "
                          "created_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def create(telegram_id, params, now_iso, name=None, notify=True):
    params = clean_params(params)
    c = conn()
    if c.execute("SELECT COUNT(*) FROM saved_searches WHERE telegram_id = ?", (telegram_id,)).fetchone()[0] >= MAX_PER_USER:
        raise ValueError(f"можно сохранить до {MAX_PER_USER} поисков - удалите ненужный")
    name = (name or "").strip()[:MAX_NAME] or None
    with db._lock:
        with c:
            cur = c.execute("INSERT INTO saved_searches (telegram_id, name, params, notify, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (telegram_id, name, json.dumps(params, ensure_ascii=False), int(bool(notify)), now_iso, now_iso))
    sid = cur.lastrowid
    baseline(telegram_id, params, now_iso, sid)
    return sid


def update(telegram_id, search_id, now_iso, name=None, params=None, notify=None):
    """name="" - вернуть имя из фильтров. Поменялись фильтры или включили уведомления - новая отметка
    известных машин: присылаем только то, что появится дальше."""
    row = get(telegram_id, search_id)
    if row is None:
        raise KeyError(search_id)
    new_params = clean_params(params) if params is not None else json.loads(row["params"])
    new_name = row["name"] if name is None else ((name or "").strip()[:MAX_NAME] or None)
    new_notify = row["notify"] if notify is None else int(bool(notify))
    with db._lock:
        c = conn()
        with c:
            c.execute("UPDATE saved_searches SET name = ?, params = ?, notify = ?, updated_at = ? WHERE id = ?",
                      (new_name, json.dumps(new_params, ensure_ascii=False), new_notify, now_iso, search_id))
    if (params is not None and new_params != json.loads(row["params"])) or (new_notify and not row["notify"]):
        baseline(telegram_id, new_params, now_iso, search_id)


def delete(telegram_id, search_id):
    """Известные машины остаются известными: удалить поиск и сохранить такой же - повторов не будет."""
    with db._lock:
        c = conn()
        with c:
            n = c.execute("DELETE FROM saved_searches WHERE id = ? AND telegram_id = ?",
                          (search_id, telegram_id)).rowcount
    return bool(n)


def active_rows():
    """Поиски с уведомлениями - для прохода notify.py."""
    return conn().execute("SELECT * FROM saved_searches WHERE notify = 1 ORDER BY telegram_id, id").fetchall()
