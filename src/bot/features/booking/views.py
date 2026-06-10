"""views.py — доменная ошибка booking → user-текст. PURE."""

from __future__ import annotations

from bot.features.booking import errors


def error_text(err: Exception) -> str:
    match err:
        case errors.GuestsRejected() | errors.AddressRejected():
            return str(err) or "Некорректный ввод, попробуйте ещё раз."
        case errors.BookingError():
            return str(err) or "Не удалось оформить заказ, попробуйте позже."
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
