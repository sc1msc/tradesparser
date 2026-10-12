# -*- coding: utf-8 -*-
r"""
Провайдеры приёма платежей для подписки Pro (billing.py) - за одним
интерфейсом, чтобы сменить сервис оплаты, не трогая логику подписок.

Интерфейс провайдера (все суммы - целые рубли):
  create_payment(order_id, amount, description, email, save_method, return_url, metadata)
      -> Payment: первый платёж; пользователь подтверждает его на странице
         провайдера (confirmation_url). save_method=True - провайдер сохраняет
         способ оплаты для автопродления.
  charge_saved(order_id, amount, description, email, payment_method_id, metadata)
      -> Payment: автосписание по сохранённому способу, без участия пользователя.
  get_payment(payment_id) -> Payment: свежее состояние у провайдера.
  payment_id_from_webhook(body) -> id платежа из уведомления или None.

Уведомлениям (вебхукам) не доверяем: из уведомления берём только id и
перечитываем платёж у провайдера по API (get_payment). ЮKassa подписи у
уведомлений не ставит, а так подделать "оплачено" нельзя.

order_id - наш идентификатор операции; он же ключ идемпотентности у
провайдера: повтор запроса (обрыв связи, второй клик) не создаст второй платёж.

Провайдеры:
  yookassa - ЮKassa (решение владельца, wiki/monetization.md). Только стандартная
             библиотека, как telegram.py. Автоплатежи в рабочем магазине включает
             менеджер ЮKassa; в тестовом магазине они работают сразу.
  fake     - для локальной проверки без денег: "страница оплаты" - наша же
             (/api/pay/fake/confirm), автосписания проходят (или все падают при
             HONESTLOT_FAKE_FAIL_RENEWALS=1). Состояние - в памяти процесса.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class ProviderError(Exception):
    """Ошибка провайдера или связи с ним. В тексте нет ключей.
    permanent=True - провайдер отказал в самом запросе (например, способ оплаты
    отвязан): повтор не поможет, для автопродления это неудачная попытка."""

    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent


@dataclass
class Payment:
    id: str
    status: str                      # pending | succeeded | canceled
    amount: int
    confirmation_url: str | None = None
    payment_method_id: str | None = None   # если способ оплаты сохранён
    payment_method_title: str | None = None
    cancel_reason: str | None = None
    metadata: dict = field(default_factory=dict)


# ---------- ЮKassa ----------

class YooKassa:
    name = "yookassa"
    API = "https://api.yookassa.ru/v3"

    def __init__(self, shop_id, secret_key, send_receipt=False):
        if not shop_id or not secret_key:
            raise ProviderError("не заданы YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY")
        self._auth = "Basic " + base64.b64encode(f"{shop_id}:{secret_key}".encode()).decode()
        # Чек по 54-ФЗ в запросе - для ИП/ООО с "Чеками от ЮKassa". Самозанятому
        # ЮKassa сама регистрирует доход в "Мой налог" - чек в запросе не нужен.
        self.send_receipt = send_receipt

    def _request(self, method, path, body=None, idempotence_key=None):
        headers = {"Authorization": self._auth, "Content-Type": "application/json"}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(self.API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                err = json.load(e)
                text = f"{err.get('code')}: {err.get('description')}"
            except ValueError:
                text = ""
            # 4xx (кроме 429 "слишком часто") - отказ в самом запросе, 5xx - сбой у ЮKassa
            raise ProviderError(f"ЮKassa HTTP {e.code} {text}".strip(),
                                permanent=400 <= e.code < 500 and e.code != 429) from None
        except (urllib.error.URLError, OSError) as e:
            raise ProviderError(f"нет связи с ЮKassa: {getattr(e, 'reason', e)}") from None

    def _receipt(self, amount, description, email):
        return {
            "customer": {"email": email},
            "items": [{
                "description": description[:128],
                "quantity": "1.00",
                "amount": {"value": f"{amount}.00", "currency": "RUB"},
                "vat_code": 1,                 # без НДС
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }],
        }

    def _body(self, amount, description, email, metadata):
        body = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "capture": True,
            "description": description[:128],
            "metadata": {k: str(v) for k, v in metadata.items()},
        }
        if self.send_receipt and email:
            body["receipt"] = self._receipt(amount, description, email)
        return body

    @staticmethod
    def _payment(obj):
        method = obj.get("payment_method") or {}
        status = obj.get("status")
        return Payment(
            id=obj["id"],
            status={"succeeded": "succeeded", "canceled": "canceled"}.get(status, "pending"),
            amount=int(float((obj.get("amount") or {}).get("value") or 0)),
            confirmation_url=(obj.get("confirmation") or {}).get("confirmation_url"),
            payment_method_id=method.get("id") if method.get("saved") else None,
            payment_method_title=method.get("title") or method.get("type"),
            cancel_reason=(obj.get("cancellation_details") or {}).get("reason"),
            metadata=obj.get("metadata") or {},
        )

    def create_payment(self, order_id, amount, description, email, save_method, return_url, metadata):
        body = self._body(amount, description, email, metadata)
        body["confirmation"] = {"type": "redirect", "return_url": return_url}
        body["save_payment_method"] = bool(save_method)
        return self._payment(self._request("POST", "/payments", body, idempotence_key=order_id))

    def charge_saved(self, order_id, amount, description, email, payment_method_id, metadata):
        body = self._body(amount, description, email, metadata)
        body["payment_method_id"] = payment_method_id
        return self._payment(self._request("POST", "/payments", body, idempotence_key=order_id))

    def get_payment(self, payment_id):
        return self._payment(self._request("GET", f"/payments/{payment_id}"))

    @staticmethod
    def payment_id_from_webhook(body):
        obj = (body or {}).get("object") or {}
        return obj.get("id") if str((body or {}).get("event", "")).startswith("payment.") else None


# ---------- тестовый провайдер ----------

class FakeProvider:
    """Без денег и без сети - для локальной проверки всего пути оплаты."""
    name = "fake"
    _payments = {}  # id -> dict; общий на процесс

    def __init__(self, site_url):
        self.site_url = site_url.rstrip("/")

    def _save(self, order_id, amount, status, metadata, **extra):
        p = self._payments.get(order_id)
        if p is None:  # идемпотентность: повтор с тем же order_id - тот же платёж
            p = {"id": f"fake-{order_id}", "amount": amount, "status": status, "metadata": metadata, **extra}
            self._payments[order_id] = p
            self._payments[p["id"]] = p
        return self._payment(p)

    def _payment(self, p):
        return Payment(id=p["id"], status=p["status"], amount=p["amount"], confirmation_url=p.get("confirmation_url"),
                       payment_method_id=p.get("method_id") if p["status"] == "succeeded" else None,
                       payment_method_title=p.get("method_title"), cancel_reason=p.get("cancel_reason"),
                       metadata=p["metadata"])

    def create_payment(self, order_id, amount, description, email, save_method, return_url, metadata):
        return self._save(order_id, amount, "pending", metadata,
                          confirmation_url=f"{self.site_url}/api/pay/fake/confirm?id=fake-{order_id}",
                          return_url=return_url,
                          method_id=f"fake-card-{order_id}" if save_method else None,
                          method_title="Тестовая карта *4242")

    def charge_saved(self, order_id, amount, description, email, payment_method_id, metadata):
        fail = os.environ.get("HONESTLOT_FAKE_FAIL_RENEWALS") == "1"
        if os.environ.get("HONESTLOT_FAKE_REJECT_RENEWALS") == "1":
            raise ProviderError("тест: способ оплаты отвязан", permanent=True)
        return self._save(order_id, amount, "canceled" if fail else "succeeded", metadata,
                          method_id=payment_method_id, method_title="Тестовая карта *4242",
                          cancel_reason="insufficient_funds" if fail else None)

    def get_payment(self, payment_id):
        p = self._payments.get(payment_id)
        if p is None:
            raise ProviderError(f"нет платежа {payment_id}")
        return self._payment(p)

    def finish(self, payment_id, paid):
        """Действие "пользователя" на тестовой странице оплаты -> адрес возврата."""
        p = self._payments[payment_id]
        if p["status"] == "pending":
            p["status"] = "succeeded" if paid else "canceled"
            if not paid:
                p["cancel_reason"] = "canceled_by_user"
        return p.get("return_url")

    @staticmethod
    def payment_id_from_webhook(body):
        return (body or {}).get("id")


def from_env(site_url):
    name = os.environ.get("HONESTLOT_PAY_PROVIDER", "yookassa")
    if name == "fake":
        return FakeProvider(site_url)
    if name == "yookassa":
        return YooKassa(os.environ.get("YOOKASSA_SHOP_ID", ""), os.environ.get("YOOKASSA_SECRET_KEY", ""),
                        send_receipt=os.environ.get("HONESTLOT_PAY_RECEIPTS") == "1")
    raise ProviderError(f"неизвестный провайдер оплаты: {name}")
