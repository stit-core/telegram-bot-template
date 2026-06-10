"""errors.py — sentinel-ошибки фичи booking. PURE."""

from __future__ import annotations

from bot.shared.errors import FeatureError


class BookingError(FeatureError):
    """Базовая ошибка оформления заказа."""


class BookingUnavailable(BookingError):
    """Бэкенд заказов недоступен."""


class GuestsRejected(BookingError):
    """Число гостей не прошло бизнес-валидацию (шаг DETAILS)."""


class AddressRejected(BookingError):
    """Адрес не прошёл бизнес-валидацию (шаг ADDRESS)."""
