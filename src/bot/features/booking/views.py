"""views.py — доменная ошибка booking → ключ user-текста (.ftl). PURE."""

from __future__ import annotations

from bot.features.booking import errors


def error_text(err: Exception) -> str:
    match err:
        case errors.GuestsRejected():
            return "booking-error-guests"
        case errors.AddressRejected():
            return "booking-error-address"
        case errors.BookingConflict():
            return "booking-error-conflict"
        case errors.BookingError():
            return "booking-error-unavailable"
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
