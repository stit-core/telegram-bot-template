"""ports.py — порт платёжного бэкенда (Protocol). PURE.

Типизирован wire-моделями pkg-клиента — PaymentsAPI удовлетворяет порт структурно, без
адаптера (связывает provider.py, DIP). get_offer — авторитетная цена/состав (сверка в
pre_checkout); fulfill_order — выдача (идемпотентно по charge_id); revoke_order — откат
выдачи при возврате; find_charge — кто оплатил charge (для admin-refund).
"""

from __future__ import annotations

from typing import Protocol

from bot.pkg.http_client.internal.payments import Charge, Offer


class PaymentsGateway(Protocol):
    async def get_offer(self, offer_id: str) -> Offer: ...

    async def fulfill_order(self, order_id: str, charge_id: str) -> None: ...

    async def revoke_order(self, order_id: str, charge_id: str) -> None: ...

    async def find_charge(self, charge_id: str) -> Charge | None: ...
