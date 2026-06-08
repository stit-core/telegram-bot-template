"""Фасад фичи booking: Provider + dialog (reference-wizard заказа/брони)."""

from __future__ import annotations

from bot.features.booking.dialogs import booking_dialog as dialog
from bot.features.booking.provider import BookingProvider as Provider

__all__ = ["Provider", "dialog"]
