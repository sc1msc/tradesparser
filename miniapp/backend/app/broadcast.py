# -*- coding: utf-8 -*-
r"""
Рассылка всем пользователям мини-аппа через @honestlot_bot (с 29.10.2026): лот-«зацепка» и коротко
о новом в приложении. Запускает владелец руками на ВМ (из ~/honestlot/miniapp):

  docker compose exec api python -m app.broadcast show  broadcasts/<файл>.txt   - что и скольким уйдёт
  docker compose exec api python -m app.broadcast test  broadcasts/<файл>.txt [@ник|id ...] - только себе
  docker compose exec api python -m app.broadcast send  broadcasts/<файл>.txt   - всем (спросит «да»)
  docker compose exec api python -m app.broadcast stats broadcasts/<файл>.txt   - дошло, открыли, подарки

test без адресата шлёт на HONESTLOT_ADMIN_CHAT_ID (вы должны хоть раз написать @honestlot_bot).

КАМПАНИЯ - один текстовый файл. Файлы из miniapp/broadcasts/ попадают в образ (папка broadcasts/ в
контейнере, после выкладки); для правки без выкладки - любой путь в /data (это miniapp/data на ВМ).
Сверху - настройки «ключ: значение», после строки «---» - текст в HTML-разметке Telegram (<b>, <i>,
<a href="...">; знаки < > & в тексте - как &lt; &gt; &amp;):
  lot: 7216904                 - лот-зацепка: первая кнопка открывает его экран в мини-аппе;
  button: Смотреть Rolls-Royce - подпись этой кнопки; вторая кнопка - «Открыть HonestLot» (лента);
  gift_days: 3                 - подарить Pro на N дней тем, у кого Pro нет и кто ещё не получал пробный;
  photo: none | <адрес>        - фото над текстом; по умолчанию первое фото лота, если оно есть
                                 (фото с нашего сервера - /img, /docimg - Telegram может не скачать:
                                 блокировка в обе стороны; тогда сообщение уходит текстом).
{подарок} в тексте - место строки о подарке (её получают только те, кому Pro подарен; у остальных
строка убирается); без метки строка дописывается в конец. Имя кампании - имя файла: по нему помним,
кому уже отправили, поэтому для новой рассылки - новый файл.

ПОЧЕМУ ТАК.
  - Повторов нет (как в notify.py): строка в broadcast_log пишется до отправки, повторный send
    пропускает всех, кто уже есть в журнале. Таймаут ответа - сообщение, возможно, ушло: второй раз не
    шлём. Нет связи с релеем - стоп, запись «stopped»: повторный send продолжит с этого человека.
  - 403 - человек заблокировал бота или ни разу его не запускал (бот не может написать первым): это
    не ошибка, просто «не дошло». Кого notify.py уже знает как заблокировавшего - не пробуем.
  - 429 (лимит Telegram) - ждём сколько сказано и повторяем; между сообщениями SEND_PAUSE_SECONDS.
  - Подарок - через billing.claim_trial (таблица trial_grants: один раз на человека) до отправки
    сообщения: кнопка в нём сразу открывает Pro, а мини-апп при входе один раз покажет «Вам открыт Pro
    на N дней». Решение владельца 29.10.2026: старым бесплатным - 3 дня, иначе «добавили фильтры»
    упирается в окно Pro, где в Telegram только «Понятно».
  - Кнопки - web_app с ?lot=ID&src=broadcast: app.js откроет лот и запишет событие notify_open с
    источником broadcast - stats считает по нему, сколько людей открыли мини-апп из рассылки.
"""
import datetime
import html
import os
import re
import sys
import time

from . import billing, db, lots, notify, telegram

SEND_PAUSE_SECONDS = 0.1    # ~10 сообщений в секунду, лимит Telegram для рассылок - около 30
CAPTION_LIMIT = 1024        # подпись к фото; длиннее - отправляем текстом без фото
MAX_429_RETRIES = 3
FEED_BUTTON = "Открыть HonestLot"
GIFT_MARK = "{подарок}"
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
              "октября", "ноября", "декабря"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS broadcast_log (
    campaign    TEXT NOT NULL,      -- имя файла кампании
    telegram_id INTEGER NOT NULL,
    status      TEXT NOT NULL,      -- sending / sent / unknown (таймаут) / blocked / failed / stopped
    gift_until  TEXT,               -- до какого дня подарен Pro в этой рассылке
    detail      TEXT,               -- ответ Telegram при ошибке
    at          TEXT NOT NULL,
    PRIMARY KEY (campaign, telegram_id)
);
"""

_schema_ready = False


def conn():
    global _schema_ready
    c = notify.conn()  # и notify_settings (кто заблокировал бота) - на случай базы без уведомлений
    if not _schema_ready:
        with db._lock:
            c.executescript(SCHEMA)
            c.commit()
        _schema_ready = True
    return c


def _iso(dt):
    return dt.isoformat(timespec="seconds")


# ---------- кампания ----------

def load(path):
    """Файл кампании -> dict: name, lot_id, button, gift_days, photo, text."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    head, sep, body = raw.partition("\n---\n")
    if not sep:
        raise ValueError(f"{path}: нет строки «---» между настройками и текстом")
    opts = {}
    for line in head.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            opts[key.strip().lower()] = value.strip()
    unknown = set(opts) - {"lot", "button", "gift_days", "photo"}
    if unknown:
        raise ValueError(f"{path}: неизвестные настройки {', '.join(sorted(unknown))}")
    return {
        "name": os.path.splitext(os.path.basename(path))[0],
        "lot_id": opts.get("lot") or None,
        "button": opts.get("button") or "Открыть лот",
        "gift_days": int(opts.get("gift_days") or 0),
        "photo": opts.get("photo") or None,
        "text": body.strip(),
    }


def _date_ru(dt):
    d = dt.astimezone(lots.MSK)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def gift_line(days, until):
    return (f"🎁 Чтобы всё это попробовать, мы открыли вам Pro на {days} "
            f"{notify._plural(days, 'день', 'дня', 'дней')} — до {_date_ru(until)}.")


def render(camp, gift_until=None):
    """Текст сообщения: с строкой о подарке (gift_until - конец подаренного срока) или без неё."""
    text = camp["text"]
    line = gift_line(camp["gift_days"], gift_until) if gift_until else ""
    if GIFT_MARK not in text:
        return text + ("\n\n" + line if line else "")
    text = text.replace(GIFT_MARK, line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plain_len(text):
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


def keyboard(camp):
    rows = []
    if camp["lot_id"]:
        rows.append([{"text": camp["button"], "web_app": {"url": notify.app_link(lot=camp["lot_id"], src="broadcast")}}])
    rows.append([{"text": FEED_BUTTON, "web_app": {"url": notify.app_link(src="broadcast")}}])
    return {"inline_keyboard": rows}


def photo_url(camp):
    """Фото над текстом: photo из файла кампании, иначе первое фото лота. -> адрес или None."""
    if camp["photo"]:
        return None if camp["photo"].lower() == "none" else camp["photo"]
    lot = lots.get(camp["lot_id"]) if camp["lot_id"] else None
    photos = (lot or {}).get("photos") or []
    url = photos[0].get("full") if photos else None
    if url and url.startswith("/"):
        url = billing.site_url() + url  # /img?u=..., /docimg/... - Telegram скачает фото с нашего сервера
    return url


# ---------- кому ----------

def _gets_gift(camp, tid):
    if not camp["gift_days"] or not billing.enabled() or billing.is_pro(tid):
        return False
    return conn().execute("SELECT 1 FROM trial_grants WHERE telegram_id = ?", (tid,)).fetchone() is None


def recipients(camp):
    """[(telegram_id, gift_until из журнала или None)] - кому ещё не отправляли (и на ком остановились)."""
    c = conn()
    billing._conn()  # таблица trial_grants
    rows = c.execute(
        "SELECT u.telegram_id, b.gift_until FROM users u "
        "LEFT JOIN broadcast_log b ON b.campaign = ? AND b.telegram_id = u.telegram_id "
        "WHERE (b.telegram_id IS NULL OR b.status = 'stopped') AND NOT EXISTS (SELECT 1 FROM notify_settings n "
        "WHERE n.telegram_id = u.telegram_id AND n.tg_blocked_at IS NOT NULL) "
        "ORDER BY u.last_seen_at DESC", (camp["name"],)).fetchall()
    return [(r["telegram_id"], r["gift_until"]) for r in rows]


def _log(camp, tid, status, now_iso, gift_until=None, detail=None):
    with db._lock:
        c = conn()
        with c:
            c.execute("INSERT INTO broadcast_log (campaign, telegram_id, status, gift_until, detail, at) "
                      "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(campaign, telegram_id) DO UPDATE SET "
                      "status = excluded.status, gift_until = COALESCE(excluded.gift_until, broadcast_log.gift_until), "
                      "detail = excluded.detail, at = excluded.at",
                      (camp["name"], tid, status, gift_until, detail, now_iso))


# ---------- отправка ----------

def _photo_error(e):
    desc = str(e).lower()
    return e.error_code == 400 and any(w in desc for w in ("http url", "file identifier", "web page content",
                                                          "photo", "image"))


def _message_error(e):
    """Ошибка в самом сообщении (разметка, длина) - у всех будет то же самое, слать дальше нет смысла."""
    desc = str(e).lower()
    return e.error_code == 400 and ("parse entities" in desc or "too long" in desc)


def _blocked(e):
    return e.error_code == 403 or (e.error_code == 400 and "chat not found" in str(e).lower())


class Sender:
    """Отправка одного сообщения кампании с фото (file_id после первой загрузки) или текстом."""

    def __init__(self, camp, call=telegram.call):
        self.camp, self.call = camp, call
        self.keyboard = keyboard(camp)
        self.photo = photo_url(camp)
        self.photo_id = None

    def send(self, chat_id, text):
        if self.photo and _plain_len(text) <= CAPTION_LIMIT:
            try:
                res = self.call("sendPhoto", chat_id=chat_id, photo=self.photo_id or self.photo, caption=text,
                                parse_mode="HTML", reply_markup=self.keyboard)
                if not self.photo_id and res.get("photo"):
                    self.photo_id = res["photo"][-1]["file_id"]  # дальше - без повторной загрузки
                return
            except telegram.TelegramError as e:
                if not _photo_error(e):
                    raise
                print(f"Фото не отправилось ({e}) - дальше без фото: {self.photo}", flush=True)
                self.photo = None
        self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True,
                  reply_markup=self.keyboard)


def _send_retrying(sender, tid, text):
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            return sender.send(tid, text)
        except telegram.TelegramError as e:
            if e.error_code != 429 or attempt == MAX_429_RETRIES:
                raise
            time.sleep((e.retry_after or 5) + 1)


def send_all(camp, call=telegram.call, sleep=time.sleep):
    """Всем, кому ещё не отправляли. -> {статус: число}, причина остановки или None."""
    sender = Sender(camp, call)
    stats, stopped = {}, None
    todo = recipients(camp)
    for i, (tid, gift_until) in enumerate(todo, 1):
        now = lots.now_msk()
        if not gift_until and _gets_gift(camp, tid):
            end = billing.claim_trial(tid, days=camp["gift_days"])
            gift_until = _iso(end) if end else None
        _log(camp, tid, "sending", _iso(now), gift_until)
        until = datetime.datetime.fromisoformat(gift_until) if gift_until else None
        status, detail = "sent", None
        try:
            _send_retrying(sender, tid, render(camp, until))
        except telegram.TelegramError as e:
            detail = str(e)
            if _blocked(e):
                status = "blocked"
            elif e.error_code is None and "timed out" in detail.lower():
                status = "unknown"  # возможно, ушло - второй раз не шлём
            elif e.error_code is None or e.error_code == 429 or _message_error(e):
                status, stopped = "stopped", detail  # нет связи, лимит или ошибка в тексте - повторный send продолжит
            else:
                status = "failed"
        _log(camp, tid, status, _iso(lots.now_msk()), gift_until, detail)
        stats[status] = stats.get(status, 0) + 1
        if stopped:
            break
        if i % 50 == 0:
            print(f"  ... {i} из {len(todo)}: {_fmt(stats)}", flush=True)
        sleep(SEND_PAUSE_SECONDS)
    return stats, stopped


STATUS_RU = {"sent": "доставлено", "blocked": "бот заблокирован или не запущен", "unknown": "таймаут (возможно, дошло)",
             "failed": "ошибка", "stopped": "остановка", "sending": "отправлялось (прервано)"}


def _fmt(stats):
    return ", ".join(f"{STATUS_RU.get(k, k)} {v}" for k, v in sorted(stats.items(), key=lambda kv: -kv[1])) or "ничего"


# ---------- команды ----------

def _lot_summary(camp):
    if not camp["lot_id"]:
        return "без лота"
    lot = lots.get(camp["lot_id"])
    if not lot:
        return f"лот {camp['lot_id']} НЕ НАЙДЕН в базе - кнопка откроет «лот не найден»"
    price = lot.get("price_current")
    line = (f"{lot.get('title')}\n  цена {price:,} ₽".replace(",", " ") if price else f"{lot.get('title')}\n  цена ?") + \
        f", приём заявок до {lot.get('applications_end')}, статус: {lot.get('status')}"
    end = lots.parse_dt(lot.get("applications_end"))
    if end and end < lots.now_msk():
        line += "\n  ВНИМАНИЕ: приём заявок уже закончился"
    return line


def show(camp):
    print(f"Кампания «{camp['name']}»")
    print(f"Лот: {_lot_summary(camp)}")
    for row in keyboard(camp)["inline_keyboard"]:
        print(f"Кнопка «{row[0]['text']}» -> {row[0]['web_app']['url']}")
    photo = photo_url(camp)
    print(f"Фото: {photo or 'нет - сообщение текстом'}")
    sample_until = lots.now_msk() + datetime.timedelta(days=camp["gift_days"]) if camp["gift_days"] else None
    for title, until in (("с подарком", sample_until), ("без подарка", None)) if sample_until else (("", None),):
        text = render(camp, until)
        print(f"\n----- текст{' ' + title if title else ''} ({_plain_len(text)} знаков) -----\n{text}")
        if photo and _plain_len(text) > CAPTION_LIMIT:
            print(f"(длиннее {CAPTION_LIMIT} знаков - уйдёт текстом без фото)")
    todo = recipients(camp)
    gifts = sum(1 for tid, until in todo if until or _gets_gift(camp, tid))
    total = conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"\nПользователей в базе: {total}; отправим: {len(todo)}" +
          (f", из них подарим Pro на {camp['gift_days']} дн.: {gifts}" if camp["gift_days"] else "") +
          ". Кто ни разу не запускал бота, получит «не дошло» - Telegram не даёт боту писать первым.")
    return todo


def test(camp, targets):
    """Только себе (или указанным): оба варианта текста, Pro не дарим, в журнал не пишем."""
    if not targets:
        admin = os.environ.get("HONESTLOT_ADMIN_CHAT_ID", "").strip()
        if not admin:
            raise SystemExit("Кому слать? Укажите @ник или telegram_id (HONESTLOT_ADMIN_CHAT_ID не задан)")
        targets = [admin]
    sender = Sender(camp)
    sample_until = lots.now_msk() + datetime.timedelta(days=camp["gift_days"]) if camp["gift_days"] else None
    for who in targets:
        tid = billing._who_id(who)
        try:
            for until in ([sample_until, None] if sample_until else [None]):
                sender.send(tid, render(camp, until))
        except telegram.TelegramError as e:
            hint = " - напишите @honestlot_bot /start и повторите" if _blocked(e) else ""
            print(f"Не отправилось {who}: {e}{hint}")
            continue
        print(f"Отправлено {who}" + (" (два варианта: с подарком и без)" if sample_until else ""))


def send(camp, yes=False):
    todo = show(camp)
    if not todo:
        print("Всем уже отправлено.")
        return
    if not yes and input(f"\nОтправить {len(todo)} пользователям? (да/нет) ").strip().lower() not in ("да", "yes", "y", "д"):
        print("Отменено.")
        return
    started = time.time()
    stats, stopped = send_all(camp)
    print(f"\nГотово за {int(time.time() - started)} с: {_fmt(stats)}")
    if stopped:
        print(f"ОСТАНОВЛЕНО: {stopped}\nИсправьте причину и запустите send ещё раз - продолжит с того же места.")


def stats(camp):
    c = conn()
    rows = c.execute("SELECT status, COUNT(*) n, MIN(at) first_at FROM broadcast_log WHERE campaign = ? GROUP BY status",
                     (camp["name"],)).fetchall()
    if not rows:
        print(f"Кампания «{camp['name']}» ещё не отправлялась")
        return
    started = min(r["first_at"] for r in rows)
    print(f"Кампания «{camp['name']}», начата {started[:16].replace('T', ' ')}: "
          f"{_fmt({r['status']: r['n'] for r in rows})}")
    gifts = c.execute("SELECT COUNT(*) FROM broadcast_log WHERE campaign = ? AND gift_until IS NOT NULL",
                      (camp["name"],)).fetchone()[0]
    opened = c.execute("SELECT COUNT(DISTINCT e.telegram_id) FROM events e JOIN broadcast_log b "
                       "ON b.campaign = ? AND b.telegram_id = e.telegram_id "
                       "WHERE e.type = 'notify_open' AND e.source = 'broadcast' AND e.created_at >= ?",
                       (camp["name"], started)).fetchone()[0]
    line = f"Открыли мини-апп кнопкой из рассылки: {opened}"
    if camp["lot_id"]:
        viewed = c.execute("SELECT COUNT(DISTINCT e.telegram_id) FROM events e JOIN broadcast_log b "
                           "ON b.campaign = ? AND b.telegram_id = e.telegram_id "
                           "WHERE e.type = 'lot_view' AND e.lot_id = ? AND e.created_at >= ?",
                           (camp["name"], str(camp["lot_id"]), started)).fetchone()[0]
        line += f"; смотрели лот {camp['lot_id']}: {viewed}"
    print(line + (f"; подарен Pro: {gifts}" if gifts else ""))


def _cli(argv):
    usage = "python -m app.broadcast show|test|send|stats <файл кампании> [@ник|id ... для test] [--yes для send]"
    if len(argv) < 2 or argv[0] not in ("show", "test", "send", "stats"):
        raise SystemExit(usage)
    camp = load(argv[1])
    if argv[0] == "show":
        show(camp)
    elif argv[0] == "test":
        test(camp, argv[2:])
    elif argv[0] == "send":
        send(camp, yes="--yes" in argv[2:])
    else:
        stats(camp)


if __name__ == "__main__":
    _cli(sys.argv[1:])
