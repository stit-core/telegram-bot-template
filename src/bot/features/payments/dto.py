"""dto.py — доменный оффер/заказ (anti-corruption). PURE.

Цена — Money(amount_minor, currency) из tgbotkit: amount_minor у XTR (Telegram Stars) —
это количество звёзд (не сотые доли). Цена/состав авторитетны с бэкенда; этот DTO лишь
переносит проверенные значения в presentation/инвойс.
"""

from __future__ import annotations

from pydantic import BaseModel
from pylibinfra.tgbotkit import Money


class Order(BaseModel):
    order_id: str
    title: str
    description: str
    price: Money
