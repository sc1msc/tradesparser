# -*- coding: utf-8 -*-
r"""
Публичные страницы сайта honestlot.ru для приёма оплаты: что продаём и за сколько
(/pro), оферта (/offer), политика обработки персональных данных (/privacy),
реквизиты (/requisites), robots.txt.

ЗАЧЕМ. ЮKassa подключает магазин, только если на сайте видны настоящие услуги с
фиксированными ценами, как покупатель получает услугу, оферта, контакты и ИНН
самозанятого. Корень сайта - мини-апп (его открывает Telegram), поэтому эти
страницы отдельные и не трогают мини-апп. Они открыты всегда, независимо от
HONESTLOT_PAYMENTS_ENABLED: ЮKassa проверяет сайт до включения оплаты.

РЕКВИЗИТЫ НЕ В GIT. Репозиторий публичный, поэтому ФИО и ИНН продавца берутся из
miniapp/.env на сервере (HONESTLOT_SELLER_NAME, HONESTLOT_SELLER_INN; вписать:
bash miniapp/set_env.sh "HONESTLOT_SELLER_NAME=Фамилия Имя Отчество" HONESTLOT_SELLER_INN=...).
Без них на страницах стоит "не указано" - заполнить до отправки сайта в ЮKassa.

НЕ ИНДЕКСИРОВАТЬ РЕКВИЗИТЫ (решение владельца): /requisites отдаётся с заголовком
X-Robots-Tag и метатегом robots "noindex", ссылки на неё - rel="nofollow". В
robots.txt её НЕ закрываем: поисковик, которому запрещено заходить на страницу, не
увидит "noindex" и может проиндексировать адрес по внешним ссылкам. ФИО и ИНН есть
только на этой странице; ссылки на неё - только из оферты и политики (не в подвале).

ЦЕНЫ - из billing.PLANS (одно место для цен: страница оплаты, письма, этот сайт):
{{PLANS}} - карточки тарифов, {{HERO_CTA}} - кнопки первого экрана /pro.
Шаблоны - app/site_pages/*.html: общий layout.html и содержимое страниц. Подстановки
{{ИМЯ}}; всё, что приходит из настроек, экранируется.
"""
import html
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import billing

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_pages")
SUPPORT_BOT = "honestlot_support_bot"
APP_BOT = "honestlot_bot"

# адрес -> (файл, заголовок вкладки, не индексировать)
PAGES = {
    "pro": ("pro.html", "HonestLot Pro — подписка", False),
    "offer": ("offer.html", "Оферта — HonestLot", False),
    "privacy": ("privacy.html", "Политика обработки персональных данных — HonestLot", False),
    "requisites": ("requisites.html", "Реквизиты — HonestLot", True),
}
NOINDEX = "noindex, nofollow, noarchive"

router = APIRouter()


def _read(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return f.read()


def _rub(n):
    return f"{n:,}".replace(",", " ") + " ₽"


MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]


def _date_text(d):
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year} года"


def _plans():
    """Карточки тарифов из billing.PLANS: пока ранняя цена доступна (billing.early_open) - она крупно, обычная
    зачёркнута; цена за месяц; самый длинный срок отмечен как самый выгодный."""
    longest = max(p["months"] for p in billing.PLANS.values())
    early = billing.early_open()
    cards = []
    for pid, p in billing.PLANS.items():
        best = p["months"] == longest
        price = p["early"] if early else p["price"]
        per_month = (f'<div class="per">≈&nbsp;{_rub(round(price / p["months"]))} в&nbsp;месяц</div>'
                     if p["months"] > 1 else '<div class="per">помесячно</div>')
        cards.append(
            f'<div class="plan{" best" if best else ""}">'
            + ('<div class="badge">Выгоднее всего</div>' if best else "")
            + f'<div class="term">{html.escape(p["title"])}</div>'
            f'<div class="price">{_rub(price)}</div>'
            + (f'<div class="regular">обычная цена <s>{_rub(p["price"])}</s></div>' if early else "")
            + f'{per_month}{_pay_link("btn small" + ("" if best else " ghost"))}</div>')
    return f'<div class="plans">{"".join(cards)}</div>'


def _early_note():
    """Строка над тарифами /pro: срок ранней цены, пока она доступна."""
    if not billing.early_open():
        return ""
    return (f'<p class="sub">Ранняя цена — при оформлении подписки до {_date_text(billing.EARLY_UNTIL)} включительно. '
            'Она сохраняется при продлении, пока подписка не прерывалась.</p>')


def _pay_link(cls):
    """Кнопка оформления - только когда оплата включена (иначе /pay/ отвечает 404)."""
    return f'<a class="{cls}" href="/pay/">Оформить</a>' if billing.enabled() else ""


def _hero_cta():
    if billing.enabled():
        return ('<a class="btn" href="/pay/">Оформить подписку</a>'
                '<a class="btn ghost" href="/">Открыть HonestLot</a>')
    # "/" - веб-версия на этом же сайте (вход через Telegram), не переход в бота: ЮKassa
    # требует, чтобы сайт с оплатой не уводил в Telegram
    return ('<a class="btn" href="/">Открыть HonestLot</a>'
            '<span class="note">Оформление подписки откроется в ближайшее время.</span>')


def values():
    """Подстановки шаблонов. Только текст из настроек - экранируется в render."""
    return {
        "SELLER_NAME": os.environ.get("HONESTLOT_SELLER_NAME", "").strip() or "не указано",
        "SELLER_INN": os.environ.get("HONESTLOT_SELLER_INN", "").strip() or "не указано",
        "EMAIL": os.environ.get("HONESTLOT_CONTACT_EMAIL", "").strip() or "info@honestlot.ru",
        "SITE": billing.site_url(),
        "EARLY_UNTIL": _date_text(billing.EARLY_UNTIL),
        "REMIND_DAYS": str(billing.REMIND_DAYS),
        "RENEW_ATTEMPTS": str(billing.RENEW_ATTEMPTS),
        "SUPPORT_BOT": SUPPORT_BOT,
        "APP_BOT": APP_BOT,
    }


def message_page(title, text, form_button=None):
    """Короткая страница-ответ без индексации: почта подтверждена, письма отключены (notify.py).
    form_button - кнопка, которая отправляет эту же страницу POST-запросом (отписка: по GET ничего не
    меняем - почтовые сканеры сами открывают ссылки из писем)."""
    action = (f'<form method="post"><button class="btn" type="submit">{html.escape(form_button)}</button></form>'
              if form_button else '<p><a class="btn" href="/">Открыть HonestLot</a></p>')
    content = f'<h1>{html.escape(title)}</h1><div class="card"><p>{html.escape(text)}</p>{action}</div>'
    out = _read("layout.html").replace("{{CONTENT}}", content)
    out = out.replace("{{ROBOTS}}", f'<meta name="robots" content="{NOINDEX}">')
    out = out.replace("{{TITLE}}", html.escape(f"{title} — HonestLot")).replace("{{PAGE}}", "message")
    for key, value in values().items():
        out = out.replace("{{" + key + "}}", html.escape(value))
    return out


def render(page):
    name, title, noindex = PAGES[page]
    out = _read("layout.html").replace("{{CONTENT}}", _read(name))
    # готовый HTML, собранный здесь же (не из настроек)
    out = out.replace("{{PLANS}}", _plans()).replace("{{HERO_CTA}}", _hero_cta())
    out = out.replace("{{EARLY_NOTE}}", _early_note())
    out = out.replace("{{ROBOTS}}", f'<meta name="robots" content="{NOINDEX}">' if noindex else "")
    out = out.replace("{{TITLE}}", html.escape(title)).replace("{{PAGE}}", page)
    # значения из настроек - последними и с экранированием (во всей странице, и в подвале)
    for key, value in values().items():
        out = out.replace("{{" + key + "}}", html.escape(value))
    return out


@router.api_route("/robots.txt", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def robots():
    # /requisites здесь нарочно не закрыт - см. докстринг
    return "User-agent: *\nDisallow: /api/\nDisallow: /pay/\n"


def _page_route(page):
    def handler():
        headers = {"Cache-Control": "no-cache"}
        if PAGES[page][2]:
            headers["X-Robots-Tag"] = NOINDEX
        return HTMLResponse(render(page), headers=headers)
    return handler


# Явные адреса, а не "/{page}": такой маршрут перехватил бы статику мини-аппа
# (/app.js, /style.css), которую отдаёт StaticFiles в конце main.py.
for _page in PAGES:
    # HEAD - так доступность сайта проверяют роботы (в том числе при модерации магазина)
    router.add_api_route(f"/{_page}", _page_route(_page), methods=["GET", "HEAD"], response_class=HTMLResponse)
