# -*- coding: utf-8 -*-
r"""
Сводка по пользователям и активности мини-аппа - печатает в консоль.

На сервере (с ПК, одной командой):
  ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats"
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
  - самые просматриваемые лоты.
Только чтение, в базу ничего не пишет.
"""
import datetime
import sqlite3

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
    c.close()


if __name__ == "__main__":
    run()
