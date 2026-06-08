"""state.py — черновик wizard'а booking + константы домена. PURE.

BookingDraft — НЕ доменная сущность, а накапливаемый между шагами черновик (rule
storage-serialization): узкие JSON-примитивные поля, живёт в dialog_data. from_data/to_data —
мост к dialog_data (хранится как model_dump(mode="json"), читается через model_validate).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bot.platform.dialogs import states

BookingSG = states.Booking

MAX_GUESTS = 10
DELIVERY_SERVICE = "delivery"
SERVICE_KEYS = ["window_seat", "child_seat", DELIVERY_SERVICE, "gift_wrap"]


class BookingDraft(BaseModel):
    services: list[str] = []
    guests: int = 0
    address: str | None = None

    @classmethod
    def from_data(cls, data: dict[str, Any] | None) -> BookingDraft:
        return cls.model_validate(data or {})

    def to_data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
