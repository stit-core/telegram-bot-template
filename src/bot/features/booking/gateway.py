"""gateway.py — HTTP-реализация BookingGateway поверх platform/backend. I/O + маппинг ошибок.

submit идемпотентен на бэкенде: Idempotency-Key = idempotency_key черновика (draft_id из
dialog_data) — повторная отправка того же черновика не создаст дубль заказа.
"""

from __future__ import annotations

from bot.features.booking import errors
from bot.features.booking.dto import BookingResult
from bot.features.booking.state import BookingDraft
from bot.platform.backend import BackendClient, BackendUnavailable


class HttpBookingGateway:
    def __init__(self, http: BackendClient) -> None:
        self._http = http

    async def submit(
        self, backend_user_id: str, draft: BookingDraft, idempotency_key: str
    ) -> BookingResult:
        try:
            raw = await self._http.post(
                "/v1/bookings",
                json={
                    "user_id": backend_user_id,
                    "services": draft.services,
                    "guests": draft.guests,
                    "address": draft.address,
                },
                idempotency_key=idempotency_key,
            )
        except BackendUnavailable as exc:
            raise errors.BookingUnavailable("Сервис заказов недоступен") from exc
        return BookingResult(confirmation_id=str(raw["confirmation_id"]))
