# -*- coding: utf-8 -*-
r"""
Механические проверки для еженедельного ревью кода (.claude/skills/weekly-review).

Зачем отдельный скрипт. Ревьюер - сессия Claude, которую по понедельникам
запускает приложение Claude (задача weekly-code-review). Суждения - его
работа, а то, что можно проверить без суждения, проще и надёжнее сделать
кодом: одинаково каждую неделю, без регулярок в командной строке (PowerShell
и Git Bash по-разному экранируют кавычки) и без риска, что секрет попадёт
в отчёт.

Команды (запуск из корня репозитория):
  python .claude/skills/weekly-review/review_checks.py secrets
      Публичный репозиторий: нет ли в отслеживаемых git файлах секретов.
      Печатает файл:строку и тип, само значение - никогда.
  python .claude/skills/weekly-review/review_checks.py syntax ФАЙЛ.py ...
      Синтаксис через ast.parse: модули проекта не импортируются (импорт
      скриптов пайплайна может полезть в таблицу или платный API).
  python .claude/skills/weekly-review/review_checks.py logs [ДНЕЙ]
      Traceback'и в logs/pipeline-*.log за последние ДНЕЙ (7), сгруппированные
      по последней строке нашего кода. Повторяющийся traceback - кандидат в баги.
  python .claude/skills/weekly-review/review_checks.py send reviews/ГГГГ-ММ-ДД.md
      Верхнюю часть отчёта (до <!-- telegram-end -->) - владельцу в Telegram
      через automation.send_telegram (бот и получатель - из local_secrets.py).

Скрипт ничего не пишет, кроме вывода в консоль, и в сеть ходит только
командой send.
"""
import ast
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKER = "<!-- telegram-end -->"

# Файлы, которым не место в публичном репозитории (они в .gitignore).
FORBIDDEN_NAMES = {"local_secrets.py", "service_account.json", ".env", "telegraph_token.txt"}
FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pfx")

SECRET_PATTERNS = [
    ("токен Telegram-бота", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("ключ Claude API", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("закрытый ключ", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("ключ сервисного аккаунта Google", re.compile(r'"private_key"\s*:\s*"-')),
    ("секретный ключ ЮKassa", re.compile(r"\b(?:live|test)_[A-Za-z0-9_-]{30,}\b")),
    ("пароль в адресе", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"]{4,}@")),
    ("ключ/пароль в присваивании", re.compile(
        r"(?i)\b[A-Z_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD)\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']")),
]
# Шаблоны и заглушки - не секреты.
PLACEHOLDER = re.compile(r"(?i)ВСТАВЬТЕ|example|your[_-]|xxx|changeme|<[^>]+>|\.\.\.|\$\{?[A-Z_]+")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def cmd_secrets():
    found = 0
    me = Path(__file__).resolve()
    for rel in _git("ls-files").splitlines():
        path = ROOT / rel
        name = Path(rel).name
        if name in FORBIDDEN_NAMES or name.endswith(FORBIDDEN_SUFFIXES):
            print(f"{rel}: файл с секретами в git (должен быть в .gitignore)")
            found += 1
            continue
        if path.resolve() == me or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # картинки и прочие бинарные файлы
        for n, line in enumerate(text.splitlines(), 1):
            for kind, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if m and not PLACEHOLDER.search(m.group(0)):
                    print(f"{rel}:{n}: похоже на {kind}")
                    found += 1
                    break  # одна строка - одна находка
    if not found:
        print("Секретов в отслеживаемых файлах не найдено.")


def cmd_syntax(files):
    bad = 0
    for f in files:
        try:
            ast.parse(Path(f).read_text(encoding="utf-8"), filename=f)
        except SyntaxError as e:
            print(f"{f}:{e.lineno}: синтаксическая ошибка: {e.msg}")
            bad += 1
        except (OSError, UnicodeDecodeError) as e:
            print(f"{f}: не прочитать: {e}")
            bad += 1
    print(f"Проверено файлов: {len(files)}, с ошибками: {bad}.")


_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+), in (\S+)')


def cmd_logs(days):
    since = datetime.now() - timedelta(days=days)
    groups = defaultdict(list)  # (место в нашем коде, исключение) -> [лог, ...]
    logs = []
    for log in sorted((ROOT / "logs").glob("pipeline-*.log")):
        try:
            started = datetime.strptime(log.stem[len("pipeline-"):], "%Y-%m-%d_%H%M")
        except ValueError:
            continue
        if started < since:
            continue
        logs.append(log.name)
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        i = 0
        while i < len(lines):
            if not lines[i].startswith("Traceback (most recent call last)"):
                i += 1
                continue
            ours, exc = None, None
            i += 1
            while i < len(lines):
                m = _FRAME.match(lines[i])
                if m:
                    p = Path(m.group(1))
                    if ".venv" not in p.parts:  # библиотеки и сам Python - не наш код
                        try:
                            rel = p.resolve().relative_to(ROOT)
                            ours = f"{rel.as_posix()}:{m.group(2)} ({m.group(3)})"
                        except ValueError:
                            pass
                elif lines[i] and not lines[i][0].isspace():
                    exc = lines[i][:200]
                    break
                i += 1
            i += 1
            # Цепочка "During handling ... another exception occurred" - одна
            # ошибка: считаем только последний traceback цепочки.
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].startswith(("During handling", "The above exception")):
                continue
            groups[(ours or "вне кода проекта", exc or "?")].append(log.name)
    print(f"Логов за {days} дн.: {len(logs)}. Traceback'ов: {sum(len(v) for v in groups.values())}.")
    for (where, exc), names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        dates = ", ".join(sorted({n[len('pipeline-'):len('pipeline-') + 10] for n in names}))
        print(f"- {len(names)} раз: {where}\n  {exc}\n  даты: {dates}")


def cmd_send(report):
    sys.path.insert(0, str(ROOT))
    import automation  # только здесь: тянет config и local_secrets

    text = Path(report).read_text(encoding="utf-8").split(MARKER)[0].strip()
    if not text:
        print("Пустой отчёт - не отправлено.")
        sys.exit(1)
    ok = automation.send_telegram(text)
    print("Отправлено в Telegram." if ok else "НЕ отправлено в Telegram.")
    sys.exit(0 if ok else 1)


def main(argv):
    if not argv:
        print(__doc__)
        sys.exit(2)
    cmd, args = argv[0], argv[1:]
    if cmd == "secrets":
        cmd_secrets()
    elif cmd == "syntax":
        cmd_syntax(args)
    elif cmd == "logs":
        cmd_logs(int(args[0]) if args else 7)
    elif cmd == "send" and len(args) == 1:
        cmd_send(args[0])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
