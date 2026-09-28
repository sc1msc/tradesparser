# -*- coding: utf-8 -*-
r"""
Дайджест в Telegram-канал: тизер (2-3 самых интересных лота прямо в
сообщении) + кнопка на полную подборку, опубликованную как страница
Telegraph (см. telegraph_publish.py).

Источник данных - один из готовых срезов (лист вида "lots_top_gap",
"lots_budget_1m" и т.д. - см. build_lot_selections.py, ничего заново не
фильтруем). Какую подборку слать - спрашивается в начале запуска; список
подборок и их метаданные (лист/заголовок/вступление) - в selections.py.

Запуск вручную:  python send_digest.py
"""
import datetime
import html

import gspread
import requests
from google.oauth2.service_account import Credentials

import config
import selections
import telegraph_publish

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MONTHS_RU = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _fmt_price(value):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    return f"{n:,}".replace(",", " ") + " ₽"


def _lots_word(n):
    """Русское склонение: 1 лот, 2-4 лота, 5+ лотов (и 11-14 - тоже лотов)."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "лот"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "лота"
    return "лотов"


def _fmt_deadline(value):
    """'2026-09-22 14:00:00' -> ('22 сен, 14:00', дней_осталось_или_None)"""
    try:
        dt = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return value or "не указан", None
    label = f"{dt.day} {MONTHS_RU[dt.month - 1]}, {dt.strftime('%H:%M')}"
    days_left = (dt.date() - datetime.date.today()).days
    return label, days_left


def _row_dict(header, row):
    return {name: (row[i] if i < len(row) else "") for i, name in enumerate(header)}


def _load_lots(sheet_name):
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(config.SPREADSHEET_ID).worksheet(sheet_name)
    values = worksheet.get_all_values()
    if not values:
        return []
    header, data_rows = values[0], values[1:]
    return [_row_dict(header, row) for row in data_rows]


def _parse_percent(value):
    """Разбор '% below mkt' в число - тот же принцип, что и в
    build_lot_selections._to_number: десятичный разделитель - запятая,
    разделителя разрядов нет."""
    if not value:
        return None
    cleaned = str(value).replace("%", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fmt_gap_label(value):
    """Превращает '% below mkt' в подпись направления вместо голой 'скидки'.

    Ни Telegram (HTML в подписях/сообщениях), ни Telegraph не поддерживают
    цвет шрифта - только bold/italic и т.п. Вместо цвета используем
    цветной кружок-эмодзи (🟢/🔴), текст оборачивается в bold отдельно
    там, где формируется само сообщение."""
    n = _parse_percent(value)
    if n is None:
        return str(value)
    if n > 0:
        return f"🟢 ниже рынка на {n:g}%".replace(".", ",")
    if n < 0:
        return f"🔴 выше рынка на {abs(n):g}%".replace(".", ",")
    return "⚪ на уровне рынка"


def _lot_title(lot):
    brand = lot.get("brand") or lot.get("autoru_mark") or ""
    name = lot.get("name") or lot.get("autoru_model") or ""
    year = lot.get("year") or lot.get("autoru_year") or ""
    return f"{brand} {name}, {year}".strip()


# ---------------------------------------------------------- Telegraph ----

def _build_telegraph_content(lots, digest_intro):
    nodes = [
        {"tag": "p", "children": [
            f"Подборка на {datetime.date.today().strftime('%d.%m.%Y')} - "
            f"{len(lots)} {_lots_word(len(lots))} {digest_intro}."
        ]},
        {"tag": "hr"},
    ]
    for lot in lots:
        deadline_label, days_left = _fmt_deadline(lot.get("applications_end"))
        deadline_text = f"Заявки до {deadline_label}"
        if days_left is not None:
            deadline_text += f" ({days_left} дн.)" if days_left > 0 else " (сегодня)"

        nodes.append({"tag": "h4", "children": [_lot_title(lot)]})

        if lot.get("photo_url"):
            nodes.append({"tag": "figure", "children": [
                {"tag": "img", "attrs": {"src": lot["photo_url"]}},
            ]})

        nodes.append({"tag": "p", "children": [
            {"tag": "strong", "children": [_fmt_price(lot.get("price_current"))]},
            f"  (рынок {_fmt_price(lot.get('autoru_price_low'))}–{_fmt_price(lot.get('autoru_price_high'))}, ",
            {"tag": "strong", "children": [_fmt_gap_label(lot.get("% below mkt", ""))]},
            ")",
        ]})
        nodes.append({"tag": "p", "children": [
            f"{lot.get('region', 'регион не указан')}  •  {deadline_text}"
        ]})
        nodes.append({"tag": "p", "children": [
            {"tag": "a", "attrs": {"href": lot.get("url", "")}, "children": ["Смотреть лот →"]}
        ]})
        nodes.append({"tag": "hr"})
    return nodes


# ----------------------------------------------------------- Telegram ----

# Сайт торгов отдаёт фото так же неохотно, как и страницы лотов - сервер
# Telegram, пытаясь скачать photo по URL напрямую, получает отказ
# ("failed to get HTTP URL content"). Поэтому скачиваем фото сами (с теми
# же заголовками, что и в backfill_photo_urls.py) и грузим в Telegram уже
# байтами, а не ссылкой.
PHOTO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def _raise_telegram_error(resp, method):
    """Достаём настоящее описание ошибки из тела ответа Telegram, а не
    просто '400 Bad Request' от requests - иначе непонятно, что пошло не так."""
    try:
        result = resp.json()
        description = result.get("description", "")
    except ValueError:
        description = resp.text
    raise RuntimeError(f"Telegram {method} вернул ошибку {resp.status_code}: {description}")


def _send_telegram_message(text, button_text, button_url):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        },
    }
    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        _raise_telegram_error(resp, "sendMessage")
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendMessage вернул ошибку: {result}")
    return result["result"]


def _download_photo(photo_url):
    """Скачивает фото с сайта торгов сами - серверу Telegram сайт фото не отдаёт."""
    resp = requests.get(photo_url, headers=PHOTO_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.content


def _send_telegram_photo(photo_url, caption):
    photo_bytes = _download_photo(photo_url)

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": config.TELEGRAM_CHANNEL_ID,
        "caption": caption,
        "parse_mode": "HTML",
    }
    files = {"photo": ("photo.jpg", photo_bytes)}
    resp = requests.post(url, data=data, files=files, timeout=30)
    if not resp.ok:
        _raise_telegram_error(resp, "sendPhoto")
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendPhoto вернул ошибку ({photo_url}): {result}")
    return result["result"]


def _build_caption(lot):
    deadline_label, days_left = _fmt_deadline(lot.get("applications_end"))
    urgency = " ⏰" if days_left is not None and days_left <= 1 else ""
    title = html.escape(_lot_title(lot))
    region = html.escape(lot.get("region") or "регион не указан")
    deadline_label = html.escape(deadline_label)
    gap_label = html.escape(_fmt_gap_label(lot.get("% below mkt", "")))
    url = html.escape(lot.get("url", ""), quote=True)
    lines = [
        f"🚗 <b>{title}</b>",
        "",
        f"Цена: {_fmt_price(lot.get('price_current'))}",
        f"Рыночная оценка: {_fmt_price(lot.get('autoru_price_low'))}–{_fmt_price(lot.get('autoru_price_high'))}",
        f"<b>{gap_label}</b>{urgency}",
        "",
        f"{region} · Заявки до {deadline_label}",
        f'<a href="{url}">Смотреть лот →</a>',
    ]
    return "\n".join(lines)


def _pick_candidates_with_photo(lots, pool_size):
    """Идёт по уже отсортированным по выгодности лотам и собирает пул из
    тех, у кого ЕСТЬ фото - пропуская лоты без фото, пока не наберётся
    pool_size штук (или не кончится список)."""
    candidates = []
    for lot in lots:
        if lot.get("photo_url"):
            candidates.append(lot)
        if len(candidates) >= pool_size:
            break
    return candidates


def _prompt_manual_pick(candidates):
    print(f"\nКандидаты с фото (из топа по выгодности) - выберите, какие отправить в канал:\n")
    for i, lot in enumerate(candidates, 1):
        deadline_label, _ = _fmt_deadline(lot.get("applications_end"))
        print(f"  [{i}] {_lot_title(lot)} — {_fmt_price(lot.get('price_current'))}, "
              f"{_fmt_gap_label(lot.get('% below mkt', ''))}, до {deadline_label}")
        print(f"      фото: {lot.get('photo_url')}")
        print(f"      лот:  {lot.get('url')}")

    raw = input(
        f"\nНомера через запятую (Enter - первые {config.DIGEST_TEASER_COUNT} по умолчанию): "
    ).strip()
    if not raw:
        return candidates[: config.DIGEST_TEASER_COUNT]

    picked = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(candidates):
            picked.append(candidates[int(part) - 1])
    return picked or candidates[: config.DIGEST_TEASER_COUNT]


def run():
    selection = selections.prompt_choice()
    sheet_name = selection["sheet"]
    print(f"\nВыбрана подборка: {selection['title']} (лист '{sheet_name}')")

    print(f"Читаю '{sheet_name}'...")
    lots = _load_lots(sheet_name)
    if not lots:
        print(f"Лист '{sheet_name}' пуст, отправлять нечего.")
        return

    full_lots = lots[: config.DIGEST_FULL_COUNT]

    print(f"Публикую Telegraph-страницу ({len(full_lots)} лотов)...")
    telegraph_url = telegraph_publish.create_page(
        title=f"{selection['title']} — {datetime.date.today().strftime('%d.%m.%Y')}",
        content_nodes=_build_telegraph_content(full_lots, selection["digest_intro"]),
    )
    print(f"  -> {telegraph_url}")

    candidates = _pick_candidates_with_photo(lots, config.DIGEST_PHOTO_POOL_SIZE)
    if not candidates:
        print("\nНи у одного лота из топа нет фото - отправлю только текстовый тизер без фото.")
        teaser_lots = lots[: config.DIGEST_TEASER_COUNT]
    else:
        teaser_lots = _prompt_manual_pick(candidates)

    print(f"\nВ канал уйдёт {len(teaser_lots)} {_lots_word(len(teaser_lots))}:")
    for lot in teaser_lots:
        print(f"  - {_lot_title(lot)}")

    answer = input("\nОтправить в канал? (yes / нет): ").strip().lower()
    if answer not in ("yes", "y", "да"):
        print("Отменено (страница Telegraph уже опубликована, ссылка выше).")
        return

    for lot in teaser_lots:
        caption = _build_caption(lot)
        if lot.get("photo_url"):
            try:
                _send_telegram_photo(lot["photo_url"], caption)
            except (requests.exceptions.RequestException, RuntimeError) as exc:
                print(f"  не удалось отправить фото для «{_lot_title(lot)}»: {exc}")
                print("  отправляю текстом без фото...")
                _send_telegram_message(caption, "Смотреть лот →", lot.get("url", ""))
        else:
            _send_telegram_message(caption, "Смотреть лот →", lot.get("url", ""))
        print(f"  отправлено: {_lot_title(lot)}")

    remaining = max(len(lots) - len(teaser_lots), 0)
    closing_text = (
        f"Ещё {remaining} {_lots_word(remaining)} в подборке «{selection['title']}» 👇"
    )
    _send_telegram_message(closing_text, "Смотреть все лоты →", telegraph_url)

    print("\nГотово, дайджест отправлен.")


if __name__ == "__main__":
    run()