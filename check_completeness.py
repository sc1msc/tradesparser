"""Проверка полноты собранных данных: у какой доли лотов ленты есть фото, VIN, пробег,
рыночная оценка, владельцы, характеристики, график публичного предложения и т.д.

Зачем. Сбор идёт из нескольких источников (агрегатор, площадки ТоргГрупп, МЭТС, ЦДТ, Lot-online),
и каждый может тихо начать отдавать неполные данные: площадка поменяла вёрстку - у новых лотов нет
фото или графика; шаг оценки не прошёл - у части машин нет рыночной цены. Тревоги конвейера ловят
падения, а не «стало меньше». Этот скрипт показывает покрытие по полям и по источникам и сравнивает
его с предыдущим днём.

Что считается. Лоты, которые видны в ленте мини-аппа на момент снимка базы (та же логика, что у
сервера: app.lots.is_open), каждая запись (лот на площадке) отдельно. Поля машины (VIN, пробег,
оценка, владельцы, характеристики) - только у лотов «одна машина»; график - только у публичных
предложений.

Откуда данные. По умолчанию - свежая копия базы сервера, которую шаг 7 конвейера каждый день
скачивает в miniapp_backups/ (ВМ не трогаем). Скрипт работает с временной копией файла: при
открытии бэкенд досоздаёт колонки, оригинал бэкапа не меняется.

Запуск:
    python check_completeness.py                  # последний бэкап + сравнение с предыдущим
    python check_completeness.py --db путь.db     # другой файл базы
    python check_completeness.py --examples 5     # по 5 примеров лотов без важного поля
    python check_completeness.py --no-compare

Пометки в отчёте: «⚠ ниже нормы» - покрытие ниже порога FLOORS (пороги подобраны по данным
19.10.2026 с запасом: срабатывают на поломку, а не на обычные колебания); «⚠ −N п.п.» - покрытие
упало больше чем на DROP_ALERT_PP по сравнению с предыдущим бэкапом. Код выхода 1, если есть
хотя бы одна пометка (можно встроить в конвейер или ревью позже).
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUPS = os.path.join(ROOT, "miniapp_backups")

# Падение покрытия поля больше чем на столько процентных пунктов к прошлому бэкапу - пометка.
DROP_ALERT_PP = 5
# Сравнивать долю, только если в группе хотя бы столько лотов (иначе 1 лот = 10-50 п.п.).
MIN_GROUP_FOR_ALERT = 20

# Платформы прямого сбора (etp_lots.PLATFORM_CODES) - подписи колонок отчёта.
PLATFORM_NAMES = {1: "ТоргГрупп", 2: "МЭТС", 3: "ЦДТ", 4: "Lot-online"}
ETP_ID_BASE = 9_000_000_000

# Поля: ключ, подпись, к каким лотам применимо, минимальная доля (None - только для сведения).
FIELDS = [
    ("photo", "Фото", "all", 70),  # обычно ~75%: у четверти лотов агрегатора фото нет вовсе
    ("photo_clean", "Фото без знака агрегатора", "all", None),
    ("brand_model", "Марка и модель", "car", 90),
    ("year", "Год", "car", 90),
    ("vin", "VIN", "car", 80),
    ("mileage", "Пробег (любой)", "car", 85),
    ("mileage_lot", "Пробег из описания лота", "car", None),
    ("estimate", "Рыночная оценка", "car", 60),
    ("owners", "Владельцы", "car", 55),
    ("specs", "Характеристики", "car", 55),
    ("plate", "Госномер", "car", None),
    ("region", "Регион", "all", 99),
    ("price", "Цена", "all", 99),
    ("description", "Описание", "all", 95),
    ("link", "Ссылка на торги (ЭТП или ЕФРСБ)", "all", 90),
    ("periods", "График снижения цены", "public", 85),
    ("status_fresh", "Статус проверен за 2 суток", "public", 70),
]
FLOORS = {key: floor for key, _, _, floor in FIELDS}
LABELS = {key: label for key, label, _, _ in FIELDS}
# Для --examples: самые важные для пользователя поля.
EXAMPLE_FIELDS = ["photo", "price", "estimate", "periods", "link"]


def source_of(lot_id):
    try:
        n = int(lot_id)
    except (TypeError, ValueError):
        return "агрегатор"
    if n < ETP_ID_BASE:
        return "агрегатор"
    code = (n - ETP_ID_BASE) // 10 ** 8
    return PLATFORM_NAMES.get(code, f"площадка {code}")


def collect(db_path, now):
    """Покрытие полей по источникам для одной базы. Возвращает словарь, пригодный для JSON."""
    tmp = tempfile.mkdtemp(prefix="completeness_")
    copy = os.path.join(tmp, "db.sqlite")
    shutil.copy(db_path, copy)
    os.environ["HONESTLOT_DB"] = copy
    for k in ("HONESTLOT_STATUS_REFRESH", "HONESTLOT_ETP_COLLECT"):
        os.environ[k] = "0"
    sys.path[:0] = [ROOT, os.path.join(ROOT, "miniapp", "backend")]
    import lot_metrics  # noqa: E402
    from app import lots  # noqa: E402

    def fresh(value):  # live_checked_at / etp_checked_at - ISO-время МСК без зоны
        try:
            dt = datetime.datetime.fromisoformat(str(value))
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=lots.MSK)
        return (now - dt) < datetime.timedelta(hours=48)

    stats = {}  # источник -> поле -> [есть, всего]
    examples = {}  # поле -> [(источник, lot_id, название)]
    total = {}
    no_photo = {}  # площадка лота -> сколько лотов без единого фото (где искать фото в первую очередь)
    for lot in lots.load():
        state = lots.current_state(lot, now)
        if not lots.is_open(lot, state, now):
            continue
        src = source_of(lot["lot_id"])
        total[src] = total.get(src, 0) + 1
        car = lot["kind"] == lot_metrics.LOT_CAR
        public = lot["trade"] == lots.TRADE_PUBLIC_OFFER
        has = {
            "photo": bool(lot.get("photo_sets")),
            "photo_clean": lots._photo_rank(lot) >= 2,
            "brand_model": bool(lot.get("brand_key") and lot.get("model_key")),
            "year": bool(lot.get("year")),
            "vin": len((lot.get("vin") or "").strip()) == 17,
            "mileage": bool(lot.get("mileage_km")),
            # источник пробега выгружается с 19.10.2026; у старых записей - «не расчётный»
            "mileage_lot": lot.get("mileage_source") == "lot" or (
                not lot.get("mileage_source") and bool(lot.get("mileage_km")) and not lot.get("mileage_estimated")),
            "estimate": bool(lot.get("autoru_price_low")),
            "owners": lot.get("autoru_owners") is not None,
            "specs": any(lot.get(k) for k in ("engine_type", "transmission", "drive", "power")),
            "plate": bool(lot.get("plate")),
            "region": bool(lot.get("region")),
            "price": bool(state["price"]),
            "description": bool((lot.get("description") or "").strip()),
            "link": bool(lot.get("etp_url") or lot.get("efrsb_url")),
            "periods": any(p["price"] for p in lot["_periods"]),
            "status_fresh": fresh(lot.get("live_checked_at")) or fresh(lot.get("etp_checked_at")),
        }
        if not has["photo"]:
            name = (lot.get("platform") or "не указана").strip()
            no_photo[name] = no_photo.get(name, 0) + 1
        for key, _, scope, _ in FIELDS:
            if scope == "car" and not car or scope == "public" and not public:
                continue
            cell = stats.setdefault(src, {}).setdefault(key, [0, 0])
            cell[1] += 1
            if has[key]:
                cell[0] += 1
            elif key in EXAMPLE_FIELDS:
                examples.setdefault(key, []).append((src, lot["lot_id"], lot["name"]))
    return {"now": now.isoformat(), "total": total, "stats": stats, "examples": examples, "no_photo": no_photo}


def snapshot_time(path):
    """Момент снимка: время изменения файла бэкапа (МСК)."""
    msk = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.fromtimestamp(os.path.getmtime(path), msk)


def run_child(path):
    """Каждую базу считаем в отдельном процессе: бэкенд держит одно соединение и кэш на процесс."""
    out = subprocess.run([sys.executable, os.path.abspath(__file__), "--json", "--db", path],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"Не удалось прочитать {path}:\n{out.stderr[-2000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def pct(cell):
    return 100.0 * cell[0] / cell[1] if cell and cell[1] else None


def merged(stats, key):
    have = sum(s.get(key, [0, 0])[0] for s in stats.values())
    of = sum(s.get(key, [0, 0])[1] for s in stats.values())
    return [have, of]


def report(cur, prev, n_examples):
    order = ["агрегатор"] + [n for n in PLATFORM_NAMES.values() if n in cur["total"]] + \
        sorted(s for s in cur["total"] if s != "агрегатор" and s not in PLATFORM_NAMES.values())
    order = [s for s in order if s in cur["total"]]
    print(f"Полнота данных ленты на {cur['now'][:16].replace('T', ' ')} МСК")
    print("Лотов в ленте: " + ", ".join(f"{s} {cur['total'][s]}" for s in order)
          + f"; всего {sum(cur['total'].values())}")
    if prev:
        print(f"Сравнение с {prev['now'][:16].replace('T', ' ')} (всего было {sum(prev['total'].values())})")
    print()
    head = f"{'Поле':34}{'Всего':>16}" + "".join(f"{s[:12]:>14}" for s in order)
    print(head)
    print("-" * len(head))
    alerts = []
    for key, label, scope, floor in FIELDS:
        cell = merged(cur["stats"], key)
        if not cell[1]:
            continue
        p = pct(cell)
        line = f"{label[:33]:34}{f'{p:.0f}% ({cell[0]}/{cell[1]})':>16}"
        for s in order:
            c = cur["stats"].get(s, {}).get(key)
            line += f"{(f'{pct(c):.0f}%' if c and c[1] else '—'):>14}"
        notes = []
        if floor is not None and p < floor:
            notes.append(f"⚠ ниже нормы {floor}%")
            alerts.append(f"{label}: {p:.0f}% при норме {floor}%")
        # падение к прошлому бэкапу - по каждому источнику отдельно
        if prev:
            for s in order:
                c, pc = cur["stats"].get(s, {}).get(key), prev["stats"].get(s, {}).get(key)
                if not c or not pc or c[1] < MIN_GROUP_FOR_ALERT or pc[1] < MIN_GROUP_FOR_ALERT:
                    continue
                drop = pct(pc) - pct(c)
                if drop > DROP_ALERT_PP:
                    notes.append(f"⚠ {s}: −{drop:.0f} п.п.")
                    alerts.append(f"{label}, {s}: {pct(pc):.0f}% → {pct(c):.0f}%")
        print(line + ("   " + "; ".join(notes) if notes else ""))
    if prev:
        for s in order:
            was, now_n = prev["total"].get(s, 0), cur["total"].get(s, 0)
            if was >= MIN_GROUP_FOR_ALERT and now_n < was * 0.7:
                alerts.append(f"Лотов из источника «{s}» стало заметно меньше: {was} → {now_n}")
    if cur.get("no_photo"):
        print()
        top = sorted(cur["no_photo"].items(), key=lambda kv: -kv[1])[:8]
        print("Лоты без фото по площадкам: " + "; ".join(f"{name} {n}" for name, n in top))
    if n_examples:
        print()
        for key in EXAMPLE_FIELDS:
            rows = cur["examples"].get(key) or []
            if not rows:
                continue
            print(f"Без поля «{LABELS[key]}» ({len(rows)}), примеры:")
            for src, lot_id, name in rows[:n_examples]:
                print(f"  {src:12} {lot_id:>12}  {name}")
    print()
    if alerts:
        print("Замечания:")
        for a in alerts:
            print("  - " + a)
    else:
        print("Замечаний нет.")
    return 1 if alerts else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Полнота данных ленты мини-аппа")
    ap.add_argument("--db", help="файл базы (по умолчанию последний из miniapp_backups/)")
    ap.add_argument("--examples", type=int, default=0, help="сколько примеров лотов без важных полей показать")
    ap.add_argument("--no-compare", action="store_true", help="не сравнивать с предыдущим бэкапом")
    ap.add_argument("--json", action="store_true", help=argparse.SUPPRESS)  # служебный режим run_child
    args = ap.parse_args()

    if args.json:
        print(json.dumps(collect(args.db, snapshot_time(args.db)), ensure_ascii=False))
        return 0

    backups = sorted(glob.glob(os.path.join(BACKUPS, "honestlot-*.db")))
    path = args.db or (backups[-1] if backups else None)
    if not path or not os.path.exists(path):
        raise SystemExit("Нет файла базы: укажите --db или дождитесь бэкапа в miniapp_backups/ (шаг 7)")
    cur = run_child(path)
    prev = None
    if not args.no_compare:
        older = [b for b in backups if os.path.abspath(b) != os.path.abspath(path)
                 and os.path.getmtime(b) < os.path.getmtime(path)]
        if older:
            prev = run_child(older[-1])
    return report(cur, prev, args.examples)


if __name__ == "__main__":
    sys.exit(main())
