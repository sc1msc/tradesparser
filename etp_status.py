# -*- coding: utf-8 -*-
r"""
Статус торгов прямо на электронной торговой площадке (ЭТП).

Зачем. Статус лота мы берём у агрегатора, а он отстаёт: публичное
предложение на ЦДТ уже завершено и опубликован протокол, аукцион на МЭТС
«не состоялся», а агрегатор всё ещё пишет «Идёт приём заявок» (лоты 7190620,
7183843, 15.10.2026). Публичные предложения заканчиваются досрочно - как
только кто-то подал заявку, - так что лента показывала уже проданные машины.
Сервер мини-аппа (miniapp/backend/app/status_refresh.py) несколько раз в
день перечитывает карточки агрегатора и страницы ЭТП; статус площадки
важнее статуса агрегатора.

Что здесь:
  etp_link(lot)        - ссылка на лот на ЭТП из JSON карточки агрегатора
                         (source_links «Лот на ЭТП» / «Торги на ЭТП»).
  engine(url)          - каким разбором читать страницу (по адресу), None -
                         площадка, которую разбирать не умеем.
  parse(url, html, hint) -> Result(state, text, outcome)
      state:   open    - идёт приём заявок;
               pending - приём заявок окончен, итог ещё не подведён
                         (определение участников, подведение итогов): лот
                         уже не купить, но торги могут продолжиться;
               closed  - итог есть: outcome done (завершены), failed (не
                         состоялись), cancelled (отменены), suspended
                         (приостановлены);
               unknown - статус на странице не нашёлся.
      hint - VIN/госномер лота: на странице бывает несколько лотов одних
      торгов со своими статусами (НИС, Фабрикант), нужный - ближайший к VIN.

Разборы - по движкам, а не по сайтам: один движок стоит на нескольких
площадках («Статус: ...» у ТоргГрупп, ЭТПУ, АРБбитЛота, Центра реализации;
«Статус торгов ...» у НИС, Систематорга, «России онлайн», Промконсалта), и
новая площадка на знакомом движке узнаётся по виду ссылки. Площадки, где
статус рисует скрипт в браузере (Аукционы Сибири, Аукцион-центр, Альфалот),
пока не разбираем: для них остаётся статус агрегатора, а сервер раз в сутки
присылает список таких площадок с числом лотов.

Модуль общий для ПК (export_to_miniapp.py) и сервера: Docker-образ копирует
его, как lot_metrics.py. Без зависимостей.
"""
import html as html_lib
import re
from collections import namedtuple
from urllib.parse import unquote, urlsplit

Result = namedtuple("Result", "state text outcome")
UNKNOWN = Result("unknown", None, None)

AGGREGATOR_HOST = "xn----etbpba5admdlad.xn--p1ai"

# Подпись итога для листа и мини-аппа - как пишет агрегатор, чтобы работали
# bidding_schedule.is_closed_status и lots.OUTCOMES.
OUTCOME_TEXT = {"done": "Торги завершены", "failed": "Торги не состоялись",
                "cancelled": "Торги отменены", "suspended": "Торги приостановлены"}

# Фраза статуса -> (state, outcome). Порядок важен: "прием заявок окончен"
# раньше "прием заявок", "не состоял" раньше "заверш".
PHRASES = (
    ("не состоял", "closed", "failed"), ("несостоявш", "closed", "failed"),
    ("процедура по лоту проведена", "closed", "done"),  # Lot-online (РАД): торги прошли (19.10.2026)
    ("отмен", "closed", "cancelled"), ("аннулир", "closed", "cancelled"),
    ("приостановл", "closed", "suspended"),
    ("прием заявок окончен", "pending", None), ("прием заявок завершен", "pending", None),
    ("завершен прием", "pending", None), ("окончен прием", "pending", None), ("закончен прием", "pending", None),
    ("прием заявок закончен", "pending", None), ("определение участников", "pending", None),
    ("подведение итогов", "pending", None), ("рассмотрение заявок", "pending", None),
    ("идут торги", "pending", None), ("торги идут", "pending", None), ("проведение торгов", "pending", None),
    ("заверш", "closed", "done"), ("закончен", "closed", "done"), ("окончен", "closed", "done"),
    ("прием заявок", "open", None), ("прием предложений", "open", None), ("объявлен", "open", None),
    ("извещение опубликовано", "open", None),  # Центр реализации: торги объявлены, приём ещё не начался
)

# Движки, у которых статус - подпись «Статус...» в тексте страницы.
LABEL_HOSTS = {
    "bankrot.torggroup.org", "au-pro.ru", "bankrupt.etpu.ru", "bankrupt.tender.one", "torgi.arbbitlot.ru",
    "torgibankrot.ru", "bankrupt.centerr.ru", "bankrotstvo.electro-torgi.ru", "uralbidin.ru",
    "nistp.ru", "rus-on.ru", "sistematorg.com", "promkonsalt.ru",
    "etp-profit.ru",  # новый сайт Профита (с осени 2026) - «Статус торгов ...», как у ELECTRO-TORGI
}
# Те же движки на новых площадках - по виду ссылки.
LABEL_URL_RE = re.compile(
    r"/TradeLot/View/|/public/(auctions|public-offers)/lots/view/|trade_view\.php|/(otpp|oaof|oapp)/\d+/lots/", re.I)
# Статус - фраза рядом с VIN лота (своей подписи нет): РАД, Фабрикант.
NEAR_VIN_HOSTS = {"www.fabrikant.ru", "fabrikant.ru"}

LABEL_RE = re.compile(r"Статус(?:\s+торгов)?(?:\s+по\s+лоту)?(?:\s+лота)?\s*:?\s*(.{1,50})", re.I)
# Где кончается значение статуса: дальше на странице идёт следующая подпись.
NEXT_LABEL_RE = re.compile(r"\s(?:Дата|Начало|Окончание|Категория|Информация|Интервалы|Тип|Лот(?=\s)|Протокол|"
                           r"Периоды|Предмет|Аукцион|Регион|Начальная|Текущая|Купить|Документы|Сведения)")
CDT_RE = re.compile(r'"tradeStatusDescription"\s*:\s*"([^"]{1,80})"')
METS_RE = re.compile(r'class="[^"]*lot-status-name[^"]*"[^>]*>\s*([^<]{1,80})<')
# Lot-online (РАД): статус лота - в блоке formMain:opStatus (<span class="status-N">Идет прием заявок</span>).
# До 19.10.2026 его искали рядом с VIN (near_vin), но после длинного описания фраза уходила дальше 400
# символов, а «Процедура по лоту проведена» (торги прошли) словарь не знал - 7 из 14 лотов не распознавались.
LOTONLINE_RE = re.compile(r'id="formMain:opStatus".*?<span class="status-\d+">(?:\s*<span></span>)?\s*([^<]{1,80}?)\s*</span>',
                          re.S)


def host(url):
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def etp_link(lot):
    """Ссылка на лот на самой ЭТП из JSON карточки агрегатора: «Лот на ЭТП» (с
    якорем лота), иначе «Торги на ЭТП», иначе trade_link. ЕФРСБ и сам агрегатор -
    не ЭТП. Нет ссылки (торги «вне ЭТП») - None."""
    links = {(x.get("title") or "").strip().lower(): x.get("link") for x in lot.get("source_links") or []}
    for url in (links.get("лот на этп"), links.get("торги на этп"), lot.get("trade_link")):
        if url and url.startswith("http") and "fedresurs" not in url and AGGREGATOR_HOST not in url:
            return normalize_etp_url(url)
    return None


# Профит перешёл на новый сайт: старые ссылки агрегатора - поиск /etp/trade/list.html?number=<N>–<вид>
# (вид в cp1251: ОАОФ, ОТПП...) - отвечают 301 на главную (тестировщик, 16.10.2026, 33 лота). Страница
# торгов на новом сайте - /<вид латиницей>/<N> (/oaof/22425, /otpp/22251).
_PROFIT_SEARCH_RE = re.compile(r"https?://(?:www\.)?etp-profit\.ru/etp/trade/list\.html\?number=(\d+)(%96|%E2%80%93|-|–)([^&]+)", re.I)
_RU_LAT = str.maketrans("ОАФТПЗКРСЕ", "oaftpzkrse")


def normalize_etp_url(url):
    """Ссылка на ЭТП, которая устарела, -> рабочая (сейчас - старый поиск Профита). Остальные - как есть."""
    m = _PROFIT_SEARCH_RE.match(url or "")
    if not m:
        return url
    kind = unquote(m.group(3), encoding="cp1251").strip().upper().translate(_RU_LAT)
    if not re.fullmatch(r"[a-z]{3,5}", kind):
        return url
    return f"https://etp-profit.ru/{kind}/{m.group(1)}"


# ЕФРСБ: агрегатор даёт старый адрес сообщения (old.bankrot.fedresurs.ru/MessageWindow.aspx?ID=<32 hex>), а
# он не пускает зарубежные адреса (у пользователя с VPN - 403). Новый сайт открывается везде (17.10.2026):
# fedresurs.ru/bankruptmessages/<тот же ID с дефисами>.
_EFRSB_MESSAGE_RE = re.compile(r"MessageWindow\.aspx\?ID=([0-9A-Fa-f]{32})")


def efrsb_link(lot):
    """Объявление о торгах на ЕФРСБ из JSON карточки агрегатора (новый адрес Федресурса) или None. Для
    лотов без ЭТП («Торги, проводимые вне ЭТП») кнопка мини-аппа ведёт сюда, а не на агрегатор."""
    links = {(x.get("title") or "").strip().lower(): x.get("link") for x in lot.get("source_links") or []}
    m = _EFRSB_MESSAGE_RE.search(links.get("объявление на ефрсб") or "")
    if not m:
        return None
    h = m.group(1).lower()
    return f"https://fedresurs.ru/bankruptmessages/{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def engine(url):
    h = host(url)
    if h == "torgi.cdtrf.ru":
        return "cdt"
    if h == "m-ets.ru":
        return "mets"
    if h == "sales.lot-online.ru":
        return "lotonline"
    if h in NEAR_VIN_HOSTS:
        return "near_vin"
    if h in LABEL_HOSTS or LABEL_URL_RE.search(url or ""):
        return "label"
    return None


def _norm(text):
    """Нижний регистр, ё -> е, «приема» -> «прием»: «Торги в стадии приема заявок» (МЭТС),
    «Этап приема заявок» (Фабрикант) - тот же «прием заявок»."""
    return (text or "").lower().replace("ё", "е").replace("приема", "прием")


def classify(fragment):
    """Текст статуса -> (state, outcome) или None, если не распознан."""
    t = _norm(fragment)
    for phrase, state, outcome in PHRASES:
        if phrase in t:
            return state, outcome
    return None


def page_text(html):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S | re.I)
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _anchors(text, hint):
    """Позиции VIN/госномера лота в тексте страницы (для выбора лота на многолотовой странице)."""
    out = []
    for key in (hint or {}).get("vin"), (hint or {}).get("plate"):
        key = (key or "").strip().upper()
        if len(key) >= 6:
            out += [m.start() for m in re.finditer(re.escape(key), text.upper())]
    return out


def _pick(found, anchors):
    """found - [(позиция, фрагмент, (state, outcome))]. Все одинаковые - берём; разные - ближайший
    к VIN; VIN не нашёлся - неизвестно (лучше промолчать, чем закрыть чужой лот)."""
    if not found:
        return None
    if len({f[2] for f in found}) == 1:
        return found[0]
    if not anchors:
        return None
    return min(found, key=lambda f: min(abs(f[0] - a) for a in anchors))


def parse(url, html, hint=None):
    kind = engine(url)
    if not kind or not html:
        return UNKNOWN
    found = []
    if kind == "cdt":
        raw = html_lib.unescape(html)
        found = [(m.start(), m.group(1), classify(m.group(1))) for m in CDT_RE.finditer(raw)]
        text = page_text(html)
    elif kind == "mets":
        found = [(m.start(), m.group(1), classify(m.group(1))) for m in METS_RE.finditer(html)]
        text = page_text(html)
    elif kind == "lotonline":
        found = [(m.start(), m.group(1), classify(m.group(1))) for m in LOTONLINE_RE.finditer(html)]
        text = page_text(html)
    else:
        text = page_text(html)
        if kind == "label":
            for m in LABEL_RE.finditer(text):
                value = NEXT_LABEL_RE.split(m.group(1), maxsplit=1)[0]
                found.append((m.start(), value, classify(value)))
        else:  # near_vin: фразы статуса в 400 символах после VIN
            for a in _anchors(text, hint):
                window = text[a: a + 400]
                for phrase in ("идет прием заявок", "прием заявок", "торги завершены", "торги не состоялись",
                               "торги отменены", "приостановлен", "подведение итогов"):
                    i = _norm(window).find(phrase)
                    if i >= 0:
                        found.append((a + i, window[i: i + 40], classify(phrase)))
                        break
    found = [f for f in found if f[2]]
    anchors = _anchors(text, hint) if kind != "near_vin" else [f[0] for f in found]
    best = _pick(found, anchors)
    if not best:
        return UNKNOWN
    state, outcome = best[2]
    return Result(state, " ".join(best[1].split())[:60], outcome)
