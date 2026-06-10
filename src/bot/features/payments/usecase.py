"""usecase.py — оркестрация оплаты. Знает порт PaymentsGateway и policy. Без aiogram/redis.

Anti-corruption: wire-Offer → доменный Order(Money) и typed-ошибки httpclient → sentinel'ы
фичи — здесь. confirm() — сердце «не доверять клиенту»: грузит авторитетную цену с бэкенда
и сверяет её с суммой/валютой из pre_checkout через чистую policy. complete()/reverse() —
выдача и её откат (идемпотентны по charge_id на бэкенде; дедуп самих апдейтов — в хендлере
через Charge/RefundGuard). payer_of() — резолв плательщика для admin-refund.
"""

from __future__ import annotations

from pylibinfra.httpclient import NotFoundError, UnavailableError
from pylibinfra.logkit import Logger
from pylibinfra.tgbotkit import Money

from bot.features.payments import errors, policy
from bot.features.payments.dto import Order
from bot.features.payments.ports import PaymentsGateway

_UNAVAILABLE = "Сервис оплаты недоступен"


class PaymentsUsecase:
    def __init__(self, gateway: PaymentsGateway, log: Logger) -> None:
        self._gateway = gateway
        self._log = log

    async def offer(self, offer_id: str) -> Order:
        try:
            offer = await self._gateway.get_offer(offer_id)
        except NotFoundError as exc:
            raise errors.OrderNotFound(str(exc)) from exc
        except UnavailableError as exc:
            raise errors.PaymentError(_UNAVAILABLE) from exc
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
        except UnavailableError as exc:
            raise errors.PaymentError(_UNAVAILABLE) from exc
        self._log.info("payments.fulfilled", order_id=payload, charge_id=charge_id)

    async def reverse(self, payload: str, charge_id: str) -> None:
        try:
            await self._gateway.revoke_order(payload, charge_id)
        except UnavailableError as exc:
            raise errors.PaymentError(_UNAVAILABLE) from exc
        self._log.info("payments.reversed", order_id=payload, charge_id=charge_id)

    async def payer_of(self, charge_id: str) -> int | None:
        try:
            charge = await self._gateway.find_charge(charge_id)
        except UnavailableError as exc:
            raise errors.PaymentError(_UNAVAILABLE) from exc
        return charge.user_id if charge is not None else None
