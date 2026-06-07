"""Backend-тест: HttpPaymentsGateway маппинг транспорт→домен (respx мокает httpx).

Ключевой инвариант — fulfill идемпотентен: 409 (BackendConflict) = «выдача уже применена»,
повтор не должен всплывать паникой, gateway трактует его как успех.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from pylibinfra.httpclient import Client, Config
from pylibinfra.logkit import nop

from bot.features.payments import errors
from bot.features.payments.gateway import HttpPaymentsGateway
from bot.platform.backend import BackendClient

pytestmark = pytest.mark.unit


def _gateway() -> HttpPaymentsGateway:
    cfg = Config(base_url="http://backend", max_retries=0)
    http = httpx.AsyncClient(base_url="http://backend")
    return HttpPaymentsGateway(BackendClient(Client(cfg, http), nop()))


@respx.mock
async def test_fulfill_treats_409_as_success() -> None:
    respx.post("http://backend/v1/orders/o1/fulfill").mock(return_value=httpx.Response(409))
    # идемпотентный повтор: 409 = уже выдано бэкендом, без исключения
    await _gateway().fulfill("o1", "charge-1")


@respx.mock
async def test_fulfill_sends_charge_id_as_idempotency_key() -> None:
    route = respx.post("http://backend/v1/orders/o1/fulfill").mock(
        return_value=httpx.Response(200, json={})
    )
    await _gateway().fulfill("o1", "charge-1")
    assert route.calls.last.request.headers["Idempotency-Key"] == "charge-1"


@respx.mock
async def test_fulfill_maps_unavailable_to_payment_error() -> None:
    # 503 → BackendUnavailable → доменная PaymentError (повтор апдейта разрулит)
    respx.post("http://backend/v1/orders/o1/fulfill").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.PaymentError):
        await _gateway().fulfill("o1", "charge-1")


@respx.mock
async def test_get_offer_returns_order() -> None:
    respx.get("http://backend/v1/offers/premium-30d").mock(
        return_value=httpx.Response(
            200, json={"id": "premium-30d", "title": "Премиум", "amount": 100}
        )
    )
    order = await _gateway().get_offer("premium-30d")
    assert order.order_id == "premium-30d"
    assert order.amount == 100
    assert order.currency == "XTR"  # дефолт, когда бэкенд не прислал валюту


@respx.mock
async def test_get_offer_maps_404_to_order_not_found() -> None:
    respx.get("http://backend/v1/offers/ghost").mock(return_value=httpx.Response(404))
    with pytest.raises(errors.OrderNotFound):
        await _gateway().get_offer("ghost")


@respx.mock
async def test_get_offer_maps_unavailable_to_payment_error() -> None:
    respx.get("http://backend/v1/offers/premium-30d").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.PaymentError):
        await _gateway().get_offer("premium-30d")
