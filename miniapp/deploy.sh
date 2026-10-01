#!/usr/bin/env bash
# Выкладка мини-аппа на сервер. Запуск из Git Bash в корне репозитория:
#   bash miniapp/deploy.sh
#
# Отправляет на сервер ЗАКОММИЧЕННОЕ состояние (git archive HEAD) - только
# lot_metrics.py, bidding_schedule.py и папку miniapp/, без секретов и кэшей - и пересобирает
# контейнеры. Незакоммиченные правки на сервер не попадут: сначала commit.
# База (miniapp/data/) и настройки (miniapp/.env) на сервере не трогаются.
set -euo pipefail

HOST="${HONESTLOT_HOST:-honestlot@84.201.144.182}"
cd "$(git rev-parse --show-toplevel)"

if ! git diff --quiet HEAD -- lot_metrics.py bidding_schedule.py miniapp; then
  echo "Внимание: есть незакоммиченные правки в miniapp/, lot_metrics.py или bidding_schedule.py - они НЕ будут выложены."
fi

echo "Отправляю $(git rev-parse --short HEAD) на $HOST ..."
git archive --format=tar HEAD lot_metrics.py bidding_schedule.py miniapp | ssh "$HOST" 'mkdir -p ~/honestlot && tar -x -C ~/honestlot'

ssh "$HOST" 'set -e
cd ~/honestlot/miniapp
if [ ! -f .env ]; then echo "На сервере нет ~/honestlot/miniapp/.env - см. miniapp/README.md"; exit 1; fi
docker compose up -d --build --remove-orphans
# Caddyfile подключён в контейнер отдельным файлом: после выкладки (новый файл) контейнер
# продолжает видеть старый, и даже caddy reload его не замечает. Изменился - перезапуск caddy.
if ! docker compose exec -T caddy cat /etc/caddy/Caddyfile | cmp -s - Caddyfile; then
  echo "Caddyfile изменился - перезапускаю caddy"
  docker compose restart caddy
fi
docker image prune -f >/dev/null
docker compose ps'
