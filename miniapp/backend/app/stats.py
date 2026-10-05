# -*- coding: utf-8 -*-
r"""
Сводка по пользователям и активности мини-аппа - печатает в консоль.

На сервере (с ПК, одной командой):
  ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats"
Список пользователей (id, username, имя, источник, даты), новые сверху:
  ... python -m app.stats users            - все
  ... python -m app.stats users podbor_post1 - только пришедшие по этой метке
  ... python -m app.stats users -          - только "без метки"
Локально (база miniapp/backend/data/honestlot.db):
  python -m app.stats   (из папки miniapp/backend)

Что считаем и зачем - минимум, по которому видно, живой ли продукт:
  - пользователи по источникам (users.source - метка ?startapp=... из
    ссылки; "без метки" - вошли через кнопку меню бота или поиск);
  - новые пользователи и активные по дням (DAU = открыл мини-апп хоть раз
    за день), активные за 7 и 30 дней;
  - удержание: сколько из пришедших 7+ дней назад вернулись позже первого дня;
  - просмотры карточек, добавления в избранное и переходы на сайт торгов
    (source_click - главный сигнал: человек пошёл разбираться с лотом);
  - самые просматриваемые лоты;
  - "Поделиться": сколько раз нажимали и кто привёл новых пользователей
    (users.referred_by; пришедшие по ссылке на лот - источник "share").
Только чтение, в базу ничего не пишет.
"""
import datetime
import sqlite3
import sys

from . import db

DAYS = 14


def _q(c, sql, args=()):
    return c.execute(sql, args).fetchall()


def run():
    c = sqlite3.connect(db.db_path())
    c.row_factory = sqlite3.Row
    msk = datetime.timezone(datetime.timedelta(hours=3))
    today = datetime.datetime.now(msk).date()
    since = (today - datetime.timedelta(days=DAYS - 1)).isoformat()

    total = _q(c, "SELECT COUNT(*) n FROM users")[0]["n"]
    print(f"Пользователей всего: {total}")
    print("\nПо источникам (первый вход):")
    for r in _q(c, "SELECT COALESCE(source, 'без метки') s, COUNT(*) n FROM users GROUP BY s ORDER BY n DESC"):
        print(f"  {r['s']:<30} {r['n']}")

    def active(days):
        start = (today - datetime.timedelta(days=days - 1)).isoformat()
        return _q(c, "SELECT COUNT(DISTINCT telegram_id) n FROM events WHERE type = 'open' AND created_at >= ?",
                  (start,))[0]["n"]
    print(f"\nАктивных (открывали мини-апп): сегодня {active(1)}, за 7 дней {active(7)}, за 30 дней {active(30)}")

    old = _q(c, "SELECT telegram_id, substr(created_at, 1, 10) d FROM users WHERE created_at < ?",
             ((today - datetime.timedelta(days=7)).isoformat(),))
    if old:
        returned = 0
        for u in old:
            later = _q(c, "SELECT 1 FROM events WHERE telegram_id = ? AND type = 'open' AND substr(created_at, 1, 10) > ? LIMIT 1",
                       (u["telegram_id"], u["d"]))
            returned += bool(later)
        print(f"Вернулись после первого дня (из пришедших 7+ дней назад): {returned} из {len(old)}")

    print(f"\nПо дням за {DAYS} дней: новые / открывали / просмотры лотов / в избранное / переходы на сайт")
    new_by_day = {r["d"]: r["n"] for r in _q(c, "SELECT substr(created_at, 1, 10) d, COUNT(*) n FROM users WHERE created_at >= ? GROUP BY d", (since,))}
    ev = {}
    for r in _q(c, "SELECT substr(created_at, 1, 10) d, type, COUNT(*) n, COUNT(DISTINCT telegram_id) u "
                   "FROM events WHERE created_at >= ? GROUP BY d, type", (since,)):
        ev[(r["d"], r["type"])] = r
    for i in range(DAYS):
        d = (today - datetime.timedelta(days=DAYS - 1 - i)).isoformat()
        get = lambda t, k="n": ev[(d, t)][k] if (d, t) in ev else 0
        print(f"  {d}   {new_by_day.get(d, 0):>4} {get('open', 'u'):>6} {get('lot_view'):>8} {get('fav_add'):>6} {get('source_click'):>6}")

    print("\nСамые просматриваемые лоты за 30 дней:")
    start = (today - datetime.timedelta(days=29)).isoformat()
    for r in _q(c, "SELECT e.lot_id, COUNT(*) n, COUNT(DISTINCT e.telegram_id) u, l.brand, l.model, l.year "
                   "FROM events e LEFT JOIN lots l ON l.lot_id = e.lot_id "
                   "WHERE e.type = 'lot_view' AND e.created_at >= ? GROUP BY e.lot_id ORDER BY u DESC, n DESC LIMIT 10",
                   (start,)):
        name = " ".join(str(x) for x in (r["brand"], r["model"], r["year"]) if x)
        print(f"  {r['lot_id']}  {name:<35} людей {r['u']}, просмотров {r['n']}")

    shares = _q(c, "SELECT COUNT(*) n, COUNT(DISTINCT telegram_id) u FROM events WHERE type = 'share' AND created_at >= ?",
                (start,))[0]
    print(f"\n\"Поделиться\" за 30 дней: {shares['n']} раз, {shares['u']} человек")
    places = {"top": "иконка вверху", "bottom": "кнопка внизу", "toast": "после ♡"}
    by_place = _q(c, "SELECT source, COUNT(*) n FROM events WHERE type = 'share' AND created_at >= ? "
                     "GROUP BY source ORDER BY n DESC", (start,))
    if by_place:
        print("  откуда нажимали: " + ", ".join(f"{places.get(r['source'], r['source'] or 'не записано')} {r['n']}" for r in by_place))
    top = _q(c, "SELECT r.telegram_id, r.username, r.first_name, COUNT(*) n FROM users u "
                "JOIN users r ON r.telegram_id = u.referred_by GROUP BY r.telegram_id ORDER BY n DESC LIMIT 10")
    if top:
        print("Кто привёл новых пользователей своими ссылками (за всё время):")
        for r in top:
            who = ("@" + r["username"]) if r["username"] else (r["first_name"] or "-")
            print(f"  {r['telegram_id']:<12} {who:<24} привёл {r['n']}")
    c.close()


def list_users(source=None):
    """source=None - все; "-" - без метки; иначе - по первому источнику."""
    c = sqlite3.connect(db.db_path())
    c.row_factory = sqlite3.Row
    sql = ("SELECT u.telegram_id, u.username, u.first_name, u.source, u.last_source, u.created_at, u.last_seen_at, "
           "u.referred_by, "
           "(SELECT COUNT(*) FROM events e WHERE e.telegram_id = u.telegram_id AND e.type = 'lot_view') views, "
           "(SELECT COUNT(*) FROM favorites f WHERE f.telegram_id = u.telegram_id) favs, "
           "(SELECT COUNT(*) FROM users x WHERE x.referred_by = u.telegram_id) brought FROM users u")
    args = ()
    if source == "-":
        sql += " WHERE u.source IS NULL"
    elif source:
        sql += " WHERE u.source = ?"
        args = (source,)
    rows = _q(c, sql + " ORDER BY u.created_at DESC", args)
    print(f"{'telegram_id':<12} {'username':<20} {'имя':<16} {'источник':<16} {'последний':<16} "
          f"{'пришёл':<16} {'был':<16} {'просм':>5} {'избр':>4} {'привёл':>6}  {'по ссылке от':<12}")
    for r in rows:
        print(f"{r['telegram_id']:<12} {('@' + r['username']) if r['username'] else '-':<20} "
              f"{(r['first_name'] or '-')[:16]:<16} {r['source'] or '-':<16} {r['last_source'] or '-':<16} "
              f"{r['created_at'][:16].replace('T', ' '):<16} {r['last_seen_at'][:16].replace('T', ' '):<16} "
              f"{r['views']:>5} {r['favs']:>4} {r['brought']:>6}  {r['referred_by'] or '-'}")
    print(f"\nВсего: {len(rows)}")
    c.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "users":
        list_users(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        run()
