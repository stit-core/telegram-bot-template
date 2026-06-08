"""usecase.py — оркестрация отправки заказа. Знает порт BookingGateway. Без aiogram/redis."""

from __future__ import annotations

from pylibinfra.logkit import Logger

from bot.features.booking.dto import BookingResult
from bot.features.booking.ports import BookingGateway
from bot.features.booking.state import BookingDraft


class BookingUsecase:
    def __init__(self, gateway: BookingGateway, log: Logger) -> None:
        self._gateway = gateway
        self._log = log

    async def submit(
        self, backend_user_id: str, draft: BookingDraft, idempotency_key: str
    ) -> BookingResult:
        result = await self._gateway.submit(backend_user_id, draft, idempotency_key)
        self._log.info("booking.submitted", confirmation_id=result.confirmation_id)
        return result
