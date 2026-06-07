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
