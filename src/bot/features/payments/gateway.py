"""gateway.py — HTTP-реализация PaymentsGateway поверх platform/backend. I/O + маппинг ошибок.

fulfill/revoke идемпотентны на бэкенде: Idempotency-Key = charge_id (повторный успешный
платёж/возврат/ретрай httpclient не приведёт к двойной выдаче или двойному откату).
"""

from __future__ import annotations

from typing import Any

from pylibinfra.tgbotkit import Money

from bot.features.payments import errors
from bot.features.payments.dto import Order
from bot.platform.backend import (
    BackendClient,
    BackendConflict,
    BackendNotFound,
    BackendUnavailable,
)


class HttpPaymentsGateway:
    def __init__(self, http: BackendClient) -> None:
        self._http = http

    async def get_offer(self, offer_id: str) -> Order:
        try:
            raw = await self._http.get(f"/v1/offers/{offer_id}")
        except BackendNotFound as exc:
            raise errors.OrderNotFound(str(exc)) from exc
        except BackendUnavailable as exc:
            raise errors.PaymentError("Сервис оплаты недоступен") from exc
        return self._to_order(raw)

    async def fulfill(self, order_id: str, charge_id: str) -> None:
        try:
            await self._http.post(
                f"/v1/orders/{order_id}/fulfill",
                json={"charge_id": charge_id},
                idempotency_key=charge_id,
            )
        except BackendConflict:
            # 409 на идемпотентный fulfill — выдача уже применена бэкендом, повтор = успех
            return
        except BackendUnavailable as exc:
            raise errors.PaymentError("Сервис оплаты недоступен") from exc

    async def revoke(self, order_id: str, charge_id: str) -> None:
        try:
            await self._http.post(
                f"/v1/orders/{order_id}/revoke",
                json={"charge_id": charge_id},
                idempotency_key=f"revoke:{charge_id}",
            )
        except (BackendConflict, BackendNotFound):
            # уже откачено / нечего откатывать — идемпотентный повтор = успех
            return
        except BackendUnavailable as exc:
            raise errors.PaymentError("Сервис оплаты недоступен") from exc

    async def payer_of(self, charge_id: str) -> int | None:
        try:
            raw = await self._http.get(f"/v1/charges/{charge_id}")
        except BackendNotFound:
            return None
        except BackendUnavailable as exc:
            raise errors.PaymentError("Сервис оплаты недоступен") from exc
        return int(raw["user_id"])

    @staticmethod
    def _to_order(raw: dict[str, Any]) -> Order:
        return Order(
            order_id=str(raw["id"]),
            title=raw["title"],
            description=raw.get("description", ""),
            price=Money(amount_minor=int(raw["amount"]), currency=raw.get("currency", "XTR")),
        )
