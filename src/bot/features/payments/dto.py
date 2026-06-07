"""dto.py — доменный оффер/заказ (anti-corruption). PURE.

amount у XTR (Telegram Stars) — это количество звёзд (не сотые доли). Цена/состав —
авторитетно с бэкенда; этот DTO лишь переносит проверенные значения в presentation.
"""

from __future__ import annotations

from pydantic import BaseModel


class Order(BaseModel):
    order_id: str
    title: str
    description: str
    amount: int
    currency: str = "XTR"
