"""errors.py — sentinel-ошибки фичи booking. PURE."""

from __future__ import annotations

from bot.shared.errors import FeatureError


class BookingError(FeatureError):
    """Базовая ошибка оформления заказа."""


class BookingUnavailable(BookingError):
    """Бэкенд заказов недоступен."""
