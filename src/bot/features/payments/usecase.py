"""usecase.py — оркестрация оплаты. Знает порт PaymentsGateway и policy. Без aiogram/redis.

confirm() — сердце «не доверять клиенту»: грузит авторитетную цену с бэкенда (get_offer) и
сверяет её с суммой/валютой из pre_checkout через чистую policy. complete()/reverse() — выдача и
её откат (gateway делает их идемпотентными по charge_id; дедуп самих апдейтов — в хендлере через
Charge/RefundGuard). payer_of() — резолв плательщика для admin-refund.
"""

from __future__ import annotations

from pylibinfra.logkit import Logger

from bot.features.payments import errors, policy
from bot.features.payments.dto import Order
from bot.features.payments.ports import PaymentsGateway


class PaymentsUsecase:
    def __init__(self, gateway: PaymentsGateway, log: Logger) -> None:
        self._gateway = gateway
        self._log = log

    async def offer(self, offer_id: str) -> Order:
        return await self._gateway.get_offer(offer_id)

    async def confirm(self, payload: str, total_amount: int, currency: str) -> bool:
        try:
            order = await self._gateway.get_offer(payload)
        except errors.PaymentError:
            return False  # нет оффера/бэкенд недоступен → fail-closed (платёж не подтверждаем)
        return order.price.currency == currency and policy.amount_matches(
            order.price.amount_minor, total_amount
        )

    async def complete(self, payload: str, charge_id: str) -> None:
        await self._gateway.fulfill(payload, charge_id)
        self._log.info("payments.fulfilled", order_id=payload, charge_id=charge_id)

    async def reverse(self, payload: str, charge_id: str) -> None:
        await self._gateway.revoke(payload, charge_id)
        self._log.info("payments.reversed", order_id=payload, charge_id=charge_id)

    async def payer_of(self, charge_id: str) -> int | None:
        return await self._gateway.payer_of(charge_id)
