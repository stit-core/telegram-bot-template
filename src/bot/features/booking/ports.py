"""ports.py — порт бэкенда заказов (Protocol). PURE.

submit — отправка собранного черновика; идемпотентно по idempotency_key (повтор клика
«Подтвердить» не создаст второй заказ). Реализация — gateway.py, связь — provider.py.
"""

from __future__ import annotations

from typing import Protocol

from bot.features.booking.dto import BookingResult
from bot.features.booking.state import BookingDraft


class BookingGateway(Protocol):
    async def submit(
        self, backend_user_id: str, draft: BookingDraft, idempotency_key: str
    ) -> BookingResult: ...
