# Google-таблица

Одна таблица — единственное общее хранилище конвейера. ID — `SPREADSHEET_ID` в
`local_secrets.py`, доступ — service account из `service_account.json` (роль «Редактор»).
Ни ID, ни ключ в вики не пишем.

Листы — это стадии конвейера. Ниже — состав на 11.10.2026.

| Лист | Строк | Кто пишет | Как |
|---|---|---|---|
| `lots` | ~1900 | шаг 1 (`main.py`), шаг 2 (пробег), старые ручные скрипты | дописывается и обновляется по ячейкам; истёкшие строки удаляются |
| `lots_processed` | = `lots` | шаг 3 | полностью перезаписывается каждый прогон |
| `lots_current_month` | ~1400 | шаг 4, шаг 5 (оценка), шаг 6 (процент) | перезаписывается, оценки переносятся |
| `lots_top_gap`, `lots_budget_1m`, `lots_one_owner`, `lots_heavy_luxury`, `lots_polo_rio_solyaris` | 20–1000 | шаг 6 | полностью перезаписываются |
| `vin_cache` | ~1700 | шаги 2, 4, 5 | строка на VIN, пишется пачками |
| `beautiful_plates` | ~100 | шаг 6 (`build_lot_selections.py`); вручную — `filter_beautiful_plates_gspread.py` | полностью перезаписывается |

## `lots` — сырые лоты

Строка на лот, ключ — `lot_id`. Лоты, собранные сервером прямо с площадок (с 16.10.2026), — с
номерами от 9 000 000 000 и `url` на страницу лота на площадке (см.
[Внутреннее устройство мини-аппа](miniapp-internals.md#лоты-прямо-с-площадок-etp_collectpy)).
Колонки (буква: имя):

| Колонки | Что | Кто пишет |
|---|---|---|
| A–V, Y | `lot_id`, `url`, `title`, `status`, `vin`, `plate`, `mileage_km`, `price_start`, `price_current`, `currency`, `region`, `trade_kind` (форма торгов), `platform`, `applications_start`, `applications_end`, `bidding_start`, `organizer_name/phone/email`, `manager_name`, `manager_sro`, `debtor_name`, `scraped_at` | шаг 1 |
| W–X, AF–AJ | `avito_*` | старый `evaluate_avito_browser.py`, не используется |
| Z–AE, AK–AM | `tronk_*` (оценка TRONK) | старый `evaluate_tronk.py`, не используется |
| AN–AY | `autoru_*` | старые значения, конвейер их не читает (оценка живёт в `lots_current_month` и `vin_cache`) |
| AZ, BA, BB | `brand`, `name`, `date` (дата выпуска, свободный текст) | `autodoc_decode.py`, выключен с 11.10.2026: у новых лотов пусто |
| BC–BR | прочие поля Autodoc (`model`, `market`, `modification`, …, `api_status`, `vin_autodoc`) | `autodoc_decode.py` |
| BS | `description` | шаг 1 |
| BT–BV | `final_price_low/high`, `final_source` | старые, не используются |
| BW | `photo_url` (первое фото) | шаг 1 |
| BX–CB | `mileage_probeg_status/date/source/checked_at/km` | шаг 2 (TRONK) |
| CC | `bidding_periods` — график ПП: `[[bid_end, price], ...]` | шаг 1 |
| CD | `status_checked_at` | шаг 1 |
| CE–CG | `etp_url` (лот на самой ЭТП), `etp_status` (что написано на ЭТП: «Прием заявок», «Торги завершены», «Определение участников»), `etp_checked_at` | шаг 1, с сервера мини-аппа (с 15.10.2026) |

Особенности:

- `applications_end` у публичного предложения — **окончательный** срок: позднейшее из срока на
  сайте и конца графика. На нём держится удаление истёкших. Срок текущего этапа считается в
  шаге 3.
- `sheets_writer.ensure_header()` при подключении переписывает шапку A–AM. `sheets_writer.COLUMNS`
  описывает только A–AM и устарела; новые скрипты ищут колонки по имени в шапке.
- `build_lots_processed.py` берёт колонки по буквам: **не вставляйте колонки** в `lots`.

## `lots_processed`

Колонки: `brand`, `name`, `year`, `vin`, `plate`, `url`, `title`, `mileage_km`, `price_start`,
`price_current`, `region`, `applications_end`, `bidding_start`, `organizer_phone`,
`organizer_email`, `photo_url`, `status`, `bidding_periods`, `lot_kind`.

Пустые `brand`/`name`/`year` заполняются из названия лота, пустые `vin`/`plate` — из текста.
У ПП `price_current` и `applications_end` — текущего этапа на момент сборки.

## `lots_current_month`

Колонки `lots_processed` плюс:

| Колонка | Что |
|---|---|
| `autoru_price_low`, `autoru_price_high` | рыночная вилка Авто.ру |
| `autoru_tradein_low`, `autoru_tradein_high` | вилка trade-in (не используется в приложении) |
| `autoru_uncertainty_percent` | погрешность Авто.ру; 90+ — «оценка может быть неточной» |
| `autoru_mark`, `autoru_model`, `autoru_year`, `autoru_owners_count` | машина по VIN от Авто.ру |
| `autoru_engine_type`, `autoru_displacement`, `autoru_power`, `autoru_drive`, `autoru_transmission`, `autoru_modification` | характеристики модификации от Авто.ру (с 13.10.2026): топливо, объём см³, мощность л.с., привод, коробка, название «1.6 AT (110 л.с.)» |
| `autoru_accuracy_note` | «Оценка может быть неточной» у `ambiguous` |
| `autoru_status` | `ok`, `ambiguous`, `no_price`, `no_mileage`, `error: …` |
| `autoru_checked_at` | когда оценивали |
| `% below mkt` | процент к рынку, число в процентных пунктах (15.4 = 15,4%) |
| `estimated_mileage` | пробег по году, если настоящего нет |

На 11.10.2026: 1441 лот (816 — Московская область, 625 — Москва), оценка `ok` у 1251.

## Листы подборок

Те же колонки, что у `lots_current_month`. Состав — [Конвейер данных](pipeline.md#6-подборки--build_lot_selectionspy).

## `vin_cache` — справочник по VIN

`vin`, пробег TRONK (`mileage_probeg_*` — бессрочно), оценка Авто.ру (`autoru_*`,
`estimated_mileage` — 60 дней), `updated_at`. Нужен, чтобы купленное и посчитанное переживало
лот: машину выставляют снова, одни торги публикуются на нескольких площадках.

## Правила работы с таблицей

- **Числа — числами.** gspread пишет как есть (RAW): строка `"450000"` ложится текстом. Перед
  записью — `sheets_writer.numify_rows(header, rows)` для колонок из
  `sheets_writer.NUMERIC_COLUMNS`. Режим `USER_ENTERED` не использовать: даты `applications_end`
  станут датами Sheets, телефоны `+7…` — числами.
- Накопившийся текст вместо чисел чинит `python fix_numeric_cells.py`. Ячейка помнит формат:
  процентный формат в колонке пробега показывал 300 000 как `30000000%`.
- **Формулы** в листах, которые пересобираются (`lots_processed`, `lots_current_month`, подборки),
  бесполезны: стираются следующим прогоном.
- **Квота Google** — около 60 запросов записи в минуту. Записи копятся и пишутся пачками.
- Не запускать скрипты, пишущие в таблицу, одновременно с прогоном: пересборка листа сдвинет
  строки под ногами у другого скрипта.
- Все даты — текст `ГГГГ-ММ-ДД ЧЧ:ММ:СС`, московское время без пояса.
