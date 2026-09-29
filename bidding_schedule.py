# -*- coding: utf-8 -*-
r"""
График снижения цены у "публичного предложения" - ОДНА реализация на всех
потребителей (main.py, build_lots_processed.py, fill_missing_mileage.py,
send_digest.py).

Зачем: у публичного предложения цена снижается ступенями по графику
(в JSON карточки лота - массив bidding_periods: begin, end, bid_end,
price, is_current). А в карточке "сверху" лежат только:
  - stages.end_bid_time - конец приёма заявок ПОСЛЕДНЕГО периода, то есть
    окончание торгов целиком (на странице - "Конец приема заявок");
  - current_price - цена периода, который сайт считает текущим.
Лот парсится один раз, поэтому в листе "lots" навсегда оставались цена
на момент первого парсинга и окончательный дедлайн - а дайджест
показывал устаревшую цену, неверный "% below mkt" и дату, до которой
цена ещё несколько раз упадёт.

Поэтому весь график хранится в листе "lots" (колонка bidding_periods,
компактный JSON: [[bid_end, price], ...]), а текущий период вычисляется
по ВРЕМЕНИ на момент сборки/отправки: первый период, у которого bid_end
ещё не наступил. Флаг is_current с сайта сознательно не используем: после
завершения торгов он "замерзает" на периоде, в котором пришла заявка (на
примере лота 7184365: торги завершены, is_current и current_price - на
4-м периоде, хотя по времени идёт уже 5-й), а для идущих торгов сайт
может переключить его позже, чем наступил bid_end.

applications_end в самом листе "lots" остаётся окончательным дедлайном
(stages.end_bid_time) - на нём держится remove_expired_lots() в
sheets_writer.py: лот нельзя удалять, пока не прошёл последний период.
Цену и дедлайн ТЕКУЩЕГО периода подставляет build_lots_processed.py (и
ещё раз - send_digest.py в момент отправки).

Досрочное завершение торгов (пришла заявка, отмена, приостановка) по
графику не вычислить - для этого main.py на каждом запуске заново читает
карточки идущих публичных предложений и обновляет status (см.
is_closed_status ниже и refresh_public_offers в main.py).

Модуль без зависимостей (ни gspread, ни config).
"""
import datetime
import json

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Статусы, при которых лот больше не интересен, даже если по графику
# приём заявок ещё идёт. Та же логика, что у мини-аппа
# (miniapp/backend/app/lots.py, CLOSED_STATUS_MARKERS).
CLOSED_STATUS_MARKERS = ("отмен", "заверш", "приостанов", "аннулир")


def is_public_offer(trade_kind):
    """trade_kind - текст формы торгов из листа ("Открытые торги
    посредством публичного предложения")."""
    return "публичн" in (trade_kind or "").lower()


def is_closed_status(status):
    status = (status or "").lower()
    return any(m in status for m in CLOSED_STATUS_MARKERS)


def pack_periods(raw_periods):
    """bidding_periods из JSON карточки -> строка для ячейки листа.
    Храним только то, что нужно для расчёта: [[bid_end, price], ...].
    Пустой график -> пустая строка (у аукционов его нет вовсе)."""
    packed = []
    for p in raw_periods or []:
        bid_end = p.get("bid_end") or p.get("end")
        if bid_end:
            packed.append([bid_end, p.get("price")])
    if not packed:
        return ""
    packed.sort(key=lambda pair: pair[0])  # формат даты сортируется как строка
    return json.dumps(packed, ensure_ascii=False, separators=(",", ":"))


def unpack_periods(text):
    """Строка из ячейки -> [(bid_end: datetime, price или None), ...].
    Битый JSON/даты -> пустой список (лот считается как аукцион - берутся
    price_current/applications_end из листа, как было раньше)."""
    if not text:
        return []
    try:
        pairs = json.loads(text)
        return [(datetime.datetime.strptime(bid_end, DATE_FORMAT), price) for bid_end, price in pairs]
    except (ValueError, TypeError):
        return []


def current_period(periods_text, now=None):
    """
    Текущий период графика на момент now:
      (цена, дедлайн "YYYY-MM-DD HH:MM:SS", номер периода с 1, всего периодов)
    Если все периоды прошли - последний (дедлайн в прошлом, лот отсеется
    как истёкший). Если графика нет - None.
    """
    periods = unpack_periods(periods_text)
    if not periods:
        return None
    now = now or datetime.datetime.now()
    idx = next((i for i, (bid_end, _) in enumerate(periods) if bid_end > now), len(periods) - 1)
    bid_end, price = periods[idx]
    return price, bid_end.strftime(DATE_FORMAT), idx + 1, len(periods)


def effective_price_and_deadline(price_current, applications_end, periods_text, now=None):
    """
    Цена и дедлайн, которые надо показывать/фильтровать: для публичного
    предложения с графиком - текущего периода, иначе - как в листе.
    Цена возвращается в формате листа (десятичный разделитель - запятая,
    как пишет sheets_writer.SheetState.upsert). Если у периода цена не
    указана - остаётся price_current.
    """
    state = current_period(periods_text, now)
    if state is None:
        return price_current, applications_end
    price, deadline, _, _ = state
    if price is None:
        return price_current, deadline
    if isinstance(price, float) and price.is_integer():
        price = int(price)
    return str(price).replace(".", ","), deadline
