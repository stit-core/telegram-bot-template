"""views.py — оффер → данные окна. PURE."""

from __future__ import annotations

from typing import Any

from bot.features.payments.dto import Order


def to_offer(order: Order) -> dict[str, Any]:
    return {
        "title": order.title,
        "description": order.description,
        "amount": order.price.amount_minor,
    }
