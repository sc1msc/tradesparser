# Архитектура бота: торги по банкротству (авто) → Google Таблица

## Общая идея

Три независимых, отдельно запускаемых этапа, связанных только через Google Таблицу:

1. **Сбор** (`main.py`) — находит лоты на сайте-агрегаторе торгов, пишет в таблицу. Безопасно гонять часто.
2. **Оценка TRONK** (`evaluate_tronk.py`) — платный API, дополняет строки. Запускается вручную, маленькими партиями.
3. **Оценка Авито** (`evaluate_avito_browser.py`) — бесплатно, но через эмуляцию браузера (антибот). Тоже вручную, партиями.

Этапы 2 и 3 не зависят друг от друга напрямую, но 3-й использует данные, оставленные 2-м (марка/модель/год), если они уже есть — это не связь в коде, а просто общая таблица.

---

## Карта файлов

| Файл | Роль |
|---|---|
| `config.py` | Все настройки: фильтры поиска, лимиты, паузы, ключи API, доступ к таблице |
| `nextjs_json.py` | Общий хелпер: достаёт JSON из Next.js-страниц сайта торгов |
| `parse_search.py` | Парсинг страницы поиска (список лотов + пагинация) |
| `parse_lot.py` | Парсинг карточки одного лота (полные данные) |
| `sheets_writer.py` | Слой доступа к Google Таблице: схема колонок, чтение, точечная и построчная запись |
| `main.py` | Оркестратор сбора: страницы поиска → карточки лотов → таблица |
| `tronk_valuation.py` | Обёртка над платным API TRONK (`avgpricebyvin`) |
| `evaluate_tronk.py` | Оркестратор массовой оценки TRONK (с лимитом и подтверждением) |
| `avito_valuation.py` | Логика работы с внутренним API Авито (резолв VIN, сборка запроса цены, разрешение неоднозначных полей) |
| `evaluate_avito_browser.py` | Оркестратор оценки Авито через Playwright (реальный браузер) |

Зависимости (кто что импортирует):

```
main.py               → parse_search, parse_lot, sheets_writer, config
parse_search.py        → nextjs_json
parse_lot.py            → nextjs_json
evaluate_tronk.py     → tronk_valuation, sheets_writer, config
evaluate_avito_browser.py → avito_valuation, sheets_writer, config, playwright
```

---

## Схема Google Таблицы (39 колонок, A–AM)

| Колонка | Поле | Кто пишет | Когда |
|---|---|---|---|
| A | `lot_id` | main.py | сбор |
| B | `url` | main.py | сбор |
| C | `title` | main.py | сбор |
| D | `status` | main.py | сбор |
| E | `vin` | main.py | сбор |
| F | `plate` (госномер) | main.py | сбор |
| G | `mileage_km` (пробег) | main.py | сбор |
| H | `price_start` | main.py | сбор |
| I | `price_current` | main.py | сбор |
| J | `currency` | main.py | сбор |
| K | `region` | main.py | сбор |
| L | `trade_kind` | main.py | сбор |
| M | `platform` | main.py | сбор |
| N | `applications_start` | main.py | сбор |
| O | `applications_end` | main.py | сбор |
| P | `bidding_start` | main.py | сбор |
| Q | `organizer_name` | main.py | сбор |
| R | `organizer_phone` | main.py | сбор |
| S | `organizer_email` | main.py | сбор |
| T | `manager_name` | main.py | сбор |
| U | `manager_sro` | main.py | сбор |
| V | `debtor_name` | main.py | сбор |
| W | `avito_price_low` | evaluate_avito_browser.py | оценка Авито |
| X | `avito_price_high` | evaluate_avito_browser.py | оценка Авито |
| Y | `scraped_at` | main.py | сбор |
| Z | `tronk_price_avg` | evaluate_tronk.py | оценка TRONK |
| AA | `tronk_price_min` | evaluate_tronk.py | оценка TRONK |
| AB | `tronk_price_max` | evaluate_tronk.py | оценка TRONK |
| AC | `tronk_mileage_avg` | evaluate_tronk.py | оценка TRONK |
| AD | `tronk_status` | evaluate_tronk.py | оценка TRONK |
| AE | `tronk_checked_at` | evaluate_tronk.py | оценка TRONK |
| AF | `avito_year` | evaluate_avito_browser.py | оценка Авито |
| AG | `avito_owners` | **вы вручную** | до запуска оценки Авито |
| AH | `avito_accuracy_note` | evaluate_avito_browser.py | оценка Авито |
| AI | `avito_status` | evaluate_avito_browser.py | оценка Авито |
| AJ | `avito_checked_at` | evaluate_avito_browser.py | оценка Авито |
| AK | `tronk_marka` | evaluate_tronk.py | оценка TRONK |
| AL | `tronk_model` | evaluate_tronk.py | оценка TRONK |
| AM | `tronk_year` | evaluate_tronk.py | оценка TRONK |

Заголовки (строка 1) `sheets_writer.ensure_header()` перезаписывает автоматически при каждом подключении, если они не совпадают с этим списком — руками их вписывать не нужно.

---

## Алгоритм: `main.py` (сбор лотов)

1. Подключиться к таблице, получить текущее состояние (`SheetState`) — какие `lot_id` уже есть.
2. Цикл по страницам поиска, пока `page ≤ config.MAX_PAGES`:
   1. Построить URL страницы поиска (`parse_search.build_search_url`).
   2. Скачать HTML, распарсить (`parse_search.parse_search_html`) → список лотов на странице + информация о пагинации.
   3. Для каждого лота, которого **ещё нет** в таблице:
      - подождать `DELAY_BETWEEN_LOT_REQUESTS`;
      - скачать HTML карточки лота, распарсить (`parse_lot.parse_lot_html`) → полные данные;
      - собрать итоговую строку, записать в таблицу (`SheetState.upsert`) — колонки Авито/TRONK остаются пустыми;
   4. Если следующей страницы нет — остановиться; иначе перейти на следующую, подождать `DELAY_BETWEEN_SEARCH_PAGES`.
3. Напечатать итог (сколько лотов добавлено).

Особенность записи: `SheetState` сам считает номер строки для каждого лота и пишет в явный диапазон (`A5:AM5`) — без автоопределения таблицы Google Sheets API (это раньше вызывало сдвиг колонок).

---

## Алгоритм: `parse_search.py`

Сайт — на Next.js, данные лежат прямо в HTML как JSON (см. ниже про `nextjs_json.py`), а не в вёрстке.

1. `extract_combined_payload(html)` — склеить все `self.__next_f.push(...)` payload'ы в одну строку.
2. Найти в этой строке `"initialLots":[...]` (карточки лотов) и `"initialMeta":{...}` (пагинация).
3. Для каждой карточки: `lot_id`, `url` (собирается как `<домен>/lot/<id>`), `title`, регион, площадка, цены — берутся напрямую из JSON. VIN/госномер/год/пробег — регуляркой из `title` (бонус-фолбэк, основной источник этих полей — `parse_lot.py`).
4. Пагинация: `current_page < last_page` → `has_next`.

---

## Алгоритм: `parse_lot.py`

1. `extract_combined_payload(html)` (тот же хелпер).
2. Найти `"lot":{...}` — единый объект со всеми данными карточки.
3. Прямое отображение полей: `title`, `status.title`, `region.title`, `organizer.*`, `arbitration_administrator.*` (управляющий), `debtor.*` (должник), `stages.*` (даты).
4. VIN: сперва из `lot["vins"]`, если пусто — регуляркой из текста.
5. Госномер и пробег — регуляркой из текста (`title` + `information`).

---

## Алгоритм: `nextjs_json.py` (общий хелпер)

- `extract_combined_payload(html)` — регуляркой находит все `self.__next_f.push([1,"..."])`, `json.loads` каждый, склеивает текстовые части.
- `find_json_value(text, key, kind)` — ищет `"key":{` или `"key":[`, вырезает сбалансированный по скобкам фрагмент (корректно игнорируя скобки внутри строк), парсит как JSON.

---

## Алгоритм: `sheets_writer.py`

- `COLUMNS` — канонический список колонок (см. таблицу выше), порядок = порядок столбцов A…AM.
- `connect()` — авторизация через service account, открытие листа, `ensure_header()`.
- `SheetState` — используется **только** `main.py` при первичном сборе: держит в памяти `lot_id → номер_строки`, пишет явным диапазоном.
- `read_rows()` / `set_cell()` / `col_index()` — используются `evaluate_tronk.py` и `evaluate_avito_browser.py`: прочитать все строки, точечно обновить одну ячейку, не трогая остальные.

---

## Алгоритм: `tronk_valuation.py`

- `get_avg_price(api_key, vin, region_id)` — один платный GET-запрос к `data.tronk.info`.
- `extract_valuation(raw)` — разбирает ответ на три ветки: `ok` / `no_data` / `error`, достаёт `price_avg/min/max`, `probeg_avg`, а также **марку/модель/год** (бесплатный побочный продукт того же запроса — используется потом Авито-скриптом).
- Режим командной строки (`python tronk_valuation.py <VIN>`) — тест на одном VIN, требует подтверждения `yes`, в таблицу не пишет.

---

## Алгоритм: `evaluate_tronk.py` (массовая оценка TRONK)

1. Проверить, что `TRONK_API_KEY` задан.
2. Подключиться к таблице, прочитать все строки (`read_rows`).
3. Отобрать кандидатов: есть `vin`, и `tronk_status` не `ok`/`no_data` (ошибки пробуются повторно).
4. Обрезать список по `config.TRONK_MAX_PER_RUN`, показать точный список и запросить подтверждение `yes` (это платные запросы).
5. Для каждого кандидата: запрос → разбор → точечная запись 8 полей (`tronk_price_*`, `tronk_mileage_avg`, `tronk_marka/model/year`, `tronk_status`, `tronk_checked_at`).
6. Пауза `DELAY_BETWEEN_TRONK_REQUESTS` между запросами.

---

## Алгоритм: `avito_valuation.py` (библиотека логики Авито)

- `make_session()` / `resolve_vin()` / `get_price()` — прямые HTTP-запросы к внутреннему API Авито (историческая версия; сейчас ловит 429/капчу Qrator при массовом использовании — оставлена как переиспользуемая логика для браузерного скрипта).
- `resolve_ambiguous_fields(resolve_data, hints)` — когда Авито сам не смог определить поле (например, модель или год — см. попап «Укажите параметры»), пытается его доопределить:
  1. если в списке вариантов только один — берёт его (не догадка, факт);
  2. иначе ищет совпадение с `hints` (текстовые подсказки марка/модель/год);
  3. если совпадения нет — поле остаётся неразрешённым.
- `build_price_payload()` — собирает тело запроса цены из уже известных `currentValueId` + владельцы/пробег.
- `parse_price_response()` — достаёт `price_low`/`price_high` из `priceDescription.priceRanges` (плюс текстовый fallback).

---

## Алгоритм: `evaluate_avito_browser.py` (оценка через браузер)

1. Подключиться к таблице, прочитать строки, отобрать кандидатов (есть `vin`, `avito_status` ≠ `ok`).
2. Обрезать по `config.AVITO_BROWSER_MAX_PER_RUN`, показать список, запросить подтверждение `yes`.
3. Открыть Playwright Chromium (по умолчанию `headless=False` — так меньше шансов словить антибот).
4. Для каждого лота:
   1. Открыть `avito.ru/evaluation/cars`; если показалась капча Qrator — **пауза**, ждём, пока вы решите её руками в видимом окне.
   2. Ввести VIN, нажать «Оценить» (реальными действиями в браузере) — перехватить ответ `resolve/number`.
   3. Собрать подсказки марка/модель/год: сначала из `tronk_marka/model/year` (уже оплачено), если пусто — регуляркой из `title` лота.
   4. `resolve_ambiguous_fields()` — доопределить то, что Авито не смог сам. Если что-то осталось неразрешённым — лот помечается ошибкой (не угадываем).
   5. Владельцы: `avito_owners` из таблицы, иначе `"4+"`. Пробег: `mileage_km` (очищенный от нецифровых символов), иначе `(текущий_год − avito_year) × 20000`.
   6. Отправить запрос цены через `fetch()` **внутри той же браузерной страницы** (не отдельным Python-запросом) — использует настоящую сессию/куки.
   7. Записать `avito_year`, `avito_price_low/high`, `avito_status="ok"`, `avito_checked_at`; если владельцы/пробег были не заданы или что-то доопределялось по подсказке — `avito_accuracy_note = "Оценка может быть неточной"`.
   8. Пауза `DELAY_BETWEEN_AVITO_BROWSER_REQUESTS` + случайный джиттер.
5. Закрыть браузер, напечатать итог.

---

## Типичный порядок запуска

```
python main.py                     # сбор новых лотов — можно часто
python evaluate_tronk.py           # опционально, платно, маленькими партиями
python evaluate_avito_browser.py   # оценка Авито - выиграет от подсказок TRONK, если он уже был запущен
```

---

## Известные ограничения

- Сайт торгов запрещает ботов в `robots.txt` — не гоняйте сбор слишком часто/агрессивно.
- Авито (даже через браузер) может показать капчу Qrator при активном использовании — скрипт ставит выполнение на паузу для ручного решения, но полностью исключить это нельзя.
- `resolve_ambiguous_fields` сопоставляет подсказки простым текстовым совпадением (без транслитерации) — для марок с сильно расходящимся написанием (кириллица/латиница) сопоставление может не сработать, тогда лот просто помечается ошибкой, а не оценивается неверно.
- Пробег на сайте торгов не всегда публикуется отдельным полем — иногда его просто нет.
