"""dto.py — результаты шагов wizard'а: usecase решает, handler мапит на экран. PURE."""

from __future__ import annotations

from pydantic import BaseModel

from bot.features.booking.state import BookingDraft


class GuestsStep(BaseModel):
    draft: BookingDraft
    address_required: bool
