# -*- coding: utf-8 -*-
r"""
Подписка HonestLot Pro: оплата на сайте, автопродление, отмена, письма.

Решения владельца - wiki/monetization.md. Здесь только приём денег и учёт
подписки: что именно даёт Pro, пока не решено, поэтому никакие функции не
закрываются - API лишь сообщает, есть ли у пользователя Pro (is_pro).

ВКЛЮЧЕНИЕ. По умолчанию модуль выключен: HONESTLOT_PAYMENTS_ENABLED не "1" -
страницы /pay и /api/pay/* отвечают 404, фоновые списания не запускаются,
таблицы не создаются. Как включить - wiki/payments.md.

КАК ПЛАТЯТ. Страница оплаты - на сайте (honestlot.ru/pay), не в мини-аппе:
Telegram (правила для разработчиков, п. 6.2) и Apple (3.1.1, 3.1.3) запрещают
продавать цифровое в мини-аппе мимо Stars и вести из него на внешнюю оплату.
Как пользователь дойдёт до страницы - решает владелец (там же). Пользователь
на сайте узнаётся одним из способов:
  - Telegram Login Widget (заголовок "Authorization: tglogin <base64 JSON>");
  - initData мини-аппа ("tma <initData>") - если владелец всё же откроет
    страницу из мини-аппа (вариант "б" в monetization.md);
  - ссылка из письма ("link <токен>", подписанный LINK_SECRET, на 30 дней) -
    чтобы отменить подписку можно было прямо из письма, без входа.
  - токен веб-версии ("web <токен>", auth.make_web_token) - если пользователь уже
    вошёл на honestlot.ru, второй раз входить для оплаты не нужно.

ОПЛАТА. checkout: выбранный тариф -> первый платёж у провайдера
(pay_providers.py) с сохранением способа оплаты, если автопродление включено
(по умолчанию - да). Платёж подтверждается уведомлением провайдера (вебхук)
или опросом со страницы возврата; применяется ровно один раз (payments.applied).

АВТОПРОДЛЕНИЕ (фоновый поток, раз в час, run_due):
  - за REMIND_DAYS дня до конца периода - письмо: сумма, дата, как отменить;
  - в день окончания - списание по сохранённому способу; не прошло -
    повтор через сутки, всего RENEW_ATTEMPTS попыток, всё это время Pro
    остаётся (статус past_due); не прошли все - подписка заканчивается;
  - без автопродления подписка заканчивается в конце периода.
ОТМЕНА = перестать списывать и стереть у себя идентификатор способа оплаты
(у ЮKassa его не удалить, monetization.md). Доступ - до конца оплаченного периода.

ЦЕНЫ. Тарифы - PLANS. Ранняя цена - первым EARLY_SLOTS платящим и тем, кому её
дали вручную (python -m app.billing early <telegram_id>); держится, пока
подписка не прерывалась: при продлении берётся цена, зафиксированная в подписке.
Повышение цены действующим подписчикам (со следующего периода, письмо за 14
дней) - пока не реализовано: цена периода хранится в subscriptions.price.

ПОДАРОК. python -m app.billing grant <@ник|telegram_id> [месяцев]: бесплатный Pro (grant).
Есть подписка - срок продлевается с её конца; нет - подписка без автопродления за 0 ₽,
в конце срока просто закончится (письма не уходят: e-mail у подарка пустой).

Письма - mailer.py. Админка - python -m app.billing [list | early <id> | grant <@ник|id> [мес]].
"""
import base64
import calendar
import datetime
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import auth, db, mailer, pay_providers

MSK = datetime.timezone(datetime.timedelta(hours=3))

PLANS = {
    "month": {"title": "1 месяц", "months": 1, "price": 1490, "early": 990},
    "quarter": {"title": "3 месяца", "months": 3, "price": 3490, "early": 2490},
    "year": {"title": "12 месяцев", "months": 12, "price": 11900, "early": 7900},
}
EARLY_SLOTS = int(os.environ.get("HONESTLOT_EARLY_SLOTS", "100"))
REMIND_DAYS = 3
RENEW_ATTEMPTS = 3
RETRY_HOURS = 24
CHECK_EVERY_SECONDS = 3600
LINK_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id          INTEGER PRIMARY KEY,
    email                TEXT NOT NULL,
    plan_id              TEXT NOT NULL,
    price                INTEGER NOT NULL,      -- цена периода, зафиксированная для подписчика
    early                INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL,         -- active | past_due | expired
    autorenew            INTEGER NOT NULL DEFAULT 1,
    period_end           TEXT,                  -- ISO, МСК
    payment_method_id    TEXT,                  -- у провайдера; стираем при отмене
    payment_method_title TEXT,
    renew_attempts       INTEGER NOT NULL DEFAULT 0,
    next_attempt_at      TEXT,
    reminded_for         TEXT,                  -- period_end, о котором уже напомнили
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    order_id     TEXT PRIMARY KEY,              -- наш id, он же ключ идемпотентности у провайдера
    provider     TEXT NOT NULL,
    payment_id   TEXT,                          -- id у провайдера
    telegram_id  INTEGER NOT NULL,
    kind         TEXT NOT NULL,                 -- first | renewal
    plan_id      TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    early        INTEGER NOT NULL DEFAULT 0,
    email        TEXT,
    autorenew    INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL,                 -- pending | succeeded | canceled
    cancel_reason TEXT,
    applied      INTEGER NOT NULL DEFAULT 0,    -- подписка по нему уже продлена
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_payment_id ON payments (payment_id);
CREATE TABLE IF NOT EXISTS early_access (
    telegram_id INTEGER PRIMARY KEY,           -- ранняя цена вручную (ученики после курса и т.п.)
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_links (
    code        TEXT PRIMARY KEY,              -- метка ссылки t.me/honestlot_bot?startapp=<code> (edu_<автор>)
    months      INTEGER NOT NULL,              -- сколько Pro дарит ссылка
    owner       TEXT,                          -- кому выдана (автор курса) - только в базе: репозиторий публичный
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_grants (
    telegram_id INTEGER PRIMARY KEY,           -- одна подарочная ссылка на человека
    code        TEXT NOT NULL,
    until       TEXT,                          -- до какого дня Pro после подарка
    shown       INTEGER NOT NULL DEFAULT 0,    -- сообщение «вам подарен Pro» уже показано
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_grants (
    username    TEXT PRIMARY KEY,              -- ник Telegram в нижнем регистре, без @
    months      INTEGER NOT NULL,              -- подарок (gift) тому, кто ещё не открывал HonestLot (0 - бессрочно):
    note        TEXT,                          -- включится при первом входе (claim_pending)
    created_at  TEXT NOT NULL
);
"""


# ---------- настройки ----------

def enabled():
    return os.environ.get("HONESTLOT_PAYMENTS_ENABLED") == "1"


def site_url():
    return (os.environ.get("HONESTLOT_SITE_URL") or "https://honestlot.ru").rstrip("/")


_provider = None


def provider():
    global _provider
    if _provider is None:
        _provider = pay_providers.from_env(site_url())
    return _provider


def _link_secret():
    secret = os.environ.get("HONESTLOT_LINK_SECRET")
    if secret:
        return secret.encode()
    # запасной вариант - производный от токена бота (он и так секретный)
    return hashlib.sha256(b"honestlot-link:" + os.environ.get("HONESTLOT_BOT_TOKEN", "").encode()).digest()


_schema_ready = False


def _conn():
    global _schema_ready
    c = db.conn()
    if not _schema_ready:
        with db._lock:
            c.executescript(SCHEMA)
            c.commit()
        _schema_ready = True
    return c


# ---------- время ----------

def now_msk():
    return datetime.datetime.now(MSK)


def _iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def _dt(value):
    return datetime.datetime.fromisoformat(value) if value else None


def add_months(dt, months):
    month = dt.month - 1 + months
    year, month = dt.year + month // 12, month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _date_ru(dt):
    return dt.astimezone(MSK).strftime("%d.%m.%Y")


# ---------- ссылки из писем ----------

def link_token(telegram_id, now=None):
    exp = int((now or time.time()) + LINK_DAYS * 86400)
    payload = f"{telegram_id}.{exp}"
    sig = hmac.new(_link_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def check_link_token(token, now=None):
    try:
        tid, exp, sig = token.split(".")
        expected = hmac.new(_link_secret(), f"{tid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(sig, expected) and int(exp) > (now or time.time()):
            return int(tid)
    except (ValueError, AttributeError):
        pass
    raise auth.AuthError("ссылка устарела - откройте страницу подписки заново")


def manage_url(telegram_id):
    return f"{site_url()}/pay/manage.html#link={link_token(telegram_id)}"


# ---------- кто платит ----------

def user_from_header(authorization):
    """-> (telegram_id, данные пользователя или None). Три способа - см. докстринг модуля."""
    kind, _, value = (authorization or "").partition(" ")
    kind = kind.lower()
    bot_token = os.environ.get("HONESTLOT_BOT_TOKEN", "")
    if kind == "tma":
        user = auth.validate_init_data(value.strip(), bot_token)
        return int(user["id"]), user
    if kind == "tglogin":
        try:
            data = json.loads(base64.b64decode(value.strip()).decode())
        except (ValueError, UnicodeDecodeError):
            raise auth.AuthError("неверные данные входа")
        user = auth.validate_login_widget(data, bot_token)
        return int(user["id"]), user
    if kind == "link":
        return check_link_token(value.strip()), None
    if kind == "web":  # вошёл в веб-версию honestlot.ru - тот же вход подходит и для оплаты
        user = auth.check_web_token(value.strip())
        return int(user["id"]), user
    dev = os.environ.get("HONESTLOT_DEV_USER_ID")
    if dev:  # локальная разработка, как в auth.user_from_header
        return int(dev), {"id": int(dev), "username": "dev", "first_name": "Dev"}
    raise auth.AuthError("войдите через Telegram")


# ---------- цены ----------

def _early_for(c, telegram_id):
    """Ранняя цена: вручную выдана, или подписка с ранней ценой ещё не прерывалась,
    или платящих пока меньше EARLY_SLOTS."""
    if c.execute("SELECT 1 FROM early_access WHERE telegram_id = ?", (telegram_id,)).fetchone():
        return True
    sub = c.execute("SELECT early, status FROM subscriptions WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if sub and sub["status"] in ("active", "past_due"):
        return bool(sub["early"])
    payers = c.execute("SELECT COUNT(DISTINCT telegram_id) n FROM payments WHERE status = 'succeeded' "
                       "AND telegram_id != ?", (telegram_id,)).fetchone()["n"]
    return payers < EARLY_SLOTS


def offer(telegram_id):
    """Тарифы с ценами для этого пользователя."""
    c = _conn()
    early = _early_for(c, telegram_id) if telegram_id else False
    return {"early": early, "plans": [
        {"id": pid, "title": p["title"], "months": p["months"], "price": p["early"] if early else p["price"],
         "regular_price": p["price"]} for pid, p in PLANS.items()]}


# ---------- статус ----------

def subscription(telegram_id):
    row = _conn().execute("SELECT * FROM subscriptions WHERE telegram_id = ?", (telegram_id,)).fetchone()
    return dict(row) if row else None


def is_pro(telegram_id, now=None):
    sub = subscription(telegram_id) if enabled() else None
    if not sub:
        return False
    if sub["status"] == "past_due":
        return True  # идут повторы списания - доступ не отбираем
    return sub["status"] == "active" and _dt(sub["period_end"]) > (now or now_msk())


def public_status(telegram_id):
    sub = subscription(telegram_id)
    if not sub:
        return {"pro": False, "subscription": None}
    plan = PLANS.get(sub["plan_id"], {})
    return {"pro": is_pro(telegram_id), "subscription": {
        "status": sub["status"], "plan": sub["plan_id"], "plan_title": plan.get("title"),
        "price": sub["price"], "period_end": sub["period_end"],
        "autorenew": bool(sub["autorenew"] and sub["payment_method_id"]),
        "payment_method": sub["payment_method_title"] if sub["payment_method_id"] else None,
        "email": sub["email"], "created_at": sub["created_at"]}}


def payment_history(telegram_id, limit=24):
    """Платежи для страницы управления: прошедшие и непрошедшие продления. Брошенные первые
    оплаты (ушёл со страницы ЮKassa) и ещё не завершённые - не показываем."""
    rows = _conn().execute(
        "SELECT created_at, amount, plan_id, kind, status FROM payments WHERE telegram_id = ? "
        "AND (status = 'succeeded' OR (status = 'canceled' AND kind = 'renewal')) "
        "ORDER BY created_at DESC LIMIT ?", (telegram_id, limit)).fetchall()
    return [{"date": r["created_at"], "amount": r["amount"], "plan_title": PLANS.get(r["plan_id"], {}).get("title"),
             "renewal": r["kind"] == "renewal", "ok": r["status"] == "succeeded"} for r in rows]


# ---------- оплата ----------

def checkout(telegram_id, plan_id, email, autorenew):
    if plan_id not in PLANS:
        raise ValueError("неизвестный тариф")
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        raise ValueError("укажите e-mail - на него придут чек и письма о подписке")
    c = _conn()
    early = _early_for(c, telegram_id)
    plan = PLANS[plan_id]
    amount = plan["early"] if early else plan["price"]
    order_id = secrets.token_hex(16)
    now = _iso(now_msk())
    with db._lock:
        with c:
            c.execute("INSERT INTO payments (order_id, provider, telegram_id, kind, plan_id, amount, early, email, "
                      "autorenew, status, created_at, updated_at) VALUES (?, ?, ?, 'first', ?, ?, ?, ?, ?, 'pending', ?, ?)",
                      (order_id, provider().name, telegram_id, plan_id, amount, int(early), email, int(bool(autorenew)),
                       now, now))
    p = provider().create_payment(
        order_id, amount, f"HonestLot Pro, {plan['title']}", email, bool(autorenew),
        f"{site_url()}/pay/return.html?order={order_id}",
        {"order_id": order_id, "telegram_id": telegram_id, "plan": plan_id})
    _update_payment(order_id, p)
    return {"order_id": order_id, "confirmation_url": p.confirmation_url}


def _update_payment(order_id, p):
    c = _conn()  # до блокировки: первое обращение создаёт таблицы и само берёт db._lock
    with db._lock:
        with c:
            c.execute("UPDATE payments SET payment_id = ?, status = ?, cancel_reason = ?, updated_at = ? "
                            "WHERE order_id = ?", (p.id, p.status, p.cancel_reason, _iso(now_msk()), order_id))


def sync_order(order_id):
    """Свежий статус платежа у провайдера -> применить. Для страницы возврата и
    для платежей, по которым не пришло уведомление."""
    row = _conn().execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        return None
    if row["payment_id"] and row["status"] == "pending":
        apply(provider().get_payment(row["payment_id"]))
        row = _conn().execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    return dict(row)


def apply(p, now=None):
    """Состояние платежа от провайдера -> наша база. Идемпотентно: продление
    подписки по платежу - ровно один раз (payments.applied). Уведомление и опрос
    со страницы возврата могут прийти одновременно, поэтому платёж "забирается"
    (applied 0 -> 1) и подписка меняется в одной транзакции под db._lock - и
    чтения тоже под ней: соединение с базой одно на процесс."""
    now = now or now_msk()
    c = _conn()
    with db._lock:
        with c:
            row = c.execute("SELECT * FROM payments WHERE payment_id = ?", (p.id,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE payments SET status = ?, cancel_reason = ?, updated_at = ? WHERE order_id = ?",
                      (p.status, p.cancel_reason, _iso(now_msk()), row["order_id"]))
            final = p.status == "succeeded" or (p.status == "canceled" and row["kind"] == "renewal")
            claimed = final and c.execute("UPDATE payments SET applied = 1 WHERE order_id = ? AND applied = 0",
                                          (row["order_id"],)).rowcount
            if not claimed:
                return p.status  # не окончательный статус или уже применён другим запросом
            if p.status == "succeeded":
                end, renewing = _extend(c, row, p, now)
    if p.status == "canceled":
        _renewal_failed(row, p, now)
        return "failed"
    _mail_paid(row, PLANS[row["plan_id"]], end, renewing)
    return "succeeded"


def _extend(c, row, p, now):
    """Продлить подписку по успешному платежу (вызывается под db._lock, в транзакции)."""
    plan = PLANS[row["plan_id"]]
    sub = c.execute("SELECT * FROM subscriptions WHERE telegram_id = ?", (row["telegram_id"],)).fetchone()
    start = now
    if sub and row["kind"] == "renewal":
        # автопродление - строго с конца прошлого периода: пока шли повторы
        # списания, доступ сохранялся, и даты не должны "уползать"
        start = _dt(sub["period_end"])
    elif sub and sub["status"] in ("active", "past_due") and _dt(sub["period_end"]) > now:
        start = _dt(sub["period_end"])  # досрочная оплата - с конца текущего периода
    end = add_months(start, plan["months"])
    autorenew = row["autorenew"] if row["kind"] == "first" else (sub["autorenew"] if sub else 1)
    method_id = p.payment_method_id or (sub["payment_method_id"] if sub and row["kind"] == "renewal" else None)
    method_title = p.payment_method_title if p.payment_method_id else (sub["payment_method_title"] if sub else None)
    email = row["email"] or (sub["email"] if sub else "")
    renewing = bool(autorenew and method_id)
    if sub:
        c.execute("UPDATE subscriptions SET email = ?, plan_id = ?, price = ?, early = ?, status = 'active', "
                  "autorenew = ?, period_end = ?, payment_method_id = ?, payment_method_title = ?, "
                  "renew_attempts = 0, next_attempt_at = NULL, updated_at = ? WHERE telegram_id = ?",
                  (email, row["plan_id"], row["amount"], row["early"], int(renewing), _iso(end),
                   method_id if autorenew else None, method_title, _iso(now), row["telegram_id"]))
    else:
        c.execute("INSERT INTO subscriptions (telegram_id, email, plan_id, price, early, status, autorenew, "
                  "period_end, payment_method_id, payment_method_title, created_at, updated_at) "
                  "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
                  (row["telegram_id"], email, row["plan_id"], row["amount"], row["early"], int(renewing),
                   _iso(end), method_id if autorenew else None, method_title, _iso(now), _iso(now)))
    return end, renewing


def cancel(telegram_id, now=None):
    """Отключить автопродление: больше не списываем, идентификатор способа оплаты стираем.
    Доступ - до конца оплаченного периода."""
    sub = subscription(telegram_id)
    if not sub:
        raise ValueError("подписки нет")
    now = now or now_msk()
    c = _conn()
    with db._lock:
        with c:
            c.execute("UPDATE subscriptions SET autorenew = 0, payment_method_id = NULL, "
                            "next_attempt_at = NULL, updated_at = ? WHERE telegram_id = ?", (_iso(now), telegram_id))
    if sub["autorenew"] and sub["payment_method_id"]:
        end = _dt(sub["period_end"])
        card = f" ({sub['payment_method_title']})" if sub["payment_method_title"] else ""
        mailer.send(sub["email"], "Подписка HonestLot Pro отменена",
                    f"Автопродление подписки HonestLot Pro отключено, способ оплаты{card} отвязан - "
                    f"больше списаний не будет.\n\n"
                    f"Доступ к Pro сохранится до {_date_ru(end)} включительно.\n"
                    f"Возобновить подписку можно на странице: {site_url()}/pay/\n")
    return public_status(telegram_id)


# ---------- автопродление ----------

def run_due(now=None):
    """Напоминания, списания и окончания подписок. Вызывается фоновым потоком раз
    в час; now - для проверки "во времени"."""
    now = now or now_msk()
    c = _conn()
    subs = [dict(r) for r in c.execute("SELECT * FROM subscriptions WHERE status IN ('active', 'past_due')")]
    for sub in subs:
        end = _dt(sub["period_end"])
        renewing = sub["autorenew"] and sub["payment_method_id"]
        if not renewing:
            if now >= end:
                _expire(sub, now, "ended")
            continue
        if sub["status"] == "active" and end - now <= datetime.timedelta(days=REMIND_DAYS) \
                and now < end and sub["reminded_for"] != sub["period_end"]:
            _mail_reminder(sub, end)
            with db._lock:
                with c:
                    c.execute("UPDATE subscriptions SET reminded_for = ? WHERE telegram_id = ?",
                              (sub["period_end"], sub["telegram_id"]))
        due = now >= end and (not sub["next_attempt_at"] or now >= _dt(sub["next_attempt_at"]))
        if due:
            _charge(sub, now)
    # платежи-продления, по которым так и не пришло уведомление
    for row in c.execute("SELECT order_id FROM payments WHERE status = 'pending' AND kind = 'renewal' "
                         "AND payment_id IS NOT NULL").fetchall():
        try:
            sync_order(row["order_id"])
        except pay_providers.ProviderError as e:
            print(f"Продление {row['order_id']}: {e}", flush=True)


def _charge(sub, now):
    plan = PLANS[sub["plan_id"]]
    attempt = sub["renew_attempts"] + 1
    order_id = f"renew-{sub['telegram_id']}-{sub['period_end'][:10]}-{attempt}"
    c = _conn()
    if c.execute("SELECT 1 FROM payments WHERE order_id = ?", (order_id,)).fetchone():
        return  # эта попытка уже сделана, ждём её результат
    with db._lock:
        with c:
            c.execute("INSERT INTO payments (order_id, provider, telegram_id, kind, plan_id, amount, early, email, "
                      "autorenew, status, created_at, updated_at) VALUES (?, ?, ?, 'renewal', ?, ?, ?, ?, 1, 'pending', ?, ?)",
                      (order_id, provider().name, sub["telegram_id"], sub["plan_id"], sub["price"], sub["early"],
                       sub["email"], _iso(now), _iso(now)))
    try:
        p = provider().charge_saved(order_id, sub["price"], f"HonestLot Pro, {plan['title']} (продление)",
                                    sub["email"], sub["payment_method_id"],
                                    {"order_id": order_id, "telegram_id": sub["telegram_id"], "plan": sub["plan_id"]})
    except pay_providers.ProviderError as e:
        print(f"Продление {sub['telegram_id']}: {e}", flush=True)
        if e.permanent:
            # провайдер отказал в запросе (способ оплаты отвязан и т.п.) - неудачная попытка
            with db._lock:
                with c:
                    c.execute("UPDATE payments SET status = 'canceled', cancel_reason = ?, applied = 1, "
                              "updated_at = ? WHERE order_id = ?", (str(e)[:200], _iso(now), order_id))
            _renewal_failed({"telegram_id": sub["telegram_id"]}, None, now)
            return
        # сбой связи или у провайдера - не отказ банка: удаляем попытку, повторим через час
        with db._lock:
            with c:
                c.execute("DELETE FROM payments WHERE order_id = ?", (order_id,))
        return
    _update_payment(order_id, p)
    if p.status in ("succeeded", "canceled"):
        apply(p, now)


def _renewal_failed(row, p, now):
    sub = subscription(row["telegram_id"])
    if not sub:
        return
    attempts = sub["renew_attempts"] + 1
    c = _conn()
    if attempts >= RENEW_ATTEMPTS:
        _expire(sub, now, "payment_failed")
        return
    with db._lock:
        with c:
            c.execute("UPDATE subscriptions SET status = 'past_due', renew_attempts = ?, next_attempt_at = ?, "
                      "updated_at = ? WHERE telegram_id = ?",
                      (attempts, _iso(now + datetime.timedelta(hours=RETRY_HOURS)), _iso(now), row["telegram_id"]))
    mailer.send(sub["email"], "Не удалось продлить HonestLot Pro",
                f"Не получилось списать {sub['price']} ₽ за продление HonestLot Pro "
                f"({sub['payment_method_title'] or 'сохранённый способ оплаты'}).\n\n"
                f"Попробуем ещё раз через сутки (попытка {attempts + 1} из {RENEW_ATTEMPTS}); доступ к Pro пока сохраняется.\n"
                f"Оплатить другим способом или отключить продление: {manage_url(sub['telegram_id'])}\n")


def _expire(sub, now, reason):
    c = _conn()
    with db._lock:
        with c:
            c.execute("UPDATE subscriptions SET status = 'expired', autorenew = 0, payment_method_id = NULL, "
                      "next_attempt_at = NULL, updated_at = ? WHERE telegram_id = ?", (_iso(now), sub["telegram_id"]))
    why = ("списать оплату за продление не удалось" if reason == "payment_failed"
           else "оплаченный период закончился")
    mailer.send(sub["email"], "Подписка HonestLot Pro закончилась",
                f"Подписка HonestLot Pro закончилась: {why}.\n\n"
                f"Оформить снова: {site_url()}/pay/\n")


# ---------- письма ----------

def _mail_paid(row, plan, end, renewing):
    renew = (f"Подписка продлится автоматически {_date_ru(end)}: спишем {row['amount']} ₽ за "
             f"{plan['title']}. За {REMIND_DAYS} дня напомним письмом.\n"
             if renewing else "Автопродление выключено - подписка закончится в конце периода.\n")
    mailer.send(row["email"], "Оплата HonestLot Pro прошла",
                f"Спасибо! Оплата {row['amount']} ₽ за HonestLot Pro ({plan['title']}) прошла.\n\n"
                f"Pro действует до {_date_ru(end)} включительно.\n{renew}\n"
                f"Управление подпиской, отмена и отвязка карты: {manage_url(row['telegram_id'])}\n")


def _mail_reminder(sub, end):
    plan = PLANS[sub["plan_id"]]
    mailer.send(sub["email"], "Скоро продление HonestLot Pro",
                f"{_date_ru(end)} подписка HonestLot Pro продлится автоматически: спишем {sub['price']} ₽ "
                f"за {plan['title']} ({sub['payment_method_title'] or 'сохранённый способ оплаты'}).\n\n"
                f"Отменить подписку и отвязать карту: {manage_url(sub['telegram_id'])}\n")


# ---------- фоновый поток ----------

def _loop():
    while True:
        try:
            run_due()
        except Exception:
            print("Подписки: ошибка фоновой проверки\n" + traceback.format_exc(), flush=True)
        time.sleep(CHECK_EVERY_SECONDS)


def start():
    if enabled():
        _conn()
        threading.Thread(target=_loop, name="billing", daemon=True).start()


# ---------- HTTP ----------

router = APIRouter()


def _guard():
    if not enabled():
        raise HTTPException(status_code=404)


def _who(authorization):
    try:
        return user_from_header(authorization)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


class CheckoutPayload(BaseModel):
    plan: str
    email: str
    autorenew: bool = True
    consent: bool = False


@router.get("/api/pay/offer")
def api_offer(authorization: str = Header(default="")):
    _guard()
    tid, user = _who(authorization)
    return {**offer(tid), **public_status(tid), "user": user and {"first_name": user.get("first_name"),
                                                                    "username": user.get("username")},
            "offer_url": os.environ.get("HONESTLOT_OFFER_URL") or "/offer",  # страницы site.py
            "privacy_url": os.environ.get("HONESTLOT_PRIVACY_URL") or "/privacy"}


@router.post("/api/pay/checkout")
def api_checkout(payload: CheckoutPayload, authorization: str = Header(default="")):
    _guard()
    tid, user = _who(authorization)
    if not payload.consent:
        raise HTTPException(status_code=400, detail="нужно согласие с офертой и обработкой персональных данных")
    if user:
        db.touch_user(tid, user.get("username"), user.get("first_name"), _iso(now_msk()))
        claim_pending(tid, user.get("username"))
        claim_promo(tid, user.get("start_param"))
    try:
        return checkout(tid, payload.plan, payload.email, payload.autorenew)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except pay_providers.ProviderError as e:
        print(f"Оплата: {e}", flush=True)
        raise HTTPException(status_code=502, detail="платёжный сервис не ответил - попробуйте ещё раз")


@router.get("/api/pay/order/{order_id}")
def api_order(order_id: str):
    _guard()
    try:
        row = sync_order(order_id)
    except pay_providers.ProviderError:
        row = _conn().execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
        row = dict(row) if row else None
    if not row:
        raise HTTPException(status_code=404)
    sub = subscription(row["telegram_id"])
    return {"status": row["status"], "amount": row["amount"], "plan_title": PLANS[row["plan_id"]]["title"],
            "period_end": sub["period_end"] if sub and row["status"] == "succeeded" else None}


@router.get("/api/pay/status")
def api_status(authorization: str = Header(default="")):
    _guard()
    tid, _ = _who(authorization)
    return {**public_status(tid), "payments": payment_history(tid)}


@router.post("/api/pay/cancel")
def api_cancel(authorization: str = Header(default="")):
    _guard()
    tid, _ = _who(authorization)
    try:
        return cancel(tid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/pay/webhook/{provider_name}")
async def api_webhook(provider_name: str, request: Request):
    _guard()
    if provider_name != provider().name:
        raise HTTPException(status_code=404)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400)
    payment_id = provider().payment_id_from_webhook(body)
    if payment_id:
        try:
            # уведомлению не верим - перечитываем платёж у провайдера
            await run_in_threadpool(lambda: apply(provider().get_payment(payment_id)))
        except pay_providers.ProviderError as e:
            print(f"Вебхук {payment_id}: {e}", flush=True)
            raise HTTPException(status_code=502)  # провайдер повторит уведомление
    return {"ok": True}


@router.get("/api/pay/fake/confirm", response_class=HTMLResponse)
def fake_confirm_page(id: str):
    _guard()
    if provider().name != "fake":
        raise HTTPException(status_code=404)
    id = html.escape(id, quote=True)
    return (f"<!doctype html><meta charset=utf-8><title>Тестовая оплата</title>"
            f"<body style='font-family:sans-serif;max-width:420px;margin:40px auto'>"
            f"<h2>Тестовая оплата</h2><p>Платёж {id}. Денег не списываем.</p>"
            f"<form method=post action='/api/pay/fake/confirm?id={id}&paid=1'><button>Оплатить</button></form><br>"
            f"<form method=post action='/api/pay/fake/confirm?id={id}&paid=0'><button>Отказаться</button></form>")


@router.post("/api/pay/fake/confirm")
def fake_confirm(id: str, paid: int):
    _guard()
    if provider().name != "fake":
        raise HTTPException(status_code=404)
    return_url = provider().finish(id, bool(paid))
    apply(provider().get_payment(id))  # как будто пришло уведомление
    return RedirectResponse(return_url, status_code=303)


# ---------- подарок: бесплатный Pro ----------

def grant(who, months=1, now=None):
    """Бесплатный Pro на months месяцев. who - telegram_id или @ник (пользователь должен хоть раз
    открыть мини-апп или сайт). -> (telegram_id, новый конец срока)."""
    now = now or now_msk()
    c = _conn()
    if str(who).startswith("@"):
        row = c.execute("SELECT telegram_id FROM users WHERE lower(username) = ?", (str(who)[1:].lower(),)).fetchone()
        if not row:
            raise ValueError(f"{who} нет в базе - пусть откроет мини-апп или сайт")
        tid = row["telegram_id"]
    else:
        tid = int(who)
    sub = subscription(tid)
    early = int(_early_for(c, tid))  # подарок не отнимает раннюю цену, если она человеку полагается
    with db._lock:
        with c:
            if sub and sub["status"] in ("active", "past_due") and _dt(sub["period_end"]) > now:
                # действующая подписка (в том числе платная с автопродлением) - продлеваем с её конца
                end = add_months(_dt(sub["period_end"]), months)
                c.execute("UPDATE subscriptions SET period_end = ?, status = 'active', renew_attempts = 0, "
                          "next_attempt_at = NULL, updated_at = ? WHERE telegram_id = ?", (_iso(end), _iso(now), tid))
            elif sub:
                end = add_months(now, months)
                c.execute("UPDATE subscriptions SET plan_id = 'month', price = 0, early = ?, status = 'active', "
                          "autorenew = 0, period_end = ?, payment_method_id = NULL, payment_method_title = NULL, "
                          "renew_attempts = 0, next_attempt_at = NULL, reminded_for = NULL, updated_at = ? "
                          "WHERE telegram_id = ?", (early, _iso(end), _iso(now), tid))
            else:
                end = add_months(now, months)
                c.execute("INSERT INTO subscriptions (telegram_id, email, plan_id, price, early, status, autorenew, "
                          "period_end, created_at, updated_at) VALUES (?, '', 'month', 0, ?, 'active', 0, ?, ?, ?)",
                          (tid, early, _iso(end), _iso(now), _iso(now)))
    return tid, end


# Бессрочный Pro (подарок авторам курсов и своим, 17.10.2026; так же с 14.10.2026 у владельца):
# подписка за 0 ₽ без автопродления и без карты до FOREVER.
FOREVER = datetime.datetime(2099, 12, 31, 23, 59, tzinfo=MSK)


def _who_id(who):
    """telegram_id по @нику или числу; нет в базе - ValueError."""
    if str(who).startswith("@"):
        row = _conn().execute("SELECT telegram_id FROM users WHERE lower(username) = ?", (str(who)[1:].lower(),)).fetchone()
        if not row:
            raise ValueError(f"{who} нет в базе - пусть откроет мини-апп или сайт")
        return row["telegram_id"]
    return int(who)


def grant_forever(who, now=None):
    """Бессрочный Pro: подписка за 0 ₽ до FOREVER, без автопродления и сохранённой карты (с карты больше
    ничего не спишется). -> (telegram_id, FOREVER)."""
    now = now or now_msk()
    tid = _who_id(who)
    c = _conn()
    early = int(_early_for(c, tid))
    with db._lock:
        with c:
            if subscription(tid):
                c.execute("UPDATE subscriptions SET plan_id = 'month', price = 0, status = 'active', autorenew = 0, "
                          "period_end = ?, payment_method_id = NULL, payment_method_title = NULL, renew_attempts = 0, "
                          "next_attempt_at = NULL, reminded_for = NULL, updated_at = ? WHERE telegram_id = ?",
                          (_iso(FOREVER), _iso(now), tid))
            else:
                c.execute("INSERT INTO subscriptions (telegram_id, email, plan_id, price, early, status, autorenew, "
                          "period_end, created_at, updated_at) VALUES (?, '', 'month', 0, ?, 'active', 0, ?, ?, ?)",
                          (tid, early, _iso(FOREVER), _iso(now), _iso(now)))
    return tid, FOREVER


def gift_forever(who, now=None):
    """Как gift, но бессрочно: кто в базе - сразу, кто ещё не открывал HonestLot - при первом входе."""
    try:
        tid, _ = grant_forever(who, now)
        return f"Pro бессрочно: {who} (telegram_id {tid})"
    except ValueError:
        if not str(who).startswith("@"):
            raise
    name = str(who)[1:].strip().lower()
    c = _conn()
    with db._lock:
        with c:
            c.execute("INSERT OR REPLACE INTO pending_grants (username, months, created_at) VALUES (?, 0, ?)",
                      (name, _iso(now or now_msk())))
    return f"{who} ещё не открывал HonestLot - бессрочный Pro включится при первом входе"


def gift(who, months=1, now=None):
    """Подарок Pro (16.10.2026): как grant, но если человек ещё ни разу не открывал мини-апп или сайт
    (его нет в базе, а Pro привязан к telegram_id), подарок записывается на ник и включается сам при
    первом входе (claim_pending). -> текст для консоли."""
    try:
        tid, end = grant(who, months, now)
        return f"Pro подарен: {who} (telegram_id {tid}) до {_date_ru(end)} включительно"
    except ValueError:
        if not str(who).startswith("@"):
            raise
    name = str(who)[1:].strip().lower()
    c = _conn()
    with db._lock:
        with c:
            row = c.execute("SELECT months FROM pending_grants WHERE username = ?", (name,)).fetchone()
            if row and row["months"] == 0:  # уже ждёт бессрочный - месяц ничего не добавит
                return f"{who} уже ждёт бессрочный Pro"
            c.execute("INSERT OR REPLACE INTO pending_grants (username, months, created_at) VALUES (?, ?, ?)",
                      (name, months + (row["months"] if row else 0), _iso(now or now_msk())))
    return f"{who} ещё не открывал HonestLot - Pro на {months} мес. включится при первом входе"


# ---------- подарочные ссылки для авторов курсов (17.10.2026) ----------
# Автор курса получает свою ссылку t.me/honestlot_bot?startapp=edu_<автор> (или honestlot.ru/?startapp=...):
# ученик, открывший по ней мини-апп или сайт, сразу получает Pro на months месяцев - без кнопок и
# промокодов. Метки - в таблице promo_links (python -m app.billing promo add ...), не в коде: репозиторий
# публичный. Одна подарочная ссылка на человека (promo_grants): по второй ссылке второго месяца нет.

def promo(code):
    """Действующая подарочная ссылка с такой меткой или None."""
    if not code:
        return None
    return _conn().execute("SELECT * FROM promo_links WHERE code = ? AND active = 1", (str(code),)).fetchone()


def claim_promo(tid, code):
    """Вход по подарочной ссылке: Pro на months месяцев, один раз на человека. -> конец срока или None.
    Метка не подарочная, уже дарили или ошибка - None; вход это не ломает."""
    try:
        link = promo(code)
        if not link:
            return None
        c = _conn()
        with db._lock:
            with c:
                fresh = c.execute("INSERT OR IGNORE INTO promo_grants (telegram_id, code, created_at) VALUES (?, ?, ?)",
                                  (tid, link["code"], _iso(now_msk()))).rowcount == 1
        if not fresh:
            return None
        try:
            _, end = grant(tid, link["months"])
        except Exception:
            with db._lock:
                with c:
                    c.execute("DELETE FROM promo_grants WHERE telegram_id = ?", (tid,))
            raise
        with db._lock:
            with c:
                c.execute("UPDATE promo_grants SET until = ? WHERE telegram_id = ?", (_iso(end), tid))
        print(f"[подарок по ссылке] {link['code']}: telegram_id {tid} - Pro до {_date_ru(end)}", flush=True)
        return end
    except Exception as e:
        print(f"[подарок по ссылке] {code}: не выдан ({type(e).__name__}: {e})", flush=True)
        return None


def promo_notice(tid):
    """Подарок по ссылке, о котором человеку ещё не сказали: {months, until} (один раз) или None."""
    c = _conn()
    with db._lock:
        with c:
            row = c.execute("SELECT g.until, l.months FROM promo_grants g JOIN promo_links l USING (code) "
                            "WHERE g.telegram_id = ? AND g.shown = 0 AND g.until IS NOT NULL", (tid,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE promo_grants SET shown = 1 WHERE telegram_id = ?", (tid,))
    return {"months": row["months"], "until": _date_ru(_dt(row["until"]))}


def claim_pending(tid, username):
    """Вход пользователя: если на его ник есть отложенный подарок (gift) - выдать Pro и снять запись.
    Ошибки не мешают входу. Поиск по ключу таблицы - на каждый вход это незаметно."""
    name = (username or "").strip().lower()
    if not name:
        return
    try:
        c = _conn()
        with db._lock:
            with c:
                row = c.execute("SELECT months FROM pending_grants WHERE username = ?", (name,)).fetchone()
                if not row or c.execute("DELETE FROM pending_grants WHERE username = ?", (name,)).rowcount != 1:
                    return
        _, end = grant_forever(tid) if row["months"] == 0 else grant(tid, row["months"])
        print(f"[подарок] @{name} (telegram_id {tid}) открыл HonestLot - Pro до {_date_ru(end)}", flush=True)
    except Exception as e:  # вход важнее подарка
        print(f"[подарок] @{name}: не выдан ({type(e).__name__}: {e})", flush=True)


# ---------- админка: python -m app.billing [list | early <telegram_id> [заметка] | grant <@ник|id> [мес]
# | gift <@ник> [<@ник> ...] [мес]] ----------

def _cli(argv):
    c = _conn()
    if argv[:1] == ["early"] and len(argv) >= 2:
        with db._lock:
            with c:
                c.execute("INSERT OR REPLACE INTO early_access (telegram_id, note, created_at) VALUES (?, ?, ?)",
                          (int(argv[1]), " ".join(argv[2:]) or None, _iso(now_msk())))
        print(f"Ранняя цена выдана: {argv[1]}")
        return
    if argv[:1] == ["promo"]:
        # promo add <метка> [@кому] [мес] | promo off <метка> | promo [list]
        if argv[1:2] == ["add"] and len(argv) >= 3:
            months = int(argv[-1]) if argv[-1].isdigit() and len(argv) > 3 else 1
            owner = next((a for a in argv[3:] if not a.isdigit()), None)
            with db._lock:
                with c:
                    c.execute("INSERT OR REPLACE INTO promo_links (code, months, owner, active, created_at) "
                              "VALUES (?, ?, ?, 1, ?)", (argv[2], months, owner, _iso(now_msk())))
            print(f"Ссылка: https://t.me/honestlot_bot?startapp={argv[2]}  (сайт: https://honestlot.ru/?startapp="
                  f"{argv[2]}) - Pro на {months} мес." + (f", для {owner}" if owner else ""))
            return
        if argv[1:2] == ["off"] and len(argv) >= 3:
            with db._lock:
                with c:
                    n = c.execute("UPDATE promo_links SET active = 0 WHERE code = ?", (argv[2],)).rowcount
            print(f"Ссылка {argv[2]} выключена" if n else f"Ссылки {argv[2]} нет")
            return
        rows = c.execute("SELECT l.*, (SELECT COUNT(*) FROM users u WHERE u.source = l.code) came, "
                         "(SELECT COUNT(*) FROM promo_grants g WHERE g.code = l.code) got "
                         "FROM promo_links l ORDER BY l.created_at").fetchall()
        print(f"{'метка':<22} {'кому':<20} {'мес':>3} {'пришли':>7} {'получили Pro':>13}  ссылка")
        for r in rows:
            print(f"{r['code']:<22} {(r['owner'] or '-'):<20} {r['months']:>3} {r['came']:>7} {r['got']:>13}  "
                  f"https://t.me/honestlot_bot?startapp={r['code']}" + ("" if r["active"] else "  (выключена)"))
        return
    if argv[:1] == ["forever"] and len(argv) >= 2:  # forever @ник [@ник ...] - бессрочный Pro
        for who in argv[1:]:
            print(gift_forever(who if who.startswith("@") or who.isdigit() else "@" + who))
        return
    if argv[:1] == ["gift"] and len(argv) >= 2:
        months = int(argv[-1]) if argv[-1].isdigit() else 1
        for who in [a for a in argv[1:] if not a.isdigit()]:
            print(gift(who if who.startswith("@") or who.isdigit() else "@" + who, months))
        waiting = c.execute("SELECT username, months FROM pending_grants ORDER BY created_at").fetchall()
        if waiting:
            print("Ждут первого входа: " + ", ".join(
                f"@{r['username']} ({'бессрочно' if r['months'] == 0 else str(r['months']) + ' мес.'})" for r in waiting))
        return
    if argv[:1] == ["grant"] and len(argv) >= 2:
        tid, end = grant(argv[1], int(argv[2]) if len(argv) > 2 else 1)
        print(f"Pro подарен: {argv[1]} (telegram_id {tid}) до {_date_ru(end)} включительно")
        return
    rows = c.execute("SELECT s.*, u.username FROM subscriptions s LEFT JOIN users u USING (telegram_id) "
                     "ORDER BY s.period_end DESC").fetchall()
    print(f"{'telegram_id':<12} {'username':<18} {'тариф':<8} {'цена':>6} {'статус':<9} {'до':<11} автопрод.  e-mail")
    for r in rows:
        print(f"{r['telegram_id']:<12} {('@' + r['username']) if r['username'] else '-':<18} {r['plan_id']:<8} "
              f"{r['price']:>6} {r['status']:<9} {(r['period_end'] or '')[:10]:<11} "
              f"{'да' if r['autorenew'] and r['payment_method_id'] else 'нет':<10} {r['email']}")
    paid = c.execute("SELECT COUNT(*) n, COALESCE(SUM(amount), 0) s FROM payments WHERE status = 'succeeded'").fetchone()
    print(f"\nПодписок: {len(rows)}, успешных платежей: {paid['n']} на {paid['s']} ₽")


if __name__ == "__main__":
    _cli(sys.argv[1:])
