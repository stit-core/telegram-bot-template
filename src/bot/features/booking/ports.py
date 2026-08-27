"""ports.py — порт фичи booking (Protocol). PURE.

Типизирован wire-моделью pkg-клиента — BookingAPI удовлетворяет порт структурно,
без адаптера (связывает provider.py, DIP). Idempotency-Key считает клиент сам из
draft_id + содержимого (канон pkg.http_client.idempotency) — повтор «Подтвердить»
не создаст второй заказ.
"""

from __future__ import annotations

from typing import Protocol

from bot.pkg.http_client.internal.booking import BookingConfirmation


class BookingGateway(Protocol):
    async def submit_booking(
        self,
        *,
        draft_id: str,
        user_id: str,
        services: list[str],
        guests: int,
        address: str | None,
    ) -> BookingConfirmation: ...
