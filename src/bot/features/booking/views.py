"""views.py — доменная ошибка booking → user-текст. PURE."""

from __future__ import annotations

from bot.features.booking.errors import BookingError


def error_text(err: BookingError) -> str:
    return str(err) or "Не удалось оформить заказ, попробуйте позже."
