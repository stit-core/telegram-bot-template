"""Unit: payments.policy + usecase.confirm — «не доверять клиенту» (сверка с бэкендом)."""

from __future__ import annotations

import pytest
from pylibinfra.logkit import nop

from bot.features.payments import errors, policy
from bot.features.payments.dto import Order
from bot.features.payments.usecase import PaymentsUsecase

pytestmark = pytest.mark.unit

_ORDER = Order(order_id="premium-30d", title="Премиум", description="", amount=100, currency="XTR")


class _FakeGateway:
    def __init__(self, order: Order | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error

    async def get_offer(self, offer_id: str) -> Order:
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def fulfill(self, order_id: str, charge_id: str) -> None:
        pass


def test_amount_matches() -> None:
    assert policy.amount_matches(100, 100) is True
    assert policy.amount_matches(100, 99) is False
    assert policy.amount_matches(100, 0) is False


async def test_confirm_matching_amount() -> None:
    uc = PaymentsUsecase(_FakeGateway(_ORDER), nop())
    assert await uc.confirm("premium-30d", 100, "XTR") is True


async def test_confirm_rejects_wrong_amount() -> None:
    uc = PaymentsUsecase(_FakeGateway(_ORDER), nop())
    # клиент прислал заниженную сумму — не доверяем, сверяем с бэкендом → отказ
    assert await uc.confirm("premium-30d", 50, "XTR") is False


async def test_confirm_rejects_wrong_currency() -> None:
    uc = PaymentsUsecase(_FakeGateway(_ORDER), nop())
    assert await uc.confirm("premium-30d", 100, "USD") is False


async def test_confirm_fails_closed_on_backend_error() -> None:
    uc = PaymentsUsecase(_FakeGateway(error=errors.PaymentError("down")), nop())
    assert await uc.confirm("premium-30d", 100, "XTR") is False
