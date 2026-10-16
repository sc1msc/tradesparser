# -*- coding: utf-8 -*-
r"""
Новые лоты прямо с электронных торговых площадок (ЭТП), без агрегатора.

Зачем. С 11.10.2026 агрегатор перестал публиковать новые лоты (поиск отвечал,
но всё в нём уже было в таблице), а и в обычное время пропускал часть лотов:
16.10.2026 на ТоргГрупп по Москве и области шёл приём заявок по 251 лоту, у нас
было 157, из недостающих 90 - машины (44 выставлены в октябре, 46 - в
июле-сентябре). Сбор с площадок идёт ВМЕСТЕ с агрегатором, а не вместо: для
площадок без своего сборщика агрегатор остаётся единственным источником.

Кто собирает. Сервер мини-аппа (miniapp/backend/app/etp_collect.py, фоновый
поток) несколько раз в сутки обходит площадки и складывает лоты в свою базу.
ПК забирает их в шаге 1 одним запросом (GET /api/etp-lots, main.pull_etp_lots)
и дописывает в лист lots то, чего там нет. В таблицу пишет только ПК: прогон
удаляет строки и держит номера строк в памяти, и запись с сервера посреди
прогона сдвинула бы их (решение владельца 16.10.2026).

Идентификатор. По 127-ФЗ (ст. 110, 139) машина проходит торги -> повторные
торги -> публичное предложение; каждые торги - своё сообщение в ЕФРСБ и свой
номер на площадке, в одних торгах может быть несколько лотов. Строка листа -
лот торгов (своя цена, срок, статус, итог); машина - VIN (мини-апп собирает
лоты одной машины, избранное следует за машиной). Ключ строки - лот на площадке
(listing_key: адрес страницы лота), а не номер ЕФРСБ: изменение объявления
публикуется в ЕФРСБ отдельным сообщением с новым номером, хотя торги те же, а
адрес лота на площадке не меняется. Номер ЕФРСБ хранится полем (efrsb_number).
lot_id - число (мини-апп и ссылки «Поделиться» вида lot<цифры>): лоты агрегатора
сохраняют его номера, лоты с площадок получают ETP_ID_BASE + код площадки *
10^8 + номер лота на площадке - всегда тот же для того же лота, без таблиц
соответствия (lot_id_for). У МЭТС лот - «<номер торгов>-<номер лота>», номер для
lot_id - номер торгов * 100 + номер лота.

Повторы (Dedup). Тот же лот у агрегатора узнаётся по адресу лота на ЭТП (у лотов
агрегатора он в etp_url), иначе - по VIN среди открытых лотов (одна машина
одновременно только в одних торгах) или по названию и начальной цене.

Что отдаёт сборщик (read_lot) - те же поля, что parse_lot.parse_lot_html у
карточки агрегатора (статусы - словами агрегатора, даты - "ГГГГ-ММ-ДД ЧЧ:ММ:СС"),
плюс то, чего у агрегатора нет: photos (все фото - оригиналы с площадки, без
водяных знаков агрегатора), periods (график для кэша мини-аппа), efrsb_number,
trade_number, lot_number, applications_count (число поданных заявок).

Площадки (ТоргГрупп, МЭТС) - классы с host, platform, list_lots(get) и read_lot(get, url);
cars_only - список уже отфильтрован категорией «легковой» самой площадки. Новая
площадка: класс + запись в COLLECTORS и в PLATFORM_CODES (код не менять, на нём
держатся номера лотов). get(url) -> текст страницы (на сервере - status_refresh.
fetch, в проверках - подмена). Модуль общий для ПК и сервера (Docker-образ
копирует его, как etp_status.py). Без зависимостей.
"""
import datetime
import html as html_lib
import json
import re
from urllib.parse import urlsplit

import bidding_schedule
import etp_status
import lot_metrics

ETP_ID_BASE = 9_000_000_000
ETP_ID_PLATFORM_STEP = 100_000_000
# Код площадки в номере лота. Только дописывать: смена кода сменит номера лотов.
PLATFORM_CODES = {"bankrot.torggroup.org": 1, "m-ets.ru": 2}

# Регионы сбора (как SEARCH_PARAMS агрегатора в config.py) - названия как у агрегатора.
REGIONS = {77: "г. Москва", 50: "Московская область"}

DATE_FORMAT = bidding_schedule.DATE_FORMAT


def lot_id_for(host, number):
    """Номер лота с площадки для листа и мини-аппа. Неизвестная площадка / не число - None."""
    code = PLATFORM_CODES.get((host or "").lower())
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if code is None or not 0 < number < ETP_ID_PLATFORM_STEP:
        return None
    return str(ETP_ID_BASE + code * ETP_ID_PLATFORM_STEP + number)


def is_etp_lot_id(lot_id):
    """Лот собран с площадки (а не с агрегатора, у которого номера ~7 млн)."""
    try:
        return int(str(lot_id).strip()) >= ETP_ID_BASE
    except (TypeError, ValueError):
        return False


def listing_key(url):
    """Адрес лота на ЭТП -> ключ для сравнения: без схемы, www, регистра хоста, якоря и
    завершающего "/". Пусто/ЕФРСБ/агрегатор - None (у торгов «вне ЭТП» лота на ЭТП нет)."""
    if not url or not url.startswith("http") or "fedresurs" in url or etp_status.AGGREGATOR_HOST in url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    key = host + parts.path.rstrip("/")
    return key + ("?" + parts.query if parts.query else "")


# --- что считать машиной: как категория «легковые» у агрегатора (легковые и
# лёгкие фургоны; грузовиков, спецтехники и недвижимости в листе нет) ---
_VEHICLE_WORDS = re.compile(r"автомоб|легков|транспортн\w*\s+средств|\bтс\b|фургон|кроссовер|внедорожник", re.I)
_NOT_VEHICLE = re.compile(
    r"трактор|экскаватор|погрузчик|самосвал|автобус|мотоцикл|мопед|скутер|полуприцеп|тягач|катер|лодк|яхт|"
    r"квадроцикл|снегоход|комбайн|бульдозер|автокран|спецтехник|квартир|комнат[аы]\b|помещени|земельн|"
    r"жилой\s+дом|здани|сооружени|нежил|гараж|машино-?мест", re.I)


def is_vehicle(title, description=""):
    """Легковая машина (или лёгкий фургон) по названию лота: VIN или слова «автомобиль»,
    «легковой», «транспортное средство», и ничего из спецтехники и недвижимости."""
    title = title or ""
    if _NOT_VEHICLE.search(title):
        return False
    return bool(lot_metrics.find_vin(title) or _VEHICLE_WORDS.search(title)
                or (lot_metrics.find_vin(description or "") and _VEHICLE_WORDS.search(description or "")))


# --- общий разбор страниц ---

def text_of(fragment):
    """HTML-фрагмент -> текст в одну строку."""
    text = re.sub(r"<br\s*/?>", " ", fragment or "", flags=re.I)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def money(value):
    """«1 600 000,00» -> 1600000; пусто/мусор -> None."""
    s = re.sub(r"[^\d,.]", "", (value or "").replace("\xa0", "")).replace(",", ".")
    try:
        return int(round(float(s))) if s else None
    except ValueError:
        return None


def ru_datetime(value):
    """«21.01.2027 08:00» -> «2027-01-21 08:00:00» (формат дат листа); не дата - None."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", value or "")
    if not m:
        return None
    d, mo, y, hh, mm = m.groups()
    try:
        return datetime.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0)).strftime(DATE_FORMAT)
    except ValueError:
        return None


def phone_digits(value):
    """«+7 (912) 323-03-56» -> «9123230356» (как телефоны агрегатора в листе)."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    return digits or None


# Статус лота на площадке -> подпись, как пишет агрегатор (их понимают
# bidding_schedule.is_closed_status, lots.py мини-аппа и подборки).
STATUS_ANNOUNCED = "Торги объявлены"
STATUS_OPEN = "Идёт приём заявок"
STATUS_PENDING = "Приём заявок завершён"


def aggregator_status(raw):
    """Статус площадки -> (подпись агрегатора, state etp_status). Лот, который ещё не
    опубликован или отклонён площадкой, - (None, None)."""
    t = etp_status._norm(raw)
    if not t or "отклонен" in t or "ожидание подтверждения" in t:
        return None, None
    if t.startswith("подтвержден") or "объявлен" in t:
        return STATUS_ANNOUNCED, "open"
    if "ожидание начала" in t or "обработка заявок" in t or "идет торг" in t:  # ТоргГрупп: заявки уже не принимают
        return STATUS_PENDING, "pending"
    found = etp_status.classify(t)
    if found is None:
        return None, None
    state, outcome = found
    if state == "closed":
        return etp_status.OUTCOME_TEXT[outcome], state
    if state == "pending":
        return STATUS_PENDING, "pending"
    return STATUS_OPEN, "open"


# --- ТоргГрупп (bankrot.torggroup.org) ---

class TorgGroup:
    """Список лотов - /Trade/AllSearch (фильтры: регион, статус лота; 20 строк на
    страницу, свежие торги сверху), лот - /TradeLot/View/<id> (статус, цены, график,
    фото, номер ЕФРСБ), торги - /Trade/View/<id> (организатор, управляющий, должник).
    Всё - обычные страницы без скриптов и защиты от ботов (проверено 16.10.2026)."""

    host = "bankrot.torggroup.org"
    platform = "Электронная торговая площадка «ТоргГрупп»"
    base = "https://bankrot.torggroup.org"
    # Статусы лота в фильтре списка: 32 «Подтвержден» (торги объявлены, приём ещё не
    # начался), 34 «Прием заявок». Остальные новых лотов не дают.
    list_states = (32, 34)
    trade_types = "32,1,33,34"  # аукционы, публичные предложения, конкурсы
    page_size = 20
    max_pages = 30  # защита от бесконечного цикла (16.10.2026 - не больше 9 страниц)

    def list_url(self, region, state, page):
        return (f"{self.base}/Trade/AllSearch?pageSize={self.page_size}&currentPage={page}&sortBy=TradeId"
                f"&asc=False&types={self.trade_types}&RegionId={region}&LotStateId={state}")

    def list_lots(self, get, regions=REGIONS, sleep=None):
        """-> [stub]: url, key, lot_number, trade_number, title, price_start, applications_start,
        applications_end, list_status, region. Только машины (is_vehicle)."""
        out = {}
        for region in regions:
            for state in self.list_states:
                for page in range(1, self.max_pages + 1):
                    html = get(self.list_url(region, state, page))
                    rows = self.parse_list(html)
                    for stub in rows:
                        stub["region"] = REGIONS.get(region)
                        out.setdefault(stub["key"], stub)
                    if sleep:
                        sleep()
                    total = re.search(r"TotalPages=(\d+)", html)
                    if not rows or not total or page >= int(total.group(1)):
                        break
        return [s for s in out.values() if is_vehicle(s["title"])]

    def parse_list(self, html):
        stubs = []
        for tr in re.findall(r"<tr.*?</tr>", html or "", re.S):
            lot = re.search(r'href="/TradeLot/View/(\d+)"', tr)
            if not lot:
                continue
            cells = [text_of(c) for c in re.findall(r"<td.*?</td>", tr, re.S)]
            if len(cells) < 8:
                continue
            url = f"{self.base}/TradeLot/View/{lot.group(1)}"
            stubs.append({
                "url": url, "key": listing_key(url), "lot_number": lot.group(1), "trade_number": cells[0],
                "title": cells[2], "price_start": money(cells[3]), "applications_start": ru_datetime(cells[5]),
                "applications_end": ru_datetime(cells[6]), "list_status": cells[7],
            })
        return stubs

    @staticmethod
    def sections(html):
        """Пары «подпись: значение» страницы по разделам (<label> - заголовок раздела):
        {(раздел, подпись): значение}; без раздела - (\"\", подпись)."""
        out = {}
        section = ""
        token = re.compile(r'<label>(.*?)</label>|<div class="left_column">(.*?)</div>\s*'
                           r'<div class="right_column">(.*?)</div>', re.S)
        for m in token.finditer(html or ""):
            if m.group(1) is not None:
                section = text_of(m.group(1))
                continue
            label = text_of(m.group(2)).rstrip(":").strip()
            out.setdefault((section, label), text_of(m.group(3)))
        return out

    @staticmethod
    def field(sections, label, section=None):
        """Значение по началу подписи (подписи длинные: «Дата и время (МСК) окончания ...»)."""
        label = label.lower()
        for (sec, lab), value in sections.items():
            if lab.lower().startswith(label) and (section is None or sec.lower().startswith(section.lower())):
                return value
        return None

    def parse_periods(self, html):
        """Интервалы снижения цены -> [{begin, end, bid_end, price}] (как bidding_periods агрегатора)."""
        m = re.search(r'id="divLotIntervalViewTable".*?<tbody>(.*?)</tbody>', html or "", re.S)
        periods = []
        for tr in re.findall(r"<tr.*?</tr>", m.group(1) if m else "", re.S):
            cells = [text_of(c) for c in re.findall(r"<td.*?</td>", tr, re.S)]
            if len(cells) < 7:
                continue
            begin, _, bid_end, end = (ru_datetime(c) for c in cells[:4])
            price = money(cells[6])
            if bid_end and price:
                periods.append({"begin": begin, "end": end or bid_end, "bid_end": bid_end, "price": price})
        periods.sort(key=lambda p: p["bid_end"])
        return periods

    def read_lot(self, get, url, with_trade=True):
        """Страница лота (+ страница торгов, если with_trade) -> поля строки листа (как
        parse_lot.parse_lot_html) и данные для мини-аппа. Лот не опубликован - parse_error."""
        html = get(url)
        number = re.search(r"/TradeLot/View/(\d+)", url)
        s = self.sections(html)
        f = lambda label, section=None: self.field(s, label, section)  # noqa: E731
        title = f("Наименование", "Информация о лоте") or f("Наименование")
        raw_status = f("Статус", "Информация о лоте") or ""
        status, state = aggregator_status(raw_status)
        if not title or not status:
            return {"url": url, "lot_id": None, "title": title,
                    "parse_error": f"на странице лота нет названия или статуса ({raw_status or 'пусто'})"}
        head = re.search(r"Информация об?\s+(аукционе|публичном предложении|конкурсе)\s*№\s*(\d+)", text_of(html))
        kind = head.group(1) if head else ""
        trade_number = head.group(2) if head else None
        open_form = (f("Форма представления предложений") or "").lower().startswith("откр")
        if kind == "публичном предложении":
            trade_kind = ("Открытые" if (f("Форма проведения") or "").lower().startswith("откр") else "Закрытые") \
                + " торги посредством публичного предложения"
        elif kind == "конкурсе":
            trade_kind = "Открытый конкурс"
        else:
            trade_kind = "Открытый аукцион с " + ("открытой" if open_form else "закрытой") \
                + " формой представления предложений о цене"
        periods = self.parse_periods(html)
        packed = bidding_schedule.pack_periods(periods)
        price_start = money(f("Начальная цена продажи"))
        price_current = money(f("Текущая цена")) or price_start
        description = f("Сведения об имуществе") or title
        photos = []
        for pid in dict.fromkeys(re.findall(r'<img src="(/Picture/Show/\d+)"', html)):
            photos.append({"full": self.base + pid, "thumb": self.base + pid})
        applications_end = ru_datetime(f("Дата и время (МСК) окончания представления заявок"))
        count = re.search(r"Количество предоставленных заявок[^:]*:\s*(\d+)", html)
        region = f("Регион местонахождения имущества")
        if region and region.replace(" ", "").lower() in ("г.москва", "москва"):
            region = REGIONS[77]
        data = {
            "url": url,
            "lot_id": lot_id_for(self.host, number.group(1) if number else None),
            "title": title,
            "status": status,
            "etp_state": state,
            "etp_status": raw_status,
            "vin": lot_metrics.find_vin(title) or lot_metrics.find_vin(description),
            "vins_all": lot_metrics.lot_vins((title + " " + description).upper()),
            "plate": lot_metrics.find_plate(title) or lot_metrics.find_plate(description),
            "mileage_km": _mileage(description) or _mileage(title),
            "photo_url": photos[0]["full"] if photos else None,
            "photos": photos,
            "region": region,
            "price_start": price_start,
            "price_current": price_current,
            "currency": "RUB",
            "trade_kind": trade_kind,
            "trade_section": "Банкротство",
            "platform": self.platform,
            "etp_url": url,
            "applications_start": ru_datetime(f("Дата и время (МСК) начала представления заявок")),
            "applications_end": bidding_schedule.final_deadline(applications_end, packed) or applications_end,
            "bidding_periods": packed,
            "periods": periods,
            "bidding_start": ru_datetime(f("Дата и время (МСК) начала представления предложений")),
            "description": description,
            "efrsb_number": f("Номер сообщения в ЕФРСБ"),
            "trade_number": trade_number,
            "lot_number": number.group(1) if number else None,
            "applications_count": int(count.group(1)) if count else None,
        }
        if with_trade and trade_number:
            data.update(self.read_trade(get, trade_number))
        return data

    def read_trade(self, get, trade_number):
        """Страница торгов: организатор, контакт, управляющий, должник."""
        s = self.sections(get(f"{self.base}/Trade/View/{trade_number}"))
        f = lambda label, section: self.field(s, label, section)  # noqa: E731
        debtor = " ".join(x for x in (f("Фамилия", "Сведения о должнике"), f("Имя", "Сведения о должнике"),
                                      f("Отчество", "Сведения о должнике")) if x) \
            or f("Полное наименование", "Сведения о должнике") or f("Наименование", "Сведения о должнике")
        return {
            "organizer_name": f("Полное наименование", "Организатор торгов") or f("Сокращенное", "Организатор торгов"),
            "organizer_phone": phone_digits(f("Телефон", "Контактное лицо")),
            "organizer_email": f("E-mail", "Контактное лицо"),
            "manager_name": f("ФИО", "Арбитражный управляющий"),
            "manager_sro": f("Наименование организации", "Арбитражный управляющий"),
            "debtor_name": debtor or None,
            "debtor_inn": f("ИНН", "Сведения о должнике"),
        }


# --- МЭТС (m-ets.ru) ---

class Mets:
    """Список лотов - /search?q=<фильтры JSON-ом в base64> (категория «Легковой автомобиль»,
    регионы, «идёт приём заявок»; 20 лотов на страницу), лот - /<номер торгов>-<номер лота>:
    на одной странице всё - статус, цены, график снижения, сроки, характеристики машины (марка,
    модель, двигатель, мощность, пробег, привод, коробка, VIN), должник, управляющий, номер
    ЕФРСБ, организатор, фото (с водяным знаком самой МЭТС). Пускает только российские адреса:
    с ВМ открывается, с ПК под VPN - 403 (проверено 16.10.2026)."""

    host = "m-ets.ru"
    platform = "Межрегиональная электронная торговая система"
    base = "https://m-ets.ru"
    cars_only = True  # список уже отфильтрован категорией площадки, is_vehicle по названию не нужен
    max_pages = 40    # защита от бесконечного цикла (16.10.2026 - 16 страниц)

    def list_url(self, page):
        import base64
        query = {"search_category": "1", "stat[]": ["1"], "xregion[]": sorted(str(r) for r in REGIONS)}
        q = base64.b64encode(json.dumps(query, separators=(",", ":")).encode()).decode().rstrip("=")
        return f"{self.base}/search?q={q}" + (f"&page={page}" if page > 1 else "")

    def list_lots(self, get, regions=REGIONS, sleep=None):
        """-> [stub]: url, key, lot_number, trade_number, title, price_start, region, list_status."""
        out = {}
        for page in range(1, self.max_pages + 1):
            html = get(self.list_url(page))
            rows = self.parse_list(html)
            for stub in rows:
                out.setdefault(stub["key"], stub)
            if sleep:
                sleep()
            last = re.search(r'class="end link"[^>]*>(\d+)<', html or "")
            if not rows or page >= (int(last.group(1)) if last else page):
                break
        return list(out.values())

    def parse_list(self, html):
        stubs = []
        for card in re.split(r'<div[^>]*class="card-so"', html or "")[1:]:
            link = re.search(r'href="(\d+)-(\d+)"', card)
            if not link:
                continue
            title = re.search(r'<div class="title">(.*?)</div>', card, re.S)
            place = re.search(r'search-item-location">\s*<span>(.*?)</span>', card, re.S)
            cost = re.search(r'<div class="cost[^"]*"[^>]*>(.*?)</div>', card, re.S)
            url = f"{self.base}/{link.group(1)}-{link.group(2)}"
            stubs.append({
                "url": url, "key": listing_key(url), "trade_number": link.group(1), "lot_number": link.group(2),
                "title": text_of(title.group(1)) if title else "", "price_start": money(text_of(cost.group(1)))
                if cost else None, "region": text_of(place.group(1)) if place else None, "list_status": "приём заявок",
            })
        return stubs

    @staticmethod
    def sections(html):
        """Поля страницы лота: {(раздел, подпись): значение}. Раздел - строка-заголовок
        (lot-info-item title: «Сведения о должнике», «Финансовый управляющий», «Организатор торгов»…)."""
        out = {}
        section = ""
        item = re.compile(r'<div class="lot-info-item( title)?[^"]*">\s*<div class="title">(.*?)</div>\s*'
                          r'(?:<div class="value">(.*?)</div>)?', re.S)
        for m in item.finditer(html or ""):
            label = text_of(m.group(2)).rstrip(":").strip()
            if m.group(1):
                section = label
                continue
            out.setdefault((section, label), text_of(m.group(3) or ""))
        return out

    @staticmethod
    def field(sections, label, section=None):
        """Значение по подписи (подпись содержит label; раздел - начинается с section)."""
        label = label.lower()
        for (sec, lab), value in sections.items():
            if label in lab.lower() and (section is None or section.lower() in sec.lower()):
                return value
        return None

    def parse_periods(self, html):
        """График снижения цены -> [{begin, end, bid_end, price}] и цена текущего периода
        (строка data-status='1')."""
        m = re.search(r"График снижения цены.*?<tbody>(.*?)</tbody>", html or "", re.S)
        periods, current = [], None
        for tr in re.findall(r"<tr[^>]*>.*?</tr>", m.group(1) if m else "", re.S):
            cells = [text_of(c) for c in re.findall(r"<td.*?</td>", tr, re.S)]
            if len(cells) < 4:
                continue
            begin, end, price = ru_datetime(cells[1]), ru_datetime(cells[2]), money(cells[3])
            if end and price:
                periods.append({"begin": begin, "end": end, "bid_end": end, "price": price})
                if "data-status='1'" in tr or 'data-status="1"' in tr:
                    current = price
        periods.sort(key=lambda p: p["bid_end"])
        return periods, current

    def read_lot(self, get, url, with_trade=True):
        """Страница лота -> поля строки листа и данные для мини-аппа (with_trade не нужен: всё на
        одной странице). Нет названия или статуса - parse_error."""
        html = get(url)
        number = re.search(r"/(\d+)-(\d+)$", url.rstrip("/"))
        s = self.sections(html)
        f = lambda label, section=None: self.field(s, label, section)  # noqa: E731
        head = re.search(r'<h2 class="lot-title[^"]*"[^>]*>(.*?)(?:<span ellipse|</h2>)', html or "", re.S)
        title = text_of(head.group(1)) if head else None
        raw = re.search(r'class="value lot-status-name"[^>]*>([^<]*)<', html or "")
        raw_status = raw.group(1).strip() if raw else ""
        status, state = aggregator_status(raw_status)
        if not title or not status:
            return {"url": url, "lot_id": None, "title": title,
                    "parse_error": f"на странице лота нет названия или статуса ({raw_status or 'пусто'})"}
        periods, current = self.parse_periods(html)
        packed = bidding_schedule.pack_periods(periods)
        price_start = money((f("Начальная цена продажи") or "").split("руб")[0])
        # описание имущества - в <span itemprop="description"> (в подписи поля - латинская «C» и значок
        # «Проверено модератором», общим разбором полей его не взять)
        desc = re.search(r'itemprop="description">(.*?)</div>', html or "", re.S)
        description = (text_of(desc.group(1)) if desc else "") or title
        vin = (f("Идентификационный номер (VIN)") or "").strip().upper()
        vin = vin if len(vin) == 17 else (lot_metrics.find_vin(title) or lot_metrics.find_vin(description))
        mileage = money(f("Пробег"))
        photos = [{"full": self.base + "/" + full, "thumb": self.base + "/" + thumb} for full, thumb in dict.fromkeys(
            re.findall(r'href="(download/[^"]+)"[^>]*data-lightbox="lotpics\d+"[^>]*data-thumb="([^"]+)"', html))]
        applications_end = ru_datetime(f("Окончание предоставления заявок"))
        count = re.search(r"Количество заявок:\s*(\d+)", html)
        region = f("Регион местонахождения имущества")
        if region and region.replace(" ", "").lower() in ("г.москва", "москва"):
            region = REGIONS[77]
        manager_section = next((sec for sec, _ in s if "управляющ" in sec.lower()), "управляющ")
        phone = f("Телефон", "Организатор торгов") or f("Номер контактного телефона")
        return {
            "url": url,
            "lot_id": lot_id_for(self.host, int(number.group(1)) * 100 + int(number.group(2))
                                 if number and int(number.group(2)) < 100 else None),
            "title": title,
            "status": status,
            "etp_state": state,
            "etp_status": raw_status,
            "vin": vin or None,
            "vins_all": lot_metrics.lot_vins((title + " " + description).upper()),
            "plate": lot_metrics.find_plate(title) or lot_metrics.find_plate(description),
            "mileage_km": mileage or _mileage(description) or _mileage(title),
            "photo_url": photos[0]["full"] if photos else None,
            "photos": photos,
            "region": region,
            "price_start": price_start,
            "price_current": current or price_start,
            "currency": "RUB",
            "trade_kind": f("Форма проведения торгов"),
            "trade_section": f("Вид торгов"),
            "platform": self.platform,
            "etp_url": url,
            "applications_start": ru_datetime(f("Начало предоставления заявок")),
            "applications_end": bidding_schedule.final_deadline(applications_end, packed) or applications_end,
            "bidding_periods": packed,
            "periods": periods,
            "bidding_start": ru_datetime(f("Начало подачи предложений о цене")),
            "description": description,
            "efrsb_number": f("Идентификационный номер торгов на ЕФРСБ"),
            "trade_number": number.group(1) if number else None,
            "lot_number": number.group(2) if number else None,
            "applications_count": int(count.group(1)) if count else None,
            # характеристики машины прямо со страницы (у ТоргГрупп их нет)
            "specs": {k: f(label) for k, label in (("brand", "Марка"), ("model", "Модель"), ("engine", "Двигатель"),
                                                     ("year", "Год выпуска"), ("power", "Мощность"),
                                                     ("drive", "Привод"), ("transmission", "Коробка передач"))},
            "organizer_name": f("Наименование", "Организатор торгов"),
            "organizer_phone": phone_digits(phone),
            "organizer_email": f("Адрес электронной почты", "Организатор торгов") or f("Адрес электронной почты"),
            "manager_name": f("ФИО", manager_section),
            "manager_sro": f("саморегулируемой", manager_section),
            "debtor_name": f("ФИО", "Сведения о должнике") or f("Наименование", "Сведения о должнике"),
            "debtor_inn": f("ИНН", "Сведения о должнике"),
        }


_MILEAGE_RE = re.compile(r"пробег[а-я]*[:\s-]*([\d\s]{3,10})\s*км", re.I)


def _mileage(text):
    m = _MILEAGE_RE.search(text or "")
    digits = re.sub(r"\D", "", m.group(1)) if m else ""
    return int(digits) if digits else None


COLLECTORS = [TorgGroup(), Mets()]


def collector_for(url):
    host = etp_status.host(url)
    return next((c for c in COLLECTORS if c.host == host), None)


# Поля строки листа lots, которые ПК пишет из лота с площадки (main.pull_etp_lots).
SHEET_FIELDS = ("lot_id", "url", "title", "status", "vin", "plate", "mileage_km", "price_start", "price_current",
                "currency", "region", "trade_kind", "platform", "applications_start", "applications_end",
                "bidding_start", "organizer_name", "organizer_phone", "organizer_email", "manager_name",
                "manager_sro", "debtor_name", "description", "photo_url", "bidding_periods", "etp_url", "etp_status")


def cache_entry(lot, fetched_at):
    """Лот с площадки -> запись кэша карточек мини-аппа (export_to_miniapp.DETAILS_CACHE_FILE):
    то, что для лотов агрегатора скачивается с его карточки."""
    return {
        "photos": lot.get("photos") or [],
        "periods": lot.get("periods") or [],
        "trade_form": lot.get("trade_kind"),
        "is_public_offer": bidding_schedule.is_public_offer(lot.get("trade_kind")),
        "status": lot.get("status"),
        "platform": lot.get("platform"),
        "description": lot.get("description"),
        "applications_end": lot.get("applications_end"),
        "etp_url": lot.get("etp_url"),
        "fetched_at": fetched_at,
        "source": "etp",
    }


# --- повторы: тот же лот у агрегатора или уже в листе ---

def _norm_title(title):
    return re.sub(r"[^0-9a-zа-я]", "", (title or "").lower().replace("ё", "е"))[:80]


class Dedup:
    """Узнаёт лот, который уже есть в листе: тот же адрес лота на ЭТП, иначе тот же VIN у
    открытого лота (одна машина одновременно только в одних торгах), иначе то же название
    и начальная цена у открытого лота - если VIN нет хотя бы у одного из двух лотов: разные
    VIN - разные машины, даже с одинаковым названием и ценой. rows - строки листа lots (dict), extra_urls -
    {lot_id: адрес на ЭТП} из кэша карточек (у старых строк листа etp_url пуст)."""

    def __init__(self, rows, now=None, extra_urls=None):
        self.now = now or datetime.datetime.now()
        self.keys, self.vins, self.titles = {}, {}, {}
        for r in rows:
            self.add(r, (extra_urls or {}).get(str(r.get("lot_id"))))

    def _open(self, row):
        if bidding_schedule.is_closed_status(row.get("status")):
            return False
        end = row.get("applications_end")
        try:
            return datetime.datetime.strptime(str(end)[:19], DATE_FORMAT) > self.now
        except ValueError:
            return True  # дедлайн неизвестен - считаем открытым

    def add(self, row, extra_url=None):
        lot_id = str(row.get("lot_id") or "")
        for url in (row.get("etp_url"), row.get("url"), extra_url):
            key = listing_key(url)
            if key:
                self.keys.setdefault(key, lot_id)
        if self._open(row):
            vin = (row.get("vin") or "").strip().upper()
            if len(vin) == 17:
                self.vins.setdefault(vin, lot_id)
            title = _norm_title(row.get("title"))
            if title and row.get("price_start"):
                key = (title, str(money(str(row.get("price_start")))))
                self.titles.setdefault(key, []).append((lot_id, vin if len(vin) == 17 else None))

    def find(self, lot):
        """-> (lot_id, почему) уже известного лота или (None, None)."""
        for url in (lot.get("etp_url"), lot.get("url")):
            key = listing_key(url)
            if key and key in self.keys:
                return self.keys[key], "тот же лот на ЭТП"
        vin = (lot.get("vin") or "").strip().upper()
        if len(vin) == 17 and vin in self.vins:
            return self.vins[vin], "тот же VIN у открытого лота"
        title = _norm_title(lot.get("title"))
        if title and lot.get("price_start"):
            for found, other_vin in self.titles.get((title, str(money(str(lot.get("price_start"))))), []):
                if len(vin) != 17 or not other_vin:  # у обоих VIN есть и разные - разные машины
                    return found, "то же название и цена"
        return None, None


def dumps(lot):
    return json.dumps(lot, ensure_ascii=False, separators=(",", ":"))
