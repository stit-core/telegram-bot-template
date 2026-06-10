"""PaymentsAPI — офферы/заказы/чарджи core-бэкенда (/v1/offers, /v1/orders, /v1/charges)."""

from __future__ import annotations

from pydantic import BaseModel
from pylibinfra.httpclient import ApiClient, ConflictError, NotFoundError

from bot.pkg.http_client.internal.codec import parse


class Offer(BaseModel):
    id: str
    title: str
    description: str = ""
    amount: int
    currency: str = "XTR"


class Charge(BaseModel):
    user_id: int


class PaymentsAPI:
    def __init__(self, api: ApiClient) -> None:
        self._api = api

    async def get_offer(self, offer_id: str) -> Offer:
        raw = await self._api.get(f"/v1/offers/{offer_id}")
        return parse(Offer, raw)

    async def fulfill_order(self, order_id: str, charge_id: str) -> None:
        # fulfill идемпотентен (Idempotency-Key=charge_id); 409 = выдача уже применена → успех
        try:
            await self._api.post(
                f"/v1/orders/{order_id}/fulfill",
                json={"charge_id": charge_id},
                idempotency_key=charge_id,
            )
        except ConflictError:
            return

    async def revoke_order(self, order_id: str, charge_id: str) -> None:
        # 409/404 = уже откачено / нечего откатывать — идемпотентный повтор = успех
        try:
            await self._api.post(
                f"/v1/orders/{order_id}/revoke",
                json={"charge_id": charge_id},
                idempotency_key=f"revoke:{charge_id}",
            )
        except (ConflictError, NotFoundError):
            return

    async def find_charge(self, charge_id: str) -> Charge | None:
        try:
            raw = await self._api.get(f"/v1/charges/{charge_id}")
        except NotFoundError:
            return None
        return parse(Charge, raw)
