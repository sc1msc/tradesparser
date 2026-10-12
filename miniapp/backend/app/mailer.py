# -*- coding: utf-8 -*-
r"""
Письма подписчикам (billing.py): оплата прошла, напоминание о списании,
списание не прошло, автопродление выключено, подписка закончилась.

Почему e-mail, а не бот: бота могут заархивировать или заблокировать -
уведомление не дойдёт, а деньги спишутся (wiki/monetization.md). Пользователям
эту причину не пишем.

SMTP из переменных окружения (miniapp/.env):
  HONESTLOT_SMTP_HOST, HONESTLOT_SMTP_PORT (465 - SSL, 587 - STARTTLS),
  HONESTLOT_SMTP_USER, HONESTLOT_SMTP_PASSWORD, HONESTLOT_SMTP_FROM,
  HONESTLOT_SMTP_REPLY_TO (необязательно: куда пойдут ответы, если не на FROM).
Без HONESTLOT_SMTP_HOST письма не уходят, а печатаются в лог (локальный
запуск, проверка) - send() возвращает False.

Шлём через Yandex Cloud Postbox (wiki/payments.md, раздел "Почта"): своего
почтового сервера нет - с ВМ Yandex Cloud закрыт исходящий порт 25, а письма с
нового IP без репутации попадают в спам. У Postbox логин SMTP - id API-ключа
сервисного аккаунта, поэтому отправитель задаётся отдельно (HONESTLOT_SMTP_FROM,
info@honestlot.ru); его домен подписан DKIM в Postbox.

Проверка настроек: python -m app.mailer test <адрес> - отправить тестовое письмо
(в контейнере: docker compose exec api python -m app.mailer test <адрес>).
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


def configured():
    return bool(os.environ.get("HONESTLOT_SMTP_HOST"))


def _log(text):
    # консоль Windows (cp1251) не печатает "₽" - лог не должен падать из-за кодировки
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(enc, "replace").decode(enc), flush=True)


def send(to, subject, text):
    """-> True, если письмо ушло. Никакие ошибки не бросаются: письмо не
    должно ронять оплату или продление (они к этому моменту уже записаны)."""
    if not to:
        return False
    try:
        return _send(to, subject, text)
    except Exception as e:  # noqa: BLE001 - что угодно, кроме падения оплаты
        _log(f"Письмо не отправлено ({to}, {subject}): {e!r}")
        return False


def _send(to, subject, text):
    if not configured():
        _log(f"[письмо не отправлено - SMTP не настроен] кому: {to} | {subject}\n{text}\n")
        return False
    host = os.environ["HONESTLOT_SMTP_HOST"]
    port = int(os.environ.get("HONESTLOT_SMTP_PORT", "465"))
    user = os.environ.get("HONESTLOT_SMTP_USER", "")
    sender = os.environ.get("HONESTLOT_SMTP_FROM") or user
    msg = EmailMessage()
    msg["From"] = formataddr(("HonestLot", sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    # Message-ID на нашем домене: без него часть почтовиков ставит свой или считает письмо спамом
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
    if os.environ.get("HONESTLOT_SMTP_REPLY_TO"):
        msg["Reply-To"] = os.environ["HONESTLOT_SMTP_REPLY_TO"]
    msg.set_content(text)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
                if user:
                    s.login(user, os.environ.get("HONESTLOT_SMTP_PASSWORD", ""))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, os.environ.get("HONESTLOT_SMTP_PASSWORD", ""))
                s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        _log(f"Письмо не отправлено ({to}, {subject}): {e}")
        return False


if __name__ == "__main__":
    # python -m app.mailer test <адрес> - проверить настройки SMTP
    if len(sys.argv) == 3 and sys.argv[1] == "test":
        if not configured():
            sys.exit("HONESTLOT_SMTP_HOST не задан - письма не отправляются")
        ok = send(sys.argv[2], "HonestLot: проверка почты",
                  "Это тестовое письмо HonestLot. Если оно пришло во \"Входящие\", а не в спам, "
                  "почта для писем подписчикам настроена.\n")
        print("Отправлено" if ok else "Не отправлено - ошибка выше")
        sys.exit(0 if ok else 1)
    sys.exit("использование: python -m app.mailer test <адрес>")
