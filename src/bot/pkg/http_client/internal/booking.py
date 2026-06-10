"""BookingAPI — заказы core-бэкенда (/v1/bookings)."""

from __future__ import annotations

from pydantic import BaseModel
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.internal.codec import parse


class BookingConfirmation(BaseModel):
    confirmation_id: str


class BookingAPI:
    def __init__(self, api: ApiClient) -> None:
        self._api = api

    async def submit_booking(
        self,
        *,
        user_id: str,
        services: list[str],
        guests: int,
        address: str | None,
        idempotency_key: str,
    ) -> BookingConfirmation:
        # submit идемпотентен на бэкенде по Idempotency-Key — повтор не создаст дубль заказа
        raw = await self._api.post(
            "/v1/bookings",
            json={
                "user_id": user_id,
                "services": services,
                "guests": guests,
                "address": address,
            },
            idempotency_key=idempotency_key,
        )
        return parse(BookingConfirmation, raw)
