# -*- coding: utf-8 -*-
r"""
Уведомления пользователям (Pro, решения владельца 18.10.2026): новые лоты по сохранённым поискам
(searches.py) и события избранного - «машину выставили снова» и «цена снизилась» («итоги торгов»
заморожены). Каналы - бот @honestlot_bot и письмо раз в день.

КАК. Фоновый поток в api (как billing, watchdog) делает проход (run_pass), как только на сервере
появились новые данные: после выгрузки с ПК (kick из POST /api/import - это и есть новые лоты) и после
каждой проверки статусов (status_refresh.py: цены и итоги торгов); ещё раз в день в DIGEST_HOUR - для
письма. Окна «только днём» нет (решение владельца 19.10.2026): новые лоты приходят сразу после прогона.
Цена публичного предложения меняется по графику (часто в полночь) и событие появляется с проверкой
статусов в 05:00, поэтому о публичных предложениях («цена снизилась», новый лот по поиску) Telegram
пишет не раньше PUBLIC_OFFER_FROM_HOUR (8:00 по Москве, решение владельца 19.10.2026): до этого они
ждут, в 08:01 поток просыпается сам. Аукционы и всё после 8:00 - сразу.
  1. события - для каждого пользователя с Pro и включённой функцией (searches.enabled_for):
     - поиск: открытые лоты ленты под фильтры поиска, машины, о которых пользователь ещё не знает
       (notify_seen) и которых нет в его избранном (о них - события избранного). Отметка «знает» и
       событие пишутся в одной транзакции до отправки - повторов нет (подробно - searches.py);
     - избранное (fav_watch - последнее, что мы знаем о машине: её открытый лот и цена):
       «выставлена снова» - у машины снова открытый лот, и это другой лот, а не тот же после паузы
       (лот прятался, пока на ЭТП «подводились итоги», и вернулся - не событие); «цена снизилась» -
       у открытого лота цена ниже известной (публичное предложение перешло на следующий этап, у машины
       появился более дешёвый параллельный лот). Машину, только что добавленную в избранное, просто
       запоминаем;
     события получают канал в момент создания: tg - если бот может писать пользователю, email - если
     почта подтверждена и письма включены; без каналов событие всё равно пишется (машина становится
     известной, и после включения канала не придёт пачка старого);
  2. Telegram - сразу: одно сообщение на поиск (до MAX_LINES лотов и «…и ещё N», кнопка открывает мини-апп с этим поиском) и одно на
     избранное. 403 / «chat not found» - пользователь заблокировал бота: Telegram ему больше не шлём,
     пока он снова не разрешит сообщения в мини-аппе. 429 или нет связи с релеем - стоп до следующего
     прохода (события ждут, но не дольше TG_TTL_HOURS). Таймаут ответа - сообщение, возможно, ушло:
     считаем отправленным (лучше пропустить, чем прислать дважды);
  3. письмо - раз в день после DIGEST_HOUR: всё новое по поискам и избранному за сутки одним письмом,
     со ссылкой «Отписаться» (и заголовком List-Unsubscribe - кнопка «Отписаться» в почте).

Перерыв. Если пользователь не проходил проверку дольше REBASELINE_HOURS (кончался Pro, функцию
выключали) - вместо событий его поиски заново отмечают все подходящие машины известными: после
продления не придёт пачка всего, что появилось за перерыв.

Разрешение писать. Бот может написать человеку первым, только если тот запускал бота или разрешил это
в мини-аппе (requestWriteAccess). Кто пришёл по прямой ссылке t.me/<бот>?startapp=... (подарок автора
курса, «Поделиться», метка источника), бота мог не запускать ни разу - ему не дойдут ни уведомления, ни
рассылка (broadcast.py). Поэтому мини-апп сам спрашивает разрешение у тех, у кого его нет (решение
владельца 30.10.2026): не больше WRITE_ASK_MAX раз, с перерывом WRITE_ASK_PAUSE_DAYS после «Не сейчас».
Сколько раз спрашивали, хранит сервер (write_asks, write_asked_at), а не телефон: после очистки данных
Telegram или на другом устройстве окно не появится снова. write_ask_due -> признак write_ask в /api/me.

Почта подтверждается ссылкой из письма (confirm_url); адрес, на который уже пришла оплата Pro, -
сразу подтверждён. Ссылки подписаны (billing._link_secret): подтверждение живёт CONFIRM_DAYS дней,
«Отписаться» - бессрочно.
"""
import datetime
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.parse

from . import billing, db, lots, mailer, searches, telegram

DIGEST_HOUR = 10                       # письмо - раз в день, после 10:00
PUBLIC_OFFER_FROM_HOUR = 8             # о публичных предложениях в Telegram - не раньше 8:00 (их цена падает ночью)
MAX_LINES = 5                          # лотов в одном сообщении, остальное - «…и ещё N»
TG_TTL_HOURS = 24                      # событие, не доставленное в Telegram за сутки, - не шлём
REBASELINE_HOURS = 72                  # проходы - минимум раз в день (письмо), обычно 5-6 раз
CONFIRM_DAYS = 3
SEND_PAUSE_SECONDS = 0.1               # между сообщениями (лимиты Telegram)
WRITE_ASK_MAX = 2                      # окно «Разрешите боту писать» - не больше двух раз
WRITE_ASK_PAUSE_DAYS = 14              # второй раз - не раньше, чем через 14 дней после первого
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notify_settings (
    telegram_id        INTEGER PRIMARY KEY,
    tg                 INTEGER NOT NULL DEFAULT 0,  -- бот может писать (разрешили в мини-аппе)
    tg_blocked_at      TEXT,                        -- Telegram ответил 403: бот заблокирован
    email              TEXT,
    email_verified_at  TEXT,
    email_on           INTEGER NOT NULL DEFAULT 0,
    email_digest_at    TEXT,                        -- когда ушло последнее письмо
    fav_events         INTEGER NOT NULL DEFAULT 1,  -- события избранного
    last_pass_at       TEXT,                        -- последний проход с событиями
    write_asks         INTEGER NOT NULL DEFAULT 0,  -- сколько раз мини-апп спрашивал разрешение писать
    write_asked_at     TEXT,                        -- когда спросил последний раз
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fav_watch (
    telegram_id INTEGER NOT NULL,
    car_key     TEXT NOT NULL,      -- VIN или "lot:<номер>"
    lot_id      TEXT,               -- последний известный главный лот машины
    is_open     INTEGER NOT NULL,   -- он был открыт
    price       INTEGER,            -- его последняя известная цена
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (telegram_id, car_key)
);

CREATE TABLE IF NOT EXISTS notify_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    kind        TEXT NOT NULL,      -- search / relisted / price_down
    search_id   INTEGER,
    lot_id      TEXT NOT NULL,
    car_key     TEXT NOT NULL,
    price       INTEGER,
    prev_price  INTEGER,
    created_at  TEXT NOT NULL,
    tg          TEXT,               -- pending / sent / failed / expired; NULL - канала не было
    tg_at       TEXT,
    email       TEXT,               -- pending / sent; NULL - канала не было
    email_at    TEXT
);
CREATE INDEX IF NOT EXISTS notify_events_tg ON notify_events(tg);
CREATE INDEX IF NOT EXISTS notify_events_email ON notify_events(email);
"""

_schema_ready = False
_kick = threading.Event()
_pass_lock = threading.Lock()


def conn():
    global _schema_ready
    c = searches.conn()
    if not _schema_ready:
        with db._lock:
            c.executescript(SCHEMA)
            have = {r[1] for r in c.execute("PRAGMA table_info(notify_settings)")}
            if "write_asks" not in have:  # базы до 30.10.2026
                c.execute("ALTER TABLE notify_settings ADD COLUMN write_asks INTEGER NOT NULL DEFAULT 0")
            if "write_asked_at" not in have:
                c.execute("ALTER TABLE notify_settings ADD COLUMN write_asked_at TEXT")
            c.commit()
        _schema_ready = True
    return c


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _dt(value):
    try:
        dt = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=lots.MSK)


# ---------- настройки ----------

def _settings_row(telegram_id):
    return conn().execute("SELECT * FROM notify_settings WHERE telegram_id = ?", (telegram_id,)).fetchone()


def settings(telegram_id):
    r = _settings_row(telegram_id)
    return {
        "tg": bool(r and r["tg"] and not r["tg_blocked_at"]),
        "tg_blocked": bool(r and r["tg_blocked_at"]),
        "email": r["email"] if r else None,
        "email_verified": bool(r and r["email_verified_at"]),
        "email_on": bool(r and r["email_on"] and r["email_verified_at"]),
        "fav_events": bool(r["fav_events"]) if r else True,
    }


def _upsert(telegram_id, now_iso, **fields):
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
    with db._lock:
        c = conn()
        with c:
            c.execute(f"INSERT INTO notify_settings (telegram_id, {cols}, updated_at) VALUES (?, {marks}, ?) "
                      f"ON CONFLICT(telegram_id) DO UPDATE SET {updates}, updated_at = excluded.updated_at",
                      (telegram_id, *fields.values(), now_iso))


def set_tg(telegram_id, allowed, now_iso):
    """Мини-апп сообщил итог requestWriteAccess (или пользователь выключил Telegram у себя)."""
    _upsert(telegram_id, now_iso, tg=int(bool(allowed)), tg_blocked_at=None)


def write_ask_due(telegram_id, now=None):
    """Пора ли спросить разрешение писать: бот ещё не может писать (по нашим данным; что знает Telegram,
    мини-апп видит сам - allows_write_to_pm), спрашивали меньше WRITE_ASK_MAX раз и не за последние
    WRITE_ASK_PAUSE_DAYS дней."""
    r = _settings_row(telegram_id)
    if not r:
        return True
    if r["tg"] and not r["tg_blocked_at"]:
        return False
    if r["write_asks"] >= WRITE_ASK_MAX:
        return False
    asked = _dt(r["write_asked_at"])
    now = now or datetime.datetime.now(lots.MSK)
    return asked is None or now - asked >= datetime.timedelta(days=WRITE_ASK_PAUSE_DAYS)


def note_write_ask(telegram_id, now_iso):
    """Мини-апп показал окно «Разрешите боту писать»."""
    with db._lock:
        c = conn()
        with c:
            c.execute("INSERT INTO notify_settings (telegram_id, write_asks, write_asked_at, updated_at) "
                      "VALUES (?, 1, ?, ?) ON CONFLICT(telegram_id) DO UPDATE SET "
                      "write_asks = write_asks + 1, write_asked_at = excluded.write_asked_at, "
                      "updated_at = excluded.updated_at", (telegram_id, now_iso, now_iso))


def set_fav_events(telegram_id, on, now_iso):
    _upsert(telegram_id, now_iso, fav_events=int(bool(on)))


def set_email_on(telegram_id, on, now_iso):
    _upsert(telegram_id, now_iso, email_on=int(bool(on)))


def touch_pass(telegram_id, now_iso):
    """Новый поиск: проходы считаются непрерывными с этого момента (иначе первый проход - «перерыв»)."""
    row = _settings_row(telegram_id)
    if not row or not row["last_pass_at"]:
        _upsert(telegram_id, now_iso, last_pass_at=now_iso)


def _sign(*parts):
    return hmac.new(billing._link_secret(), ".".join(str(p) for p in parts).encode(),
                    hashlib.sha256).hexdigest()[:32]


def confirm_url(telegram_id, email, now=None):
    exp = int((now or time.time()) + CONFIRM_DAYS * 86400)
    token = f"{telegram_id}.{exp}.{_sign(telegram_id, exp, email.lower(), 'confirm')}"
    return f"{billing.site_url()}/notify/confirm?t={token}"


def unsubscribe_url(telegram_id):
    return f"{billing.site_url()}/notify/unsubscribe?t={telegram_id}.{_sign(telegram_id, 'unsub')}"


def request_email(telegram_id, email, now_iso):
    """Почта для писем. -> "verified" (адрес оплаты Pro - подтверждён сразу) или "sent" (ушла ссылка)."""
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        raise ValueError("проверьте адрес почты")
    sub = billing.subscription(telegram_id) if billing.enabled() else None
    if sub and (sub.get("email") or "").strip().lower() == email.lower():
        _upsert(telegram_id, now_iso, email=email, email_verified_at=now_iso, email_on=1)
        return "verified"
    _upsert(telegram_id, now_iso, email=email, email_verified_at=None, email_on=1)
    mailer.send(email, "HonestLot: подтвердите почту для уведомлений",
                "Здравствуйте!\n\nЧтобы получать на эту почту новые лоты по сохранённым поискам и изменения "
                f"в избранном HonestLot, подтвердите адрес:\n{confirm_url(telegram_id, email)}\n\n"
                f"Ссылка действует {CONFIRM_DAYS} дня. Если вы не просили уведомления - просто не "
                "открывайте её.\n")
    return "sent"


def confirm(token, now_iso, now=None):
    """Ссылка из письма -> telegram_id или None (устарела, адрес сменили)."""
    try:
        tid, exp, sig = token.split(".")
        tid, exp = int(tid), int(exp)
    except (ValueError, AttributeError):
        return None
    r = _settings_row(tid)
    if not r or not r["email"] or exp < (now or time.time()) or \
            not hmac.compare_digest(sig, _sign(tid, exp, r["email"].lower(), "confirm")):
        return None
    _upsert(tid, now_iso, email_verified_at=now_iso, email_on=1)
    return tid


def unsubscribe(token, now_iso):
    try:
        tid, sig = token.split(".")
        tid = int(tid)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(sig, _sign(tid, "unsub")):
        return None
    _upsert(tid, now_iso, email_on=0)
    return tid


# ---------- события ----------

def _eligible(telegram_id):
    return searches.enabled_for(telegram_id) and searches.can_create(telegram_id)


def _channels(st):
    return ("pending" if st["tg"] else None), ("pending" if st["email_on"] else None)


def _search_events(telegram_id, pairs, now_iso, channels):
    favs = lots.Favs(db.favorite_rows(telegram_id))
    c = conn()
    seen = {r[0] for r in c.execute("SELECT car_key FROM notify_seen WHERE telegram_id = ?", (telegram_id,))}
    found = []
    for s in c.execute("SELECT * FROM saved_searches WHERE telegram_id = ? AND notify = 1 ORDER BY id",
                       (telegram_id,)).fetchall():
        for it, lot in searches.matching(json.loads(s["params"]), pairs):
            key = searches.car_key(lot)
            if key in seen or favs.has(lot):
                continue
            seen.add(key)
            found.append((s["id"], it, lot, key))
    created = 0
    with db._lock:
        with c:
            for sid, it, lot, key in found:
                n = c.execute("INSERT OR IGNORE INTO notify_seen (telegram_id, car_key, lot_id, search_id, reason, "
                              "created_at) VALUES (?, ?, ?, ?, 'notified', ?)",
                              (telegram_id, key, lot["lot_id"], sid, now_iso)).rowcount
                if n:  # отметку поставил этот проход - событие одно
                    c.execute("INSERT INTO notify_events (telegram_id, kind, search_id, lot_id, car_key, price, "
                              "created_at, tg, email) VALUES (?, 'search', ?, ?, ?, ?, ?, ?, ?)",
                              (telegram_id, sid, lot["lot_id"], key, it["price"], now_iso, *channels))
                    created += 1
    return created


def _fav_events(telegram_id, now, now_iso, channels):
    favs = lots.Favs(db.favorite_rows(telegram_id))
    c = conn()
    watch = {r["car_key"]: r for r in c.execute("SELECT * FROM fav_watch WHERE telegram_id = ?", (telegram_id,))}
    writes, events, keep = [], [], set()
    for it in lots.favorites_list(favs, now):
        lot = lots.get(it["id"])
        if lot is None:
            continue
        key = searches.car_key(lot)
        keep.add(key)
        opened = it["fav_state"] == "open"
        price = it["price"] if opened else None
        row = watch.get(key)
        if row is None:  # только что в избранном - запоминаем
            writes.append((key, it["id"], int(opened), price))
            continue
        if opened:
            if not row["is_open"] and row["lot_id"] != it["id"]:
                events.append(("relisted", it, key, row["price"]))
            elif row["is_open"] and row["lot_id"] != it["id"]:
                old = lots.get(row["lot_id"])
                old_open = old is not None and lots.is_open(old, lots.current_state(old, now), now)
                if not old_open:
                    events.append(("relisted", it, key, row["price"]))
                elif price is not None and row["price"] is not None and price < row["price"]:
                    events.append(("price_down", it, key, row["price"]))
            elif price is not None and row["price"] is not None and price < row["price"]:
                events.append(("price_down", it, key, row["price"]))
            if (row["lot_id"], row["is_open"], row["price"]) != (it["id"], 1, price):
                writes.append((key, it["id"], 1, price))
        elif row["is_open"]:
            writes.append((key, row["lot_id"], 0, row["price"]))  # закрылся: цену помним для «было …»
    gone = [k for k in watch if k not in keep]  # убрали из избранного
    with db._lock:
        with c:
            c.executemany("INSERT INTO fav_watch (telegram_id, car_key, lot_id, is_open, price, updated_at) "
                          "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(telegram_id, car_key) DO UPDATE SET "
                          "lot_id = excluded.lot_id, is_open = excluded.is_open, price = excluded.price, "
                          "updated_at = excluded.updated_at",
                          [(telegram_id, k, lid, o, p, now_iso) for k, lid, o, p in writes])
            c.executemany("DELETE FROM fav_watch WHERE telegram_id = ? AND car_key = ?",
                          [(telegram_id, k) for k in gone])
            for kind, it, key, prev in events:
                c.execute("INSERT INTO notify_events (telegram_id, kind, lot_id, car_key, price, prev_price, "
                          "created_at, tg, email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (telegram_id, kind, it["id"], key, it["price"], prev, now_iso, *channels))
    return len(events)


def _candidates():
    """Пользователи с поисками (с уведомлениями) или с избранным."""
    c = conn()
    ids = {r[0] for r in c.execute("SELECT DISTINCT telegram_id FROM saved_searches WHERE notify = 1")}
    ids |= {r[0] for r in c.execute("SELECT DISTINCT telegram_id FROM favorites")}
    return sorted(ids)


def detect(now=None):
    """События для всех, кому положено. -> {"search": N, "fav": N, "rebaseline": N}."""
    now = now or lots.now_msk()
    now_iso = _iso(now)
    pairs = lots.open_items(lots.Favs([]), now)
    stats = {"search": 0, "fav": 0, "rebaseline": 0}
    for tid in _candidates():
        if not _eligible(tid):
            continue
        st_row = _settings_row(tid)
        st = settings(tid)
        last = _dt(st_row["last_pass_at"]) if st_row else None
        if last is None or now - last > datetime.timedelta(hours=REBASELINE_HOURS):
            # перерыв (Pro кончался, функцию выключали) или первый проход: всё текущее - известное
            for s in conn().execute("SELECT * FROM saved_searches WHERE telegram_id = ? AND notify = 1",
                                    (tid,)).fetchall():
                searches.baseline(tid, json.loads(s["params"]), now_iso, s["id"])
            if st["fav_events"]:
                _fav_events(tid, now, now_iso, (None, None))  # только запомнить состояние избранного
            stats["rebaseline"] += 1
        else:
            channels = _channels(st)
            stats["search"] += _search_events(tid, pairs, now_iso, channels)
            if st["fav_events"]:
                stats["fav"] += _fav_events(tid, now, now_iso, channels)
        _upsert(tid, now_iso, last_pass_at=now_iso)
    return stats


# ---------- тексты ----------

def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _rub(n):
    return f"{int(n):,}".replace(",", " ") + " ₽"


def _lot_line(lot_id, price, now, prev=None, kind="search"):
    lot = lots.get(lot_id)
    if lot is None:
        return None
    state = lots.current_state(lot, now)
    price = price if price is not None else state["price"]
    head = lot["name"] + (f" {lot['year']}" if lot.get("year") else "")
    bits = []
    if kind == "price_down" and prev:
        bits.append(f"цена снизилась: {_rub(prev)} → {_rub(price)}")
    elif kind == "relisted":
        bits.append("выставлена снова" + (f": {_rub(price)}" if price else "") +
                    (f" (было {_rub(prev)})" if prev and price and prev != price else ""))
    elif price:
        bits.append(_rub(price))
    gap = lots.gap_for(lot, price)
    if gap is not None and gap >= 1:
        bits.append(f"на {round(gap)}% ниже рынка" + (" (оценка может быть неточной)" if lot.get("estimate_uncertain") else ""))
    if state["deadline"]:
        bits.append(f"заявки до {state['deadline']:%d.%m}")
    return f"{head} — {', '.join(bits)}" if bits else head


def app_link(**params):
    """Адрес мини-аппа с параметром (?search=, ?lot=, ?tab=favs): кнопка в Telegram и ссылки в письме."""
    return f"{billing.site_url()}/?{urllib.parse.urlencode(params)}"


def tg_messages(events, now, names):
    """События пользователя -> [(текст, кнопка, адрес, [id событий])]: по сообщению на поиск и одно на избранное."""
    out = []
    by_search, fav = {}, []
    for e in events:
        (by_search.setdefault(e["search_id"], []) if e["kind"] == "search" else fav).append(e)
    for sid, evs in by_search.items():
        lines = [x for x in (_lot_line(e["lot_id"], e["price"], now) for e in evs) if x]
        if not lines:
            out.append((None, None, None, [e["id"] for e in evs]))
            continue
        title = "Новый лот" if len(lines) == 1 else "Новые лоты"
        text = f"🔔 {title} по поиску «{names.get(sid, 'Сохранённый поиск')}»\n\n" + \
            "\n".join(f"• {x}" for x in lines[:MAX_LINES])
        if len(lines) > MAX_LINES:
            text += f"\n…и ещё {len(lines) - MAX_LINES}"
        if len(lines) == 1:
            button, url = "Открыть лот", app_link(lot=evs[0]["lot_id"], src="notify")
        else:
            button, url = "Открыть подборку", app_link(search=sid, src="notify")
        out.append((text, button, url, [e["id"] for e in evs]))
    if fav:
        lines = [x for x in (_lot_line(e["lot_id"], e["price"], now, e["prev_price"], e["kind"]) for e in fav) if x]
        if lines:
            text = "⭐ Изменения в избранном\n\n" + "\n".join(f"• {x}" for x in lines[:MAX_LINES])
            if len(lines) > MAX_LINES:
                text += f"\n…и ещё {len(lines) - MAX_LINES}"
            if len(lines) == 1:
                button, url = "Открыть лот", app_link(lot=fav[0]["lot_id"], src="notify")
            else:
                button, url = "Открыть избранное", app_link(tab="favs", src="notify")
            out.append((text, button, url, [e["id"] for e in fav]))
        else:
            out.append((None, None, None, [e["id"] for e in fav]))
    return out


def _search_names(telegram_id):
    return {r["id"]: (r["name"] or searches.describe(json.loads(r["params"])))
            for r in conn().execute("SELECT * FROM saved_searches WHERE telegram_id = ?", (telegram_id,))}


def _send_tg(chat_id, text, button, url):
    telegram.call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True,
                  reply_markup={"inline_keyboard": [[{"text": button, "web_app": {"url": url}}]]})


def _mark(ids, column, value, now_iso):
    if not ids:
        return
    with db._lock:
        c = conn()
        with c:
            c.executemany(f"UPDATE notify_events SET {column} = ?, {column}_at = ? WHERE id = ?",
                          [(value, now_iso, i) for i in ids])


def _public_offer(lot_id):
    lot = lots.get(lot_id)
    return lot is not None and lot["trade"] == lots.TRADE_PUBLIC_OFFER


def deliver_tg(now=None, send=_send_tg):
    """Неотправленные события -> сообщения в Telegram. -> {"sent": N, "failed": N, "stopped": причина}."""
    now = now or lots.now_msk()
    now_iso = _iso(now)
    stats = {"sent": 0, "failed": 0, "stopped": None}
    c = conn()
    expired = [r[0] for r in c.execute("SELECT id FROM notify_events WHERE tg = 'pending' AND created_at < ?",
                                       (_iso(now - datetime.timedelta(hours=TG_TTL_HOURS)),))]
    _mark(expired, "tg", "expired", now_iso)
    rows = c.execute("SELECT * FROM notify_events WHERE tg = 'pending' ORDER BY telegram_id, id").fetchall()
    if now.astimezone(lots.MSK).hour < PUBLIC_OFFER_FROM_HOUR:
        rows = [r for r in rows if not _public_offer(r["lot_id"])]  # ждут утра (см. PUBLIC_OFFER_FROM_HOUR)
    by_user = {}
    for r in rows:
        by_user.setdefault(r["telegram_id"], []).append(r)
    for tid, evs in by_user.items():
        st = settings(tid)
        if not st["tg"] or not _eligible(tid):
            _mark([e["id"] for e in evs], "tg", "failed", now_iso)
            continue
        names = _search_names(tid)
        for text, button, url, ids in tg_messages(evs, now, names):
            if text is None:  # лоты пропали из базы - слать нечего
                _mark(ids, "tg", "expired", now_iso)
                continue
            try:
                send(tid, text, button, url)
            except telegram.TelegramError as e:
                desc = str(e).lower()
                if e.error_code == 403 or (e.error_code == 400 and "chat not found" in desc):
                    _upsert(tid, now_iso, tg_blocked_at=now_iso)  # бот заблокирован - больше не пишем
                    _mark([x["id"] for x in evs], "tg", "failed", now_iso)
                    stats["failed"] += 1
                    break
                if e.error_code == 429 or (e.error_code is None and "timed out" not in desc):
                    stats["stopped"] = str(e)  # лимит или нет связи с релеем - до следующего прохода
                    return stats
                if e.error_code is None:  # таймаут: сообщение, возможно, ушло - второй раз не шлём
                    _mark(ids, "tg", "sent", now_iso)
                    stats["sent"] += 1
                    continue
                _mark(ids, "tg", "failed", now_iso)
                stats["failed"] += 1
                print(f"[уведомления] Telegram не принял сообщение: {e}", flush=True)
                continue
            _mark(ids, "tg", "sent", now_iso)
            stats["sent"] += 1
            time.sleep(SEND_PAUSE_SECONDS)
    return stats


def email_text(telegram_id, events, now):
    names = _search_names(telegram_id)
    parts, by_search, fav = [], {}, []
    for e in events:
        (by_search.setdefault(e["search_id"], []) if e["kind"] == "search" else fav).append(e)
    total = 0
    for sid, evs in by_search.items():
        lines = [(x, e["lot_id"]) for e, x in ((e, _lot_line(e["lot_id"], e["price"], now)) for e in evs) if x]
        if lines:
            total += len(lines)
            parts.append(f"По поиску «{names.get(sid, 'Сохранённый поиск')}»:\n" +
                         "\n".join(f"• {x}\n  {app_link(lot=lid, src='email')}" for x, lid in lines))
    fav_lines = [(x, e["lot_id"]) for e, x in ((e, _lot_line(e["lot_id"], e["price"], now, e["prev_price"], e["kind"]))
                                               for e in fav) if x]
    if fav_lines:
        parts.append("Изменения в избранном:\n" +
                     "\n".join(f"• {x}\n  {app_link(lot=lid, src='email')}" for x, lid in fav_lines))
    if not parts:
        return None, None
    subject = (f"HonestLot: {total} {_plural(total, 'новый лот', 'новых лота', 'новых лотов')} по вашим поискам"
               if total else "HonestLot: изменения в избранном")
    text = ("Здравствуйте!\n\nНовое в HonestLot за сутки.\n\n" + "\n\n".join(parts) +
            f"\n\nНастроить поиски и уведомления: {app_link(tab='searches', src='email')}"
            f"\nОтписаться от этих писем: {unsubscribe_url(telegram_id)}\n")
    return subject, text


def deliver_email(now=None, send=mailer.send):
    """Раз в день после DIGEST_HOUR - письмо всем, у кого есть новое. -> писем отправлено."""
    now = now or lots.now_msk()
    msk = now.astimezone(lots.MSK)
    if msk.hour < DIGEST_HOUR:
        return 0
    now_iso, today, sent = _iso(now), msk.date(), 0
    c = conn()
    users = {r[0] for r in c.execute("SELECT DISTINCT telegram_id FROM notify_events WHERE email = 'pending'")}
    for tid in sorted(users):
        row = _settings_row(tid)
        last = _dt(row["email_digest_at"]) if row else None
        if last is not None and last.astimezone(lots.MSK).date() >= today:
            continue
        evs = c.execute("SELECT * FROM notify_events WHERE telegram_id = ? AND email = 'pending' ORDER BY id",
                        (tid,)).fetchall()
        st = settings(tid)
        if not st["email_on"] or not _eligible(tid):
            _mark([e["id"] for e in evs], "email", "failed", now_iso)
            continue
        subject, text = email_text(tid, evs, now)
        headers = {"List-Unsubscribe": f"<{unsubscribe_url(tid)}>",
                   "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
        if subject and not send(st["email"], subject, text, headers) and mailer.configured():
            continue  # не ушло (SMTP) - повтор при следующем проходе; без SMTP (локально) письмо - в логе
        _mark([e["id"] for e in evs], "email", "sent", now_iso)
        _upsert(tid, now_iso, email_digest_at=now_iso)
        sent += 1
    return sent


# ---------- проход и поток ----------

def run_pass(now=None):
    if not searches.enabled():
        return None
    with _pass_lock:
        now = now or lots.now_msk()
        out = detect(now)
        out["tg"] = deliver_tg(now)
        out["email"] = deliver_email(now)
        return out


def kick():
    """Новые данные на сервере (выгрузка с ПК, проверка статусов) - проход сразу."""
    _kick.set()


def _seconds_to_wake(now=None):
    """До ближайшего плана без новых данных: PUBLIC_OFFER_FROM_HOUR (отложенные ночью публичные
    предложения) или DIGEST_HOUR (письмо)."""
    now = (now or lots.now_msk()).astimezone(lots.MSK)
    times = []
    for hour in (PUBLIC_OFFER_FROM_HOUR, DIGEST_HOUR):
        at = now.replace(hour=hour, minute=1, second=0, microsecond=0)
        times.append(at if at > now else at + datetime.timedelta(days=1))
    return (min(times) - now).total_seconds()


def _loop():
    while True:
        _kick.wait(_seconds_to_wake())  # новые данные - сразу; без них - в 08:01 и 10:01
        _kick.clear()
        try:
            out = run_pass()
            if out and (out["search"] or out["fav"] or out["tg"]["sent"] or out["email"]):
                print(f"[уведомления] {out}", flush=True)
        except Exception as e:  # поток не должен умирать из-за одного прохода
            print(f"[уведомления] проход упал: {type(e).__name__}: {e}", flush=True)


def start():
    if searches.enabled():
        conn()
        threading.Thread(target=_loop, name="notify", daemon=True).start()


if __name__ == "__main__":
    print(run_pass())
