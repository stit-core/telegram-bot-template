"""views.py — оффер → данные окна; доменная ошибка → ключ user-текста (.ftl). PURE."""

from __future__ import annotations

from typing import Any

from bot.features.payments import errors
from bot.features.payments.dto import Order


def to_offer(order: Order) -> dict[str, Any]:
    return {
        "title": order.title,
        "description": order.description,
        "amount": order.price.amount_minor,
    }


def error_text(err: Exception) -> str:
    match err:
        case errors.OrderNotFound():
            return "payments-error-not-found"
        case errors.PaymentError():
            return "payments-error-unavailable"
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
