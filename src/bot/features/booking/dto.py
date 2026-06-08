"""dto.py — результат отправки заказа (anti-corruption). PURE."""

from __future__ import annotations

from pydantic import BaseModel


class BookingResult(BaseModel):
    confirmation_id: str
