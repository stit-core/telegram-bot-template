"""BookingAPI — заказы core-бэкенда (/v1/bookings)."""

from __future__ import annotations

from bot.pkg.http_client.api import JsonApi
from bot.pkg.http_client.idempotency import idempotency_key
from bot.pkg.http_client.wire import WireModel


class BookingConfirmation(WireModel):
    confirmation_id: str


class BookingAPI:
    def __init__(self, api: JsonApi) -> None:
        self._api = api

    async def submit_booking(
        self,
        *,
        draft_id: str,
        user_id: str,
        services: list[str],
        guests: int,
        address: str | None,
    ) -> BookingConfirmation:
        # Ключ от (draft_id + содержимое): повтор «Подтвердить» не создаёт дубль заказа,
        # а изменённый черновик того же визарда получает новый ключ (не 409 на бэкенде).
        key = idempotency_key(
            "booking-submit", draft_id, user_id, *services, str(guests), address or ""
        )
        return await self._api.post(
            "/v1/bookings",
            json={
                "user_id": user_id,
                "services": services,
                "guests": guests,
                "address": address,
            },
            idempotency_key=key,
            model=BookingConfirmation,
        )
