"""ports.py — порт платёжного бэкенда (Protocol). PURE.

get_offer — авторитетная цена/состав (для сверки в pre_checkout); fulfill — выдача после
успешной оплаты (идемпотентно по charge_id). Реализация — gateway.py, связь — provider.py.
"""

from __future__ import annotations

from typing import Protocol

from bot.features.payments.dto import Order


class PaymentsGateway(Protocol):
    async def get_offer(self, offer_id: str) -> Order: ...

    async def fulfill(self, order_id: str, charge_id: str) -> None: ...
