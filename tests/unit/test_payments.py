"""Unit: payments.policy + usecase.confirm — «не доверять клиенту» (сверка с бэкендом)."""

from __future__ import annotations

import pytest
from pylibinfra.httpclient import UnavailableError
from pylibinfra.logkit import nop

from bot.features.payments import policy
from bot.features.payments.usecase import PaymentsUsecase
from bot.pkg.http_client.internal.payments import Charge, Offer

pytestmark = pytest.mark.unit

_OFFER = Offer(id="premium-30d", title="Премиум", amount=100, currency="XTR")


class _FakeGateway:
    def __init__(
        self,
        offer: Offer | None = None,
        error: Exception | None = None,
        payer: int | None = None,
    ) -> None:
        self._offer = offer
        self._error = error
        self._payer = payer
        self.revoked: list[tuple[str, str]] = []

    async def get_offer(self, offer_id: str) -> Offer:
        if self._error is not None:
            raise self._error
        assert self._offer is not None
        return self._offer

    async def fulfill_order(self, order_id: str, charge_id: str) -> None:
        pass

    async def revoke_order(self, order_id: str, charge_id: str) -> None:
        self.revoked.append((order_id, charge_id))

    async def find_charge(self, charge_id: str) -> Charge | None:
        return Charge(user_id=self._payer) if self._payer is not None else None


def test_amount_matches() -> None:
    assert policy.amount_matches(100, 100) is True
    assert policy.amount_matches(100, 99) is False
    assert policy.amount_matches(100, 0) is False


async def test_confirm_matching_amount() -> None:
    uc = PaymentsUsecase(_FakeGateway(_OFFER), nop())
    assert await uc.confirm("premium-30d", 100, "XTR") is True


async def test_confirm_rejects_wrong_amount() -> None:
    uc = PaymentsUsecase(_FakeGateway(_OFFER), nop())
    # клиент прислал заниженную сумму — не доверяем, сверяем с бэкендом → отказ
    assert await uc.confirm("premium-30d", 50, "XTR") is False


async def test_confirm_rejects_wrong_currency() -> None:
    uc = PaymentsUsecase(_FakeGateway(_OFFER), nop())
    assert await uc.confirm("premium-30d", 100, "USD") is False


async def test_confirm_fails_closed_on_backend_error() -> None:
    uc = PaymentsUsecase(_FakeGateway(error=UnavailableError("down")), nop())
    assert await uc.confirm("premium-30d", 100, "XTR") is False


async def test_reverse_revokes_fulfillment() -> None:
    gw = _FakeGateway(_OFFER)
    uc = PaymentsUsecase(gw, nop())
    await uc.reverse("premium-30d", "charge-1")
    assert gw.revoked == [("premium-30d", "charge-1")]


async def test_payer_of_delegates_to_gateway() -> None:
    uc = PaymentsUsecase(_FakeGateway(_OFFER, payer=42), nop())
    assert await uc.payer_of("charge-1") == 42
