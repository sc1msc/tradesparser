# Настройки

Значения на 11.10.2026. Источник истины — сам код: перед ответом, где важна цифра, сверьтесь.

## `config.py` (ПК, конвейер)

### Сбор лотов

| Параметр | Значение | Что |
|---|---|---|
| `SEARCH_PARAMS` | категория 2, регионы 50 и 77, `bankrupt` | фильтр поиска: легковые, МО и Москва, банкротство |
| `MAX_PAGES` | 20 | страниц поиска за прогон (~480 самых новых лотов) |
| `EXPIRED_LOT_DAYS` | 3 | через сколько дней после окончательного срока лот удаляется из `lots` |
| `NO_NEW_LOTS_ALERT_DAYS` | 2 | столько дней нет новых лотов агрегатора — уведомление каждый прогон |
| `DELAY_BETWEEN_LOT_REQUESTS` | 2.0 с | пауза между карточками |
| `DELAY_BETWEEN_SEARCH_PAGES` | 2.0 с | пауза между страницами поиска |
| `SITE_MAX_ERRORS_IN_ROW` | 10 | столько карточек подряд не прочиталось — проход останавливается |
| `SITE_FAILED_SHARE_ALERT` | 0.33 | не прочиталась такая доля карточек — уведомление |
| `PUBLIC_OFFER_REFRESH_MAX_PER_RUN` | 1000 | публичных предложений на перепроверку за прогон |
| `AGGREGATOR_NIGHTLY_UPDATE` | 04:30 | после этого времени статусы считаются устаревшими |
| `PUBLIC_OFFER_REFRESH_HOURS` | 8 | и не чаще, чем раз в столько часов |

### Пробег и оценки

| Параметр | Значение | Что |
|---|---|---|
| `MILEAGE_METHOD` | `probeg` | метод TRONK для пробега |
| `MILEAGE_MAX_PER_RUN` | 1000 | платных запросов пробега за прогон (уникальных VIN) |
| `TRONK_MONTHLY_BUDGET_RUB` | 1500 | бюджет TRONK на месяц, ₽ (пробег и ДТП вместе; 1000 до 19.10.2026) |
| `DTP_MAX_PER_RUN` | 1500 | платных запросов ДТП за прогон (уникальных VIN) |
| `DTP_TTL_DAYS` | 180 | через столько дней VIN спрашивается снова |
| `DELAY_BETWEEN_DTP_REQUESTS` | 0,3 | пауза между запросами ДТП, с |
| `TRONK_LOW_BALANCE_DAYS` | 5 | предупреждать, если баланса хватит меньше чем на столько дней |
| `TRONK_MAX_PER_RUN` | 10 | лимит старой оценки `evaluate_tronk.py` |
| `ANNUAL_MILEAGE_KM` | 16 600 | км в год: пересчёт показания TRONK на сегодня и пробег по году |
| `AUTORU_MAX_PER_RUN` | 300 | оценок Авто.ру за прогон |
| `DELAY_BETWEEN_AUTORU_REQUESTS` | 3.0 с (+ до 2 с случайно) | пауза между оценками |
| `AUTORU_HEADLESS` | False | браузер в видимом окне |
| `AUTORU_ESTIMATE_TTL_DAYS` | 60 | сколько дней оценка машины годится для нового лота |
| `AUTORU_SPECS_PER_RUN` | 30 | сколько машин со старой оценкой без характеристик шаг 5 дозаполняет за прогон (0 — выключено) |
| `AUTORU_CAPTCHA_WAIT_MIN` | 10 | сколько ждать решения капчи |
| `AUTORU_MAX_ERRORS_IN_ROW` | 5 | ошибок Авто.ру подряд до остановки шага |

### Проверка фото

| Параметр | Значение | Что |
|---|---|---|
| `DAMAGE_CHECK_MIN_GAP` | 40 | проверяются лоты дешевле середины рынка на столько процентов и больше |
| `DAMAGE_CHECK_PHOTOS` | 4 | фото на лот |
| `DAMAGE_CHECK_MAX_PER_RUN` | 200 | лотов за запуск |
| `DAMAGE_CHECK_MODEL` | `claude-opus-5-5` | модель |
| `DAMAGE_CHECK_PRICE_USD` | 4 / 20 $ за 1 млн токенов (вход/выход) | для оценки стоимости |
| `USD_RUB` | 85 | курс для учёта расходов |

### Автозапуск, уведомления, расходы

| Параметр | Значение | Что |
|---|---|---|
| `PIPELINE_LOG_DAYS` | 30 | сколько дней хранить логи |
| `PIPELINE_SUMMARY_DAYS` | 7 | раз во сколько дней сводка |
| `FIXED_MONTHLY_COSTS` | Yandex Cloud: 1480 ₽ | постоянные расходы в журнал раз в месяц |

### Канал и мини-апп

| Параметр | Значение | Что |
|---|---|---|
| `TELEGRAM_CHANNEL_ID` | `@honestlot` | канал для `send_digest.py` |
| `DIGEST_TEASER_COUNT` | 3 | лотов в посте |
| `DIGEST_PHOTO_POOL_SIZE` | 7 | кандидатов с фото на выбор |
| `DIGEST_FULL_COUNT` | 100 | лотов на странице Telegraph максимум |
| `MINIAPP_DETAILS_REFRESH_DAYS` | 7 | раз во сколько дней перекачивать карточку лота для мини-аппа |

## Константы в коде

| Где | Константа | Значение | Что |
|---|---|---|---|
| `build_lots_current_month.py` | `WINDOW_DAYS` | 30 | окно срока для среза и приложения |
| `lot_metrics.py` | `UNCERTAIN_ESTIMATE_PERCENT` | 90 | порог «оценка может быть неточной» |
| `lot_metrics.py` | `MAX_PLAUSIBLE_MILEAGE_KM` | 1 000 000 | больше — пробег считается ошибкой |
| `build_lot_selections.py` | `TOP_GAP_LIMIT`, `BUDGET_LIMIT`, `LUXURY_MIN_PRICE`, `MODEL_MAX_AGE_YEARS` | 50, 1 000 000, 5 000 000, 10 | параметры подборок |
| `export_to_miniapp.py` | `GHOST_CONFIRM_HOURS` | 6 | интервал двух проверок лота-призрака |
| `miniapp/backend/app/lots.py` | `FAVORITE_ARCHIVE_DAYS` | 60 | через сколько дней после срока закрытое избранное уходит в архив |
| `miniapp/backend/app/lots.py` | `WATCH_DAYS`, `WATCH_RECHECK_HOURS` | 60, 20 | сколько дней и как часто перепроверять итоги избранного |
| `miniapp/backend/app/auth.py` | `MAX_AGE_SECONDS` | 7 дней | срок жизни подписи Telegram |
| `miniapp/backend/app/watchdog.py` | `STALE_HOURS`, `REPEAT_HOURS` | 36, 24 | порог и повтор сторожа |
| `miniapp/backend/app/backup.py` | `KEEP`, `BACKUP_HOUR_MSK` | 7, 4 | копий базы на сервере, час копии |
| `run_pipeline.py` | `LOCK_STALE_HOURS` | 8 | через сколько часов лок прогона считается зависшим |

## `local_secrets.py` (ПК)

`TRONK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `SPREADSHEET_ID`, `MINIAPP_API_URL`,
`MINIAPP_IMPORT_TOKEN`, `ANTHROPIC_API_KEY`, `NOTIFY_CHAT_ID`. Шаблон — `local_secrets.example.py`.
Известная ловушка: если в файле нет хотя бы одного из первых трёх, `config.py` молча подставит
заглушки «ВСТАВЬТЕ_…» во все три.

## `miniapp/.env` (ВМ)

| Переменная | Что |
|---|---|
| `DOMAIN` | `honestlot.ru` — имя для HTTPS |
| `HONESTLOT_BOT_TOKEN` | токен @honestlot_bot: проверка подписи initData и бот |
| `HONESTLOT_TELEGRAM_API` | `https://tg.honestlot.ru` — релей |
| `HONESTLOT_IMPORT_TOKEN` | ключ выгрузки, тот же, что `MINIAPP_IMPORT_TOKEN` на ПК |
| `HONESTLOT_ADMIN_CHAT_ID` | кому идут все уведомления (сторож, статусы, сбор лотов, пайплайн с ПК); пусто — сторож выключен |
| `HONESTLOT_NOTIFY_BOT_TOKEN` | токен бота уведомлений; пусто — уведомления идут от @honestlot_bot |
| `HONESTLOT_ETP_COLLECT` | `0` — сервер не собирает лоты с площадок (`etp_collect.py`); по умолчанию собирает |
| `HONESTLOT_TRIAL_DAYS` | пробный Pro новому пользователю при первом входе, дней (по умолчанию 14; 0 — выключено; с 22.10.2026) |
| `HONESTLOT_SAVED_SEARCHES` | сохранённые поиски и уведомления: пусто — выключены, `all` — всем, `telegram_id` / `@ник` через запятую — только им |

Шаблон — `miniapp/.env.example`.
