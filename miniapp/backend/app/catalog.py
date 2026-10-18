# -*- coding: utf-8 -*-
r"""
Справочник марок и моделей ленты: единые названия, семейства, ручные правки и ежемесячная проверка.

Зачем (аудит 18.10.2026). Марку и модель большинству лотов даёт рыночная оценка по VIN - коды вида
NIVA_LEGEND, 2131_4X4, RAV_4, - остальным разбор названия лота. Из-за этого одна машина жила под
разными моделями (Нива: «Niva Legend», «2131 4X4», «2121»), Lada - кодами вместо названий («2170» -
это Priora), подписи были кривые («Rav 4», «Asx», «X Trail», «Santa FE»), а в моделях попадался мусор
из названий лотов. Для сохранённых поисков и подписок это критично: подписка на «Ниву» теряла половину
лотов. Решения владельца (18.10.2026): варианты одной модели объединять в одну (Niva и т.п., «аналогично
с другими»), мусор разбирать вручную раз в месяц.

Что здесь:
  code_to_model(code)      - код модели рыночной оценки -> модель с дефисами (CR_V -> CR-V, X_TRAIL ->
                             X-TRAIL, 9_3 -> 9-3): короткая первая часть кода пишется через дефис.
  normalize(brand_key, brand_label, model_label, lot, clean_brand)
                           -> (brand_key, brand_label, model_label) после ручных правок из базы
                             (таблица catalog_fixes), семейств (FAMILIES) и единых подписей (LABELS).
                             Вызывает lots._prepare для каждого лота.
  report()                 - аномалии справочника (текст): лоты без марки и без модели, модели
                             кириллицей, похожие на мусор, коды из цифр, похожие модели одной марки.
Ручные правки - в базе, без выкладки кода, действуют со следующей сборки кэша ленты (python -m app.catalog):
  fix <lot_id|VIN> "<Марка>" "<Модель>"        - марка и модель конкретного лота (машины);
  rename "<Марка>" "<модель>" "<новая модель>" - модель марки целиком (все лоты с такой подписью);
  ok <lot_id>  |  ok "<Марка>" "<модель>"      - это не ошибка: больше не показывать в проверке;
  list | del <id> | report
Ежемесячно (первая проверка сторожа выгрузок после 10:00 1-го числа, watchdog.py) сервер присылает
администратору сводку аномалий через бота уведомлений (monthly_check). Каждую строку владелец
исправляет (fix/rename) или помечает нормальной (ok) - в следующей сводке будут только новые.
"""
import datetime
import json
import os
import re
import sys

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_fixes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,      -- lot: правка лота/машины; model: переименование; ok: не показывать в проверке
    brand_key   TEXT,               -- для model и ok модели: марка (ключ)
    match       TEXT NOT NULL,      -- lot_id / VIN или модель (ключ, верхний регистр)
    brand_label TEXT,               -- для lot: новая марка
    model_label TEXT NOT NULL,      -- новая модель ("" у ok)
    created_at  TEXT NOT NULL
);
"""

# Семейства: варианты одной модели - одна модель (решения владельца 18.10.2026). Ключ - ключ модели после
# разбора (верхний регистр), значение - подпись модели. Коды из рыночной оценки и из названий лотов.
FAMILIES = {
    "LADA": {
        **{k: "Niva" for k in ("2121", "21213", "21214", "2131", "2131 4X4", "2131 (4X4)", "4X4", "NIVA",
                               "NIVA LEGEND", "4X4 (НИВА)", "НИВА")},
        **{k: "Samara" for k in ("2108", "2109", "21099", "2113", "2114", "2115", "SAMARA")},
        **{k: "Priora" for k in ("2170", "2171", "2172", "217030", "217230", "217130", "PRIORA")},
        **{k: "2110" for k in ("2110", "2111", "2112")},
        **{k: "Kalina" for k in ("1117", "1118", "1119", "KALINA")},
        **{k: "Granta" for k in ("2190", "2191", "2192", "2194", "219010", "219110", "GRANTA")},
    },
    "GAZ": {
        # бортовая, фургон, микроавтобус, «Фермер» - всё ГАЗель; ГАЗель Next - FAMILY_PATTERNS
        **{k: "ГАЗель" for k in ("3302", "33021", "33023", "330202", "330210", "330232", "2705", "27057",
                                 "2747", "3221", "32213", "322132", "GAZEL", "ГАЗЕЛЬ")},
        **{k: "Соболь" for k in ("2752", "27527", "2217", "22171", "221717", "SOBOL", "СОБОЛЬ")},
        **{k: "Волга" for k in ("2410", "3102", "3110", "31105", "VOLGA", "ВОЛГА")},
    },
    "UAZ": {
        "23632": "Pickup", "3163": "Patriot", "315195": "Hunter",
        **{k: "Буханка" for k in ("452", "3909", "39094", "2206", "3962", "3741", "БУХАНКА")},
    },
    "HYUNDAI": {
        "H-100": "Porter", "H-100 (AU) PORTER": "Porter", "PORTER": "Porter",
        "H1 2.4 AT COMFORT": "H-1 Starex", "H-1": "H-1 Starex", "STAREX": "H-1 Starex",
    },
    "INFINITI": {"EX35 PREMIUM": "EX35"},
    "FIAT": {"NUOVO DUCATO": "Ducato"},
    "CHERY": {"SUV T11": "Tiggo"},
    # модели кириллицей из документов торгов
    "PEUGEOT": {"БОКСЕР": "Boxer"},
    "ROLLS-ROYCE": {"ГОУСТ": "Ghost"},
    "DAEWOO": {"ГНЕНТРА": "Gentra", "ДЖЕНТРА": "Gentra"},
}
FAMILY_PATTERNS = {"GAZ": [(re.compile(r"^A2[1-3]R"), "ГАЗель Next")]}  # A21R22, A23R32...
# Единые подписи моделей (ключ - ключ модели, верхний регистр): аббревиатуры заглавными, привычное написание.
LABELS = {
    "RAV 4": "RAV4", "ASX": "ASX", "SANTA FE": "Santa Fe", "MDX": "MDX", "RDX": "RDX", "SRX": "SRX",
    "RVR": "RVR", "WRX": "WRX", "TXL": "TXL", "UNI T": "UNI-T", "UNI K": "UNI-K", "UNI V": "UNI-V",
    "CS35PLUS": "CS35 Plus", "CS55PLUS": "CS55 Plus", "CS75PLUS": "CS75 Plus", "HOVERH3": "Hover H3",
    "HOVERH5": "Hover H5", "HOVERH6": "Hover H6", "MI-DO": "Mi-Do", "ON-DO": "On-Do", "PT-CRUISER": "PT Cruiser",
    "PORTER-2": "Porter II", "GRAND STAREX": "Grand Starex", "IX35": "ix35", "I40": "i40", "I30": "i30",
    "G05PRO": "G05 Pro", "XRAY": "XRAY",
}
# Модели-цифры, которые и есть название (проверка их не показывает): у этих марок любые, у Lada - классика.
NUMERIC_BRANDS = {"PEUGEOT", "MAZDA"}
NUMERIC_OK = {("LADA", m) for m in ("2101", "2102", "2103", "2104", "2105", "2106", "2107", "2110")}
# Коды рыночной оценки, где после короткой первой части дефис не нужен (иначе «PT-Cruiser»).
NO_HYPHEN = {"PT_CRUISER"}
_CODE_HYPHEN_RE = re.compile(r"^([A-Z]{1,2}|\d{1,2})_(?=[A-Z0-9])")
_OUR_LABELS = {v for fam in FAMILIES.values() for v in fam.values()} | \
    {v for pats in FAMILY_PATTERNS.values() for _, v in pats}

_fixes = {"lot": {}, "model": {}, "ok_lot": set(), "ok_model": set()}
_schema_ready = False


def _key(value):
    return " ".join((value or "").upper().replace("Ё", "Е").replace("_", " ").split())


def code_to_model(code):
    """Код модели рыночной оценки -> модель для разбора подписи: CR_V -> CR-V, CX_5 -> CX-5, X_TRAIL ->
    X-TRAIL, H_1_STAREX -> H-1_STAREX, 9_3 -> 9-3. Остальные коды - как есть."""
    code = (code or "").strip()
    if code.upper() in NO_HYPHEN:
        return code
    return _CODE_HYPHEN_RE.sub(r"\1-", code)


def _conn():
    global _schema_ready
    c = db.conn()
    if not _schema_ready:
        with db._lock:
            c.executescript(SCHEMA)
            c.commit()
        _schema_ready = True
    return c


def load_fixes():
    """Ручные правки из базы - при каждой сборке кэша ленты (lots.load)."""
    out = {"lot": {}, "model": {}, "ok_lot": set(), "ok_model": set()}
    for r in _conn().execute("SELECT * FROM catalog_fixes ORDER BY id"):
        if r["kind"] == "lot":
            out["lot"][r["match"].upper()] = (r["brand_label"], r["model_label"])
        elif r["kind"] == "model":
            out["model"][(r["brand_key"], r["match"])] = r["model_label"]
        elif r["kind"] == "ok":
            if r["brand_key"]:
                out["ok_model"].add((r["brand_key"], r["match"]))
            else:
                out["ok_lot"].add(r["match"].upper())
    _fixes.update(out)
    return out


def normalize(brand_key, brand_label, model_label, lot, clean_brand=None):
    """Марка и модель после справочника: ручная правка лота (по lot_id или VIN) важнее всего, потом
    ручное переименование модели, семейства и единые подписи."""
    fix = _fixes["lot"].get(str(lot.get("lot_id") or "").upper()) or \
        _fixes["lot"].get((lot.get("vin") or "").strip().upper() or "-")
    if fix:
        b_label, m_label = fix
        if b_label and clean_brand:
            k, lbl = clean_brand(b_label)
            if k:
                brand_key, brand_label = k, lbl
        return brand_key, brand_label, m_label
    key = _key(model_label)
    renamed = _fixes["model"].get((brand_key, key))
    if renamed:
        return brand_key, brand_label, renamed
    family = FAMILIES.get(brand_key, {}).get(key)
    if family:
        return brand_key, brand_label, family
    for pattern, label in FAMILY_PATTERNS.get(brand_key, ()):
        if pattern.match(key):
            return brand_key, brand_label, label
    return brand_key, brand_label, LABELS.get(key, model_label)


# ---------- проверка справочника ----------

_SUSPECT_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)|г\.?в|\bvin\b|гос|номер|двигат|кузов|цвет|"
                         r"л\.?с|\bкм\b|автомоб|легков|\(|\)|,", re.I)


def anomalies(lots_):
    """Аномалии справочника по лотам ленты (машины) без помеченных «ok»: -> dict {вид: [строки]}."""
    from . import lots as lots_mod  # здесь: lots импортирует catalog
    cars = [l for l in lots_ if l.get("in_source") and l["kind"] == "car"
            and str(l["lot_id"]).upper() not in _fixes["ok_lot"]]
    out = {"без марки": [], "без модели": [], "модель кириллицей": [], "похоже на мусор": [],
           "модель - код из цифр": [], "похожие модели одной марки": []}
    models = {}
    for l in cars:
        title = " ".join((l.get("title") or "").split())[:90]
        if not l["brand_key"]:
            out["без марки"].append(f"{l['lot_id']}: {title}")
        elif not l["model_key"]:
            out["без модели"].append(f"{l['lot_id']} {l['brand_label']}: {title}")
        elif (l["brand_key"], l["model_key"]) not in _fixes["ok_model"]:
            models.setdefault((l["brand_key"], l["brand_label"], l["model_label"]), []).append(str(l["lot_id"]))
    for (bk, b, m), ids in sorted(models.items(), key=lambda x: x[0][1:]):
        if m in _OUR_LABELS:
            continue
        tag = f"{b} «{m}» ({len(ids)}: {', '.join(ids[:3])}{'…' if len(ids) > 3 else ''})"
        if re.search(r"[а-яё]", m, re.I) and not re.search(r"класс|серии", m, re.I):
            out["модель кириллицей"].append(tag)
        elif len(m) > 22 or _SUSPECT_RE.search(m):
            out["похоже на мусор"].append(tag)
        elif re.fullmatch(r"\d{4,6}[A-Za-zА-Яа-я]{0,2}", m) and bk not in NUMERIC_BRANDS \
                and (bk, m) not in NUMERIC_OK:
            out["модель - код из цифр"].append(tag)
    # похожие модели: та же проверка «на слух», что у поиска (lots._close): «Солярис» и «Solaris»
    by_brand = {}
    for (bk, b, m) in models:
        if not re.search(r"класс|серии", m, re.I):
            by_brand.setdefault(b, []).append(m)
    for b, ms in by_brand.items():
        sounds = [(m, lots_mod._sound(lots_mod._skeleton(m))) for m in sorted(ms)]
        for i, (m1, s1) in enumerate(sounds):
            for m2, s2 in sounds[i + 1:]:
                if len(s1) >= 4 and s1.isalpha() and s2.isalpha() and \
                        lots_mod._sound_cons(s1) == lots_mod._sound_cons(s2) and lots_mod._close(s1, s2):
                    out["похожие модели одной марки"].append(f"{b}: «{m1}» / «{m2}»")
    return {k: v for k, v in out.items() if v}


def report(lots_=None):
    from . import lots as lots_mod
    lots_ = lots_ if lots_ is not None else lots_mod.load()
    found = anomalies(lots_)
    cars = sum(1 for l in lots_ if l.get("in_source") and l["kind"] == "car")
    lines = [f"Справочник марок и моделей: машин в ленте {cars}, на проверку {sum(len(v) for v in found.values())}."]
    for kind, items in found.items():
        lines.append(f"\n{kind} ({len(items)}):")
        lines += [f"  {x}" for x in items[:30]] + ([f"  … ещё {len(items) - 30}"] if len(items) > 30 else [])
    lines.append('\nНа сервере: docker compose exec api python -m app.catalog ...\n'
                 '  fix <lot_id|VIN> "Марка" "Модель" - исправить лот\n'
                 '  rename "Марка" "модель" "новая модель" - переименовать модель у всех лотов\n'
                 '  ok <lot_id>  или  ok "Марка" "модель" - это не ошибка, больше не показывать')
    return "\n".join(lines)


def state_file():
    return os.path.join(os.path.dirname(os.path.abspath(db.db_path())), "catalog_check.json")


def monthly_check(now=None, send=None):
    """Раз в месяц (первый вызов после 10:00 1-го числа и позже) - сводка аномалий администратору.
    -> отправлено ли. Не отправилось (релей, Telegram) - исключение, повтор при следующем вызове."""
    from . import watchdog
    now = now or datetime.datetime.now(watchdog.MSK)
    if now.day == 1 and now.hour < 10:
        return False
    month = now.strftime("%Y-%m")
    try:
        with open(state_file(), encoding="utf-8") as f:
            if json.load(f).get("month") == month:
                return False
    except (OSError, ValueError):
        pass
    chat = watchdog.admin_chat_id()
    if not chat:
        return False
    load_fixes()
    text = report()
    (send or watchdog._send)(chat, "HonestLot, ежемесячная проверка справочника марок и моделей.\n\n" + text[:3800])
    with open(state_file(), "w", encoding="utf-8") as f:
        json.dump({"month": month, "at": now.isoformat(timespec="seconds")}, f)
    return True


def _cli(argv):
    from . import lots as lots_mod
    c = _conn()
    now = datetime.datetime.now().isoformat(timespec="seconds")

    def add(kind, match, model_label="", brand_key=None, brand_label=None):
        with db._lock:
            with c:
                c.execute("INSERT INTO catalog_fixes (kind, brand_key, match, brand_label, model_label, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?)", (kind, brand_key, match, brand_label, model_label, now))

    def brand_of(label):
        bkey, _ = lots_mod.clean_brand(label)
        if not bkey:
            raise SystemExit(f"Марка «{label}» не распознана")
        return bkey

    if argv[:1] == ["fix"] and len(argv) >= 4:
        add("lot", argv[1].upper(), argv[3], brand_label=argv[2])
        print(f"Лот/машина {argv[1]}: {argv[2]} {argv[3]}")
    elif argv[:1] == ["rename"] and len(argv) >= 4:
        add("model", _key(argv[2]), argv[3], brand_key=brand_of(argv[1]))
        print(f"{argv[1]}: «{argv[2]}» -> «{argv[3]}»")
    elif argv[:1] == ["ok"] and len(argv) == 2:
        add("ok", argv[1].upper())
        print(f"Лот {argv[1]} больше не показывается в проверке")
    elif argv[:1] == ["ok"] and len(argv) >= 3:
        add("ok", _key(argv[2]), brand_key=brand_of(argv[1]))
        print(f"{argv[1]} «{argv[2]}» больше не показывается в проверке")
    elif argv[:1] == ["del"] and len(argv) >= 2:
        with db._lock:
            with c:
                n = c.execute("DELETE FROM catalog_fixes WHERE id = ?", (int(argv[1]),)).rowcount
        print("удалено" if n else "нет такой правки")
    elif argv[:1] == ["list"]:
        for r in c.execute("SELECT * FROM catalog_fixes ORDER BY id"):
            if r["kind"] == "lot":
                what = f"лот/машина {r['match']} -> {r['brand_label'] or ''} {r['model_label']}"
            elif r["kind"] == "model":
                what = f"{r['brand_key']} «{r['match']}» -> {r['model_label']}"
            else:
                what = f"ok: {(r['brand_key'] + ' ') if r['brand_key'] else 'лот '}{r['match']}"
            print(f"{r['id']:>4}  {what}")
    else:
        load_fixes()
        print(report())


if __name__ == "__main__":
    _cli(sys.argv[1:])
