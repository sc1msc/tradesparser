# -*- coding: utf-8 -*-
r"""
Доска задач проекта - вид на TODO.md (решение владельца 19.10.2026: доска, но без второго списка дел).

Источник один - TODO.md в репозитории: его читают сессии Claude, еженедельное ревью и напоминания.
Этот скрипт только раскладывает его пункты по колонкам и собирает страницу-канбан; страницу публикуют
артефактом (ссылка - в памяти Claude, wiki не нужна). Поменяли TODO.md - пересобрать и перевыложить:
    python todo_board.py <файл.html>

Колонки:
  «Высокий» / «Средний» - открытые пункты одноимённых разделов;
  «На паузе»            - открытые пункты с «на паузе», «отложено», «заморож» в тексте (из любого раздела);
  «Остальное»           - открытые пункты прочих разделов (раздел - подписью на карточке);
  «Сделано»             - отмеченные [x], свёрнуто.
Карточка: жирный заголовок пункта, раздел, дата «записано …», начало текста; по нажатию - текст целиком.
"""
import html
import json
import re
import subprocess
import sys

PAUSE_RE = re.compile(r"на паузе|отложен|заморож", re.I)
DATE_RE = re.compile(r"(?:записано|решено|решили|сделано)\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.I)


def parse(text):
    """TODO.md -> [{title, body, done, section, subsection, date}]."""
    items, section, subsection, cur = [], "", "", None
    for line in text.splitlines():
        if line.startswith("## "):
            section, subsection, cur = line[3:].strip(), "", None
            continue
        if line.startswith("### "):
            subsection, cur = line[4:].strip(), None
            continue
        m = re.match(r"^- \[( |x|X)\]\s*(.*)$", line)
        if m:
            cur = {"done": m.group(1).lower() == "x", "raw": [m.group(2)], "section": section, "subsection": subsection}
            items.append(cur)
            continue
        if cur is not None and (line.startswith("  ") or not line.strip()):
            if line.strip():
                cur["raw"].append(line.strip())
            continue
        cur = None
    out = []
    for it in items:
        raw = " ".join(it.pop("raw"))
        t = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", raw)
        title, body = (t.group(1), t.group(2)) if t else (raw[:90], raw)
        d = DATE_RE.search(raw)
        out.append({**it, "title": title.strip(), "body": body.strip(), "date": d.group(1) if d else ""})
    return out


def column(it):
    if it["done"]:
        return "done"
    if PAUSE_RE.search(it["title"] + " " + it["body"]):
        return "pause"
    sec = it["section"].lower()
    if "высокий" in sec:
        return "high"
    if "средний" in sec:
        return "mid"
    return "other"


COLUMNS = [("high", "Высокий"), ("mid", "Средний"), ("other", "Остальное"), ("pause", "На паузе"), ("done", "Сделано")]


def md_inline(text):
    """`код` и **жирный** -> HTML (остальное экранируется)."""
    s = html.escape(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def build(items, commit):
    cols = {key: [] for key, _ in COLUMNS}
    for it in items:
        cols[column(it)].append(it)
    parts = []
    for key, name in COLUMNS:
        cards = []
        for it in cols[key]:
            where = it["section"] + (f" · {it['subsection']}" if it["subsection"] else "")
            short = it["body"][:220] + ("…" if len(it["body"]) > 220 else "")
            cards.append(
                f'<details class="card" data-text="{html.escape((it["title"] + " " + it["body"]).lower())}">'
                f'<summary><span class="t">{md_inline(it["title"])}</span>'
                f'<span class="meta">{html.escape(where)}{" · " + it["date"] if it["date"] else ""}</span>'
                f'<span class="short">{md_inline(short)}</span></summary>'
                f'<div class="full">{md_inline(it["body"])}</div></details>')
        parts.append(f'<section class="col col-{key}"{" data-collapsed" if key == "done" else ""}>'
                     f'<h2>{name} <span class="n">{len(cols[key])}</span></h2>'
                     f'<div class="cards">{"".join(cards) or "<p class=empty>Пусто</p>"}</div></section>')
    open_n = sum(1 for it in items if not it["done"])
    return TEMPLATE.replace("{{COLUMNS}}", "".join(parts)).replace("{{STAMP}}",
        f"Из TODO.md, коммит {html.escape(commit)} · открыто {open_n}, сделано {len(items) - open_n}")


TEMPLATE = """<title>Доска HonestLot</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&family=JetBrains+Mono:wght@400&display=swap">
<style>
/* Канбан по TODO.md: колонки по приоритету, карточки раскрываются по нажатию. */
:root { --bg:#f3f5f2; --surface:#fff; --fg:#17201a; --muted:#5d6a61; --line:#dde3de; --accent:#147a43;
  --high:#c2410c; --mid:#b7791f; --other:#5d6a61; --pause:#6b4fa0; --done:#147a43; --code:#ecf1ed;
  --f:"Golos Text",-apple-system,"Segoe UI",Roboto,Arial,sans-serif; --mono:"JetBrains Mono",ui-monospace,Consolas,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0e1311; --surface:#161c19; --fg:#e5ece7;
  --muted:#97a39b; --line:#26302a; --accent:#3fca7b; --high:#f28b54; --mid:#e3b04b; --other:#97a39b; --pause:#ad93e0;
  --done:#3fca7b; --code:#1d2521; color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#0e1311; --surface:#161c19; --fg:#e5ece7; --muted:#97a39b; --line:#26302a; --accent:#3fca7b;
  --high:#f28b54; --mid:#e3b04b; --other:#97a39b; --pause:#ad93e0; --done:#3fca7b; --code:#1d2521; color-scheme:dark; }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); font:15px/1.5 var(--f); }
.wrap { padding-block:20px 48px; padding-left:max(16px, env(safe-area-inset-left,0px)); padding-right:max(16px, env(safe-area-inset-right,0px)); }
header { display:flex; flex-wrap:wrap; gap:10px 20px; align-items:baseline; margin-bottom:16px; }
h1 { font-size:24px; margin:0; font-weight:600; }
.stamp { color:var(--muted); font-size:13px; }
#q { flex:1 1 220px; max-width:360px; margin-left:auto; font:14px var(--f); color:var(--fg); background:var(--surface);
  border:1px solid var(--line); border-radius:10px; padding:8px 12px; }
.board { display:grid; grid-template-columns:repeat(5, minmax(260px, 1fr)); gap:14px; align-items:start; overflow-x:auto; }
@media (max-width:900px) { .board { grid-template-columns:minmax(0,1fr); } }
.col { min-width:0; }
.col h2 { font-size:14px; font-weight:600; margin:0 0 8px; display:flex; gap:8px; align-items:center; text-transform:uppercase; letter-spacing:.05em; }
.col h2::before { content:""; width:10px; height:10px; border-radius:3px; background:var(--c); }
.col-high { --c:var(--high); } .col-mid { --c:var(--mid); } .col-other { --c:var(--other); } .col-pause { --c:var(--pause); } .col-done { --c:var(--done); }
.n { color:var(--muted); font-weight:500; }
.cards { display:flex; flex-direction:column; gap:8px; }
.col[data-collapsed] .cards { display:none; }
.col[data-collapsed] h2 { cursor:pointer; }
.col[data-collapsed] h2::after { content:"показать"; margin-left:auto; color:var(--accent); font-size:12px; text-transform:none; letter-spacing:0; }
.card { background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--c); border-radius:10px; padding:10px 12px; }
.card summary { list-style:none; cursor:pointer; display:flex; flex-direction:column; gap:4px; }
.card summary::-webkit-details-marker { display:none; }
.t { font-weight:600; font-size:14.5px; line-height:1.35; }
.meta { color:var(--muted); font-size:12px; }
.short { font-size:13px; color:var(--muted); }
.card[open] .short { display:none; }
.full { font-size:13.5px; margin-top:8px; white-space:normal; overflow-wrap:anywhere; }
code { font-family:var(--mono); font-size:.88em; background:var(--code); padding:0 4px; border-radius:4px; overflow-wrap:anywhere; }
.empty { color:var(--muted); font-size:13px; margin:0; }
.card.hide { display:none; }
</style>
<div class="wrap">
<header><h1>Доска HonestLot</h1><span class="stamp">{{STAMP}}</span>
<input id="q" type="search" placeholder="Найти задачу" aria-label="Найти задачу"></header>
<div class="board">{{COLUMNS}}</div>
</div>
<script>
document.querySelectorAll(".col[data-collapsed] h2").forEach(h => h.addEventListener("click", () => {
  h.parentElement.removeAttribute("data-collapsed"); }));
document.getElementById("q").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll(".card").forEach(c => c.classList.toggle("hide", !!q && !c.dataset.text.includes(q)));
  if (q) document.querySelectorAll(".col[data-collapsed]").forEach(c => c.removeAttribute("data-collapsed"));
});
</script>
"""


def main(out):
    text = open("TODO.md", encoding="utf-8").read()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "?"
    items = parse(text)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(items, commit))
    print(json.dumps({k: sum(1 for it in items if column(it) == k) for k, _ in COLUMNS}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "todo_board.html")
