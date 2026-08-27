"""PaymentsAPI: идемпотентные fulfill/revoke (409/404 = успех) + find_charge → None на 404."""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.errors import UnavailableError
from bot.pkg.http_client.internal.payments import PaymentsAPI

pytestmark = pytest.mark.pkg


def _key(operation: str, charge_id: str) -> str:
    return f"{operation}:{hashlib.sha256(charge_id.encode()).hexdigest()}"


@respx.mock
async def test_get_offer_returns_model(api: ApiClient) -> None:
    respx.get("http://backend/v1/offers/o1").mock(
        return_value=httpx.Response(
            200, json={"id": "o1", "title": "Pro", "amount": 100, "currency": "XTR"}
        )
    )
    offer = await PaymentsAPI(api).get_offer("o1")
    assert offer.title == "Pro"
    assert offer.currency == "XTR"


@respx.mock
async def test_fulfill_order_conflict_is_success(api: ApiClient) -> None:
    route = respx.post("http://backend/v1/orders/ord1/fulfill").mock(
        return_value=httpx.Response(409)
    )
    await PaymentsAPI(api).fulfill_order("ord1", "ch1")
    assert route.calls.last.request.headers["Idempotency-Key"] == _key("order-fulfill", "ch1")


@respx.mock
async def test_fulfill_order_5xx_raises_unavailable(api: ApiClient) -> None:
    respx.post("http://backend/v1/orders/ord1/fulfill").mock(return_value=httpx.Response(503))
    with pytest.raises(UnavailableError):
        await PaymentsAPI(api).fulfill_order("ord1", "ch1")


@respx.mock
async def test_revoke_order_404_is_success(api: ApiClient) -> None:
    route = respx.post("http://backend/v1/orders/ord1/revoke").mock(
        return_value=httpx.Response(404)
    )
    await PaymentsAPI(api).revoke_order("ord1", "ch1")
    assert route.calls.last.request.headers["Idempotency-Key"] == _key("order-revoke", "ch1")


@respx.mock
async def test_find_charge_404_is_none(api: ApiClient) -> None:
    respx.get("http://backend/v1/charges/ch1").mock(return_value=httpx.Response(404))
    assert await PaymentsAPI(api).find_charge("ch1") is None


@respx.mock
async def test_find_charge_returns_model(api: ApiClient) -> None:
    respx.get("http://backend/v1/charges/ch1").mock(
        return_value=httpx.Response(200, json={"user_id": 42})
    )
    charge = await PaymentsAPI(api).find_charge("ch1")
    assert charge is not None
    assert charge.user_id == 42
