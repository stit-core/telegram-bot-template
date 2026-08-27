"""PaymentsAPI — офферы/заказы/чарджи core-бэкенда (/v1/offers, /v1/orders, /v1/charges)."""

from __future__ import annotations

from bot.pkg.http_client.api import JsonApi
from bot.pkg.http_client.errors import ConflictError, NotFoundError
from bot.pkg.http_client.idempotency import idempotency_key
from bot.pkg.http_client.wire import WireModel


class Offer(WireModel):
    id: str
    title: str
    description: str = ""
    amount: int
    currency: str


class Charge(WireModel):
    user_id: int


class PaymentsAPI:
    def __init__(self, api: JsonApi) -> None:
        self._api = api

    async def get_offer(self, offer_id: str) -> Offer:
        return await self._api.get(f"/v1/offers/{offer_id}", model=Offer)

    async def fulfill_order(self, order_id: str, charge_id: str) -> None:
        # fulfill идемпотентен по charge_id; 409 = выдача уже применена → успех
        try:
            await self._api.post(
                f"/v1/orders/{order_id}/fulfill",
                json={"charge_id": charge_id},
                idempotency_key=idempotency_key("order-fulfill", charge_id),
            )
        except ConflictError:
            return

    async def revoke_order(self, order_id: str, charge_id: str) -> None:
        # 409/404 = уже откачено / нечего откатывать — идемпотентный повтор = успех
        try:
            await self._api.post(
                f"/v1/orders/{order_id}/revoke",
                json={"charge_id": charge_id},
                idempotency_key=idempotency_key("order-revoke", charge_id),
            )
        except (ConflictError, NotFoundError):
            return

    async def find_charge(self, charge_id: str) -> Charge | None:
        try:
            return await self._api.get(f"/v1/charges/{charge_id}", model=Charge)
        except NotFoundError:
            return None
