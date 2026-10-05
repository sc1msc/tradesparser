# honestlot — мини-апп Telegram

Интерфейс для конечного пользователя: лента выгодных лотов с фильтрами, карточка лота, избранное.
Спецификация MVP — в заметках проекта; здесь — как это устроено и как запускать.

## Как устроено

```
ПК (run_pipeline.py)                           Сервер (Yandex Cloud, одна ВМ)
  ... шаги 1-6 -> лист lots_current_month
  7) export_to_miniapp.py ── POST /api/import ──> api (FastAPI + SQLite) ──> Telegram Mini App
       + карточки лотов с сайта                    caddy (HTTPS)
         (все фото, график периодов),
         кэш: miniapp_details_cache.json
```

- `backend/app/main.py` — эндпоинты API и раздача фронтенда.
- `backend/app/lots.py` — текущая цена и дедлайн (для публичного предложения — по графику на момент запроса, `bidding_schedule.effective_price_and_deadline`, тот же расчёт, что у пайплайна), процент к рынку (`lot_metrics.gap_percent`, та же формула, что у дайджеста), фильтры, сортировка, нормализация марок и моделей. Оба общих модуля лежат в корне репозитория и копируются в Docker-образ.
- `backend/app/db.py` — SQLite: `lots` (все когда-либо выгруженные), `users`, `favorites` (лот + VIN машины), `events`.
- Машина и лоты: параллельные лоты одной машины (один VIN) в ленте — одна карточка; на экране лота — другие площадки и история торгов. Избранное следует за машиной: если её выставят снова, в избранном появится новый лот с пометкой «Перевыставлен».
- Итоги торгов для избранного: шаг 7 берёт у сервера `GET /api/watchlist` и отправляет статусы в `POST /api/lot-status` (оба — с ключом импорта).
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

База лежит в `miniapp/data/honestlot.db` на сервере.

Бэкап (`backend/app/backup.py`):
- сервер сам раз в сутки (после 04:00 МСК) копирует базу в `miniapp/data/backups/honestlot-ГГГГ-ММ-ДД.db`, хранит 7 последних;
- шаг 7 пайплайна в конце забирает свежую копию на ПК (`GET /api/backup`, ключ импорта) в `miniapp_backups/` в корне репозитория, тоже 7 последних, с проверкой целостности. Это на случай, если пропадёт сама ВМ.

Восстановление на сервере:

```
cd ~/honestlot/miniapp && docker compose stop api
cp data/backups/honestlot-ГГГГ-ММ-ДД.db data/honestlot.db && rm -f data/honestlot.db-wal data/honestlot.db-shm
docker compose start api
```

Копию с ПК сначала загрузить на сервер: `scp miniapp_backups/honestlot-ГГГГ-ММ-ДД.db honestlot@84.201.144.182:~/honestlot/miniapp/data/backups/`.

На ПК в `local_secrets.py`:
```
MINIAPP_API_URL = "https://<DOMAIN>"
MINIAPP_IMPORT_TOKEN = "<то же, что HONESTLOT_IMPORT_TOKEN>"
```

## Ссылки с меткой источника и метрики

Ссылка, по которой открывается мини-апп сразу, с меткой, откуда пришёл человек:

```
https://t.me/honestlot_bot?startapp=<метка>
```

Метка: латиница, цифры, `_` и `-`, до 64 символов. Например, `podbor_2026_10` для поста в канале про подбор или `sales` для канала продаж. Ссылка работает, когда у бота включено основное мини-приложение: @BotFather → `/mybots` → бот → Bot Settings → Configure Mini App → Enable Mini App, адрес — тот же, что у кнопки меню.

Метка приходит в подписанных данных Telegram (`start_param`) и записывается пользователю в `users.source` при первом входе. При входе через кнопку меню метки нет.

Метки вида `lot<номер>` занимать нельзя: так устроены ссылки «Поделиться».

## Ссылка на лот («Поделиться»)

На экране лота есть кнопка «Поделиться»: иконка рядом с ♡ и кнопка в нижней панели слева от «Открыть лот на сайте торгов». Ещё её предлагает уведомление после добавления в избранное («Добавлено в избранное · Поделиться ›»). Откуда нажали, пишется в `events.source` у события `share` (`top` / `bottom` / `toast`) и видно в `app.stats`. Кнопка открывает выбор чата в Telegram со ссылкой

```
https://t.me/honestlot_bot?startapp=lot7159530_k7f3q2
```

По ней мини-апп открывается сразу на экране этого лота, «Назад» ведёт в ленту. `k7f3q2` — код того, кто поделился (`users.ref_code`, случайный, выдаётся `GET /api/me`). Это не telegram_id, получатель ничего о поделившемся не узнаёт. Если торги лота закончились, а машину выставили снова, на экране лота есть переход на текущие торги. Лота нет в базе — «Лот больше недоступен».

В статистике пришедшие по таким ссылкам получают источник `share`, а новому пользователю записывается `users.referred_by` — кто его привёл. Уже знакомого пользователя ссылка не «приводит». `python -m app.stats` показывает, сколько раз делились и кто сколько привёл, `app.stats users` — столбцы «привёл» и «по ссылке от».

Проверка в обычном браузере: `http://localhost:8000/?startapp=lot<номер>`.

Сводка по пользователям, источникам и активности:

```
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats"
```

Список пользователей поимённо (id, username, имя, первый и последний источник, даты, просмотры, избранное), новые сверху:

```
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats users"
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats users podbor_post1"
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose exec -T api python -m app.stats users -"
```

Вторая команда — только пришедшие по метке `podbor_post1`, третья — только «без метки».
