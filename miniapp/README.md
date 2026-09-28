# honestlot — мини-апп Telegram

Интерфейс для конечного пользователя: лента выгодных лотов с фильтрами, карточка лота, избранное.
Спецификация MVP — в заметках проекта; здесь — как это устроено и как запускать.

## Как устроено

```
ПК (run_pipeline.py)                           Сервер (Yandex Cloud, одна ВМ)
  ... шаги 1-7 -> лист lots_current_month
  8) export_to_miniapp.py ── POST /api/import ──> api (FastAPI + SQLite) ──> Telegram Mini App
       + карточки лотов с сайта                    caddy (HTTPS)
         (все фото, график периодов),
         кэш: miniapp_details_cache.json
```

- `backend/app/main.py` — эндпоинты API и раздача фронтенда.
- `backend/app/lots.py` — текущая цена и дедлайн (для публичного предложения — по графику периодов на момент запроса), процент к рынку (`lot_metrics.gap_percent`, та же формула, что у дайджеста), фильтры, сортировка, нормализация марок и моделей.
- `backend/app/db.py` — SQLite: `lots`, `users`, `favorites`.
- `backend/app/auth.py` — проверка подписи Telegram initData токеном бота.
- `frontend/` — чистый HTML/CSS/JS без сборки. После правок увеличьте `?v=` в `index.html`, иначе Telegram может показать старую версию из кэша.

Лоты, пропавшие из листа, из базы не удаляются: они скрываются из ленты, но остаются в избранном с пометкой «Приём заявок завершён».

## Локальный запуск (обычный браузер, без Telegram)

```
pip install -r miniapp/backend/requirements.txt
python export_to_miniapp.py --dry-run      # собрать выгрузку в miniapp_export_preview.json, без отправки
python miniapp/run_local.py --import       # http://localhost:8000 и загрузка выгрузки в локальную базу
```

Локально запросы без Telegram считаются запросами пользователя с id 1 (`HONESTLOT_DEV_USER_ID`). На сервере эту переменную не задаём.

## Сервер

Настройки — в `miniapp/.env` (шаблон `.env.example`): `DOMAIN`, `HONESTLOT_BOT_TOKEN`, `HONESTLOT_IMPORT_TOKEN`.

```
docker compose -f miniapp/docker-compose.yml up -d --build
```

База лежит в `miniapp/data/honestlot.db` на сервере. Бэкап — копия этого файла.

На ПК в `local_secrets.py`:
```
MINIAPP_API_URL = "https://<DOMAIN>"
MINIAPP_IMPORT_TOKEN = "<то же, что HONESTLOT_IMPORT_TOKEN>"
```
