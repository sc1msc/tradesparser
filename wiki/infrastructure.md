# Серверы и доступы

Значения секретов в вики не пишем — только где они лежат. Адреса серверов и команды ниже — для
владельца и разработчика; пользователям их не сообщать (кроме страницы проверки связи, см.
[FAQ](faq.md#не-открывается-белый-экран-бесконечная-загрузка)).

## Машины

| Что | Где | Доступ | Что там |
|---|---|---|---|
| ПК владельца | Windows, папка репозитория | локально | конвейер, Google service account, кэши, журнал расходов, логи, копии базы мини-аппа |
| ВМ мини-аппа | Yandex Cloud, `84.201.144.182` (статический IP), домен `honestlot.ru` | `ssh honestlot@84.201.144.182`, код в `~/honestlot/miniapp` | Docker: `api`, `bot`, `caddy`; база в `miniapp/data/` |
| Релей Telegram | VPS VDSina, Амстердам, `89.124.97.131`, Ubuntu, `tg.honestlot.ru` | `ssh root@89.124.97.131` | только Caddy: пускает IP ВМ, пересылает в api.telegram.org. Данных нет, пересоздаётся `relay/setup.sh` |

- IP ВМ должен оставаться статическим: релей пускает только его (`ALLOWED_IPS` в
  `relay/setup.sh`). Сменился IP — бот и сторож перестанут достучаться до Telegram (ответ 403).
- `http://84.201.144.182` (без https) отвечает «HonestLot: связь с сервером есть» — проверка для
  поддержки.
- `https://honestlot.ru/api/health` — `{"ok":true,"lots":N}`, живой ли API.

## Домены

| Имя | Куда | Где управлять |
|---|---|---|
| `honestlot.ru` | A → 84.201.144.182 (ВМ) | регистратор SpaceWeb, DNS у регистратора; продление ~320 ₽/год |
| `tg.honestlot.ru` | A → 89.124.97.131 (релей) | там же |

Сертификаты Let's Encrypt Caddy получает и продлевает сам. Несколько имён в `DOMAIN` — через
запятую **с пробелом** и в кавычках, иначе Caddy не стартует. Верификация администратора домена
у SpaceWeb — через Госуслуги.

До 10.10.2026 мини-апп жил на `84-201-144-182.sslip.io`; у пользователя с VPN это имя не
находилось, поэтому купили свой домен.

## Telegram

| Аккаунт | Роль | Токен |
|---|---|---|
| [@honestlot_bot](https://t.me/honestlot_bot) | мини-апп (кнопка меню и основное мини-приложение настроены в @BotFather на `https://honestlot.ru`), приветствие, сторож | `HONESTLOT_BOT_TOKEN` в `miniapp/.env` на ВМ |
| @honest_torgi_bot | служебный: посты в канал, уведомления конвейера владельцу | `TELEGRAM_BOT_TOKEN` в `local_secrets.py` на ПК |
| [@honestlot_support_bot](https://t.me/honestlot_support_bot) | поддержка, сюда ведёт кнопка «Написать в поддержку» | вне репозитория |
| канал [@honestlot](https://t.me/honestlot) | подборки | `config.TELEGRAM_CHANNEL_ID` |

Получатель уведомлений — `NOTIFY_CHAT_ID` (ПК) и `HONESTLOT_ADMIN_CHAT_ID` (ВМ). Чтобы бот мог
написать человеку, тот должен хотя бы раз нажать «Старт» у этого бота.

## Где лежат секреты

| Секрет | Где | Кому нужен |
|---|---|---|
| `SPREADSHEET_ID` | `local_secrets.py` | все скрипты конвейера |
| `service_account.json` | файл на ПК | доступ к Google-таблице |
| `TRONK_API_KEY` | `local_secrets.py` | шаг 2, учёт расходов |
| `TELEGRAM_BOT_TOKEN`, `NOTIFY_CHAT_ID` | `local_secrets.py` | уведомления, `send_digest.py` |
| `MINIAPP_API_URL`, `MINIAPP_IMPORT_TOKEN` | `local_secrets.py` | шаг 7 |
| `ANTHROPIC_API_KEY` | `local_secrets.py` (пока пусто) | проверка фото |
| `telegraph_token.txt` | файл на ПК | страницы Telegraph |
| `DOMAIN`, `HONESTLOT_BOT_TOKEN`, `HONESTLOT_TELEGRAM_API`, `HONESTLOT_IMPORT_TOKEN`, `HONESTLOT_ADMIN_CHAT_ID` | `miniapp/.env` на ВМ | сервер мини-аппа |

Все эти файлы в `.gitignore`. Никогда не вписывать ключи в `config.py`, скрипты или вики.
`HONESTLOT_IMPORT_TOKEN` на ВМ и `MINIAPP_IMPORT_TOKEN` на ПК — одно и то же значение.

## Частые команды

```
# журнал бота и API
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose logs --tail 50 bot"
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose logs --tail 50 api"

# состояние контейнеров
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose ps"

# перезапуск api (например, после правки .env)
ssh honestlot@84.201.144.182 "cd ~/honestlot/miniapp && docker compose up -d api"

# выкладка новой версии (из Git Bash в корне репозитория)
bash miniapp/deploy.sh

# настройка релея заново
ssh root@89.124.97.131 'bash -s' < relay/setup.sh
```

Проверка цепочки ВМ → релей → Telegram — `miniapp/README.md`, раздел «Бот и релей Telegram».

## Почему так устроено

- **ВМ в России, релей за рубежом.** Провайдер ВМ блокирует Telegram в обе стороны (ответ
  поддержки Yandex Cloud 01.10.2026: блокировка не у них). Релей — обычный HTTPS через Caddy: VPN
  и туннели между РФ и заграницей детектятся и режутся. База и логика остаются в РФ (152-ФЗ),
  релей ничего не хранит.
- **Конвейер на ПК.** С ВМ Авто.ру сразу показывает капчу.
- **Caddy на релее из репозитория Ubuntu**: репозиторий Caddy на Cloudsmith 10.10.2026 отвечал
  «402 Payment Required».
