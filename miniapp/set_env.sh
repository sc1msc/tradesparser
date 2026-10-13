#!/usr/bin/env bash
# Вписать настройки (в том числе секреты) в miniapp/.env на сервере. Запуск из Git Bash
# в корне репозитория:
#   bash miniapp/set_env.sh ИМЯ=значение ... ИМЯ ...
#
# ИМЯ=значение - записать как есть (для несекретного: адрес, порт).
# ИМЯ без значения - скрипт спросит значение скрытым вводом. Так секрет не попадает ни
# в историю команд, ни в чат с Claude, ни в аргументы процессов на сервере: он идёт
# через ssh в стандартный ввод.
#
# Пример - почта Postbox (wiki/payments.md, раздел "Почта"):
#   bash miniapp/set_env.sh HONESTLOT_SMTP_HOST=postbox.cloud.yandex.net HONESTLOT_SMTP_PORT=465 \
#     HONESTLOT_SMTP_FROM=info@honestlot.ru HONESTLOT_SMTP_USER HONESTLOT_SMTP_PASSWORD
#
# На сервере: строка ИМЯ=... заменяется на месте (повторы удаляются), новой переменной -
# дописывается в конец. Перед правкой - копия .env.bak; права на .env - только владельцу.
# После записи пересоздаются контейнеры (docker compose up -d): переменные из .env
# читаются только при создании контейнера. Мини-апп недоступен несколько секунд.
set -euo pipefail

HOST="${HONESTLOT_HOST:-honestlot@84.201.144.182}"

if [ $# -eq 0 ]; then
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi

payload=""
for arg in "$@"; do
  name="${arg%%=*}"
  if ! [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    echo "Неверное имя переменной: $name" >&2
    exit 1
  fi
  if [[ "$arg" == *=* ]]; then
    value="${arg#*=}"
  else
    read -r -s -p "$name (ввод не отображается): " value
    echo
    if [ -z "$value" ]; then
      echo "$name: пустое значение - ничего не записано" >&2
      exit 1
    fi
  fi
  # docker compose подставляет переменные в значения .env ($x), снимает кавычки, обрезает
  # пробелы по краям и считает " #" началом комментария - такое значение дошло бы до
  # приложения искажённым. Пробелы внутри (ФИО) он сохраняет. Ключи и токены этого не содержат.
  if [[ "$value" =~ [\$\"\'\\#$'\t'] || "$value" =~ ^[[:space:]] || "$value" =~ [[:space:]]$ ]]; then
    echo "$name: в значении есть \$, кавычки, \\, #, табуляция или пробел по краям - впишите его в .env вручную" >&2
    exit 1
  fi
  payload+="$name=$value"$'\n'
done

# Правка .env на сервере: построчно из stdin, значения - через окружение awk (не через -v:
# там обрабатываются обратные слэши), чтобы любые символы ключа записались как есть.
printf '%s' "$payload" | ssh "$HOST" 'set -euo pipefail
cd ~/honestlot/miniapp
if [ ! -f .env ]; then echo "На сервере нет ~/honestlot/miniapp/.env - см. miniapp/README.md" >&2; exit 1; fi
umask 077
cp -p .env .env.bak
tmp=$(mktemp .env.XXXXXX)
cp .env "$tmp"
while IFS= read -r line; do
  N="${line%%=*}" V="${line#*=}" awk '"'"'
    BEGIN { n = ENVIRON["N"]; v = ENVIRON["V"] }
    index($0, n "=") == 1 { if (!done) print n "=" v; done = 1; next }
    { print }
    END { if (!done) print n "=" v }
  '"'"' "$tmp" > "$tmp.new"
  mv "$tmp.new" "$tmp"
  echo "записано: ${line%%=*}"
done
chmod 600 "$tmp"
mv "$tmp" .env'

ssh "$HOST" 'cd ~/honestlot/miniapp && docker compose up -d'
