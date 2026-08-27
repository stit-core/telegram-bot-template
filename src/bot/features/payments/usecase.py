"""usecase.py — оркестрация оплаты. Знает порт PaymentsGateway и policy. Без aiogram/redis.

Anti-corruption: wire-Offer → доменный Order(Money) и typed-ошибки HTTP-границы → sentinel'ы
фичи (catch-all ApiError → PaymentUnavailable) — здесь. confirm() — сердце «не доверять
клиенту»: грузит авторитетную цену с бэкенда и сверяет её с суммой/валютой из pre_checkout
через чистую policy. complete()/reverse() —
выдача и её откат (идемпотентны по charge_id на бэкенде; дедуп самих апдейтов — в хендлере
через Charge/RefundGuard). payer_of() — резолв плательщика для admin-refund.
"""

from __future__ import annotations

from pylibinfra.logkit import Logger
from pylibinfra.tgbotkit import Money

from bot.features.payments import errors, policy
from bot.features.payments.dto import Order
from bot.features.payments.ports import PaymentsGateway
from bot.pkg.http_client.errors import ApiError, NotFoundError


class PaymentsUsecase:
    def __init__(self, gateway: PaymentsGateway, log: Logger) -> None:
        self._gateway = gateway
        self._log = log

    async def offer(self, offer_id: str) -> Order:
        try:
            offer = await self._gateway.get_offer(offer_id)
        except NotFoundError as exc:
            raise errors.OrderNotFound from exc
        except ApiError as exc:
            self._log.warn(
                "payments.backend_fault", kind=type(exc).__name__, status=exc.status_code
            )
            raise errors.PaymentUnavailable from exc
        return Order(
            order_id=offer.id,
            title=offer.title,
            description=offer.description,
            price=Money(amount_minor=offer.amount, currency=offer.currency),
        )

    async def confirm(self, payload: str, total_amount: int, currency: str) -> bool:
        try:
            order = await self.offer(payload)
        except errors.PaymentError:
            return False  # нет оффера/бэкенд недоступен → fail-closed (платёж не подтверждаем)
        return order.price.currency == currency and policy.amount_matches(
            order.price.amount_minor, total_amount
        )

    async def complete(self, payload: str, charge_id: str) -> None:
        try:
            await self._gateway.fulfill_order(payload, charge_id)
        except ApiError as exc:
            self._log.warn(
                "payments.backend_fault", kind=type(exc).__name__, status=exc.status_code
            )
            raise errors.PaymentUnavailable from exc
        self._log.info("payments.fulfilled", order_id=payload, charge_id=charge_id)

    async def reverse(self, payload: str, charge_id: str) -> None:
        try:
            await self._gateway.revoke_order(payload, charge_id)
        except ApiError as exc:
            self._log.warn(
                "payments.backend_fault", kind=type(exc).__name__, status=exc.status_code
            )
            raise errors.PaymentUnavailable from exc
        self._log.info("payments.reversed", order_id=payload, charge_id=charge_id)

    async def payer_of(self, charge_id: str) -> int | None:
        try:
            charge = await self._gateway.find_charge(charge_id)
        except ApiError as exc:
            self._log.warn(
                "payments.backend_fault", kind=type(exc).__name__, status=exc.status_code
            )
            raise errors.PaymentUnavailable from exc
        return charge.user_id if charge is not None else None
