"""BookingAPI: payload сабмита + Idempotency-Key от draft_id и содержимого."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.internal.booking import BookingAPI

pytestmark = pytest.mark.pkg


@respx.mock
async def test_submit_booking_sends_payload_and_idempotency_key(api: ApiClient) -> None:
    route = respx.post("http://backend/v1/bookings").mock(
        return_value=httpx.Response(200, json={"confirmation_id": "c-1"})
    )
    result = await BookingAPI(api).submit_booking(
        draft_id="draft-42",
        user_id="u1",
        services=["cleaning"],
        guests=2,
        address="Тверская, 1",
    )
    assert result.confirmation_id == "c-1"
    req = route.calls.last.request
    digest = hashlib.sha256("draft-42\x1fu1\x1fcleaning\x1f2\x1fТверская, 1".encode()).hexdigest()
    assert req.headers["Idempotency-Key"] == f"booking-submit:{digest}"
    assert json.loads(req.content) == {
        "user_id": "u1",
        "services": ["cleaning"],
        "guests": 2,
        "address": "Тверская, 1",
    }


@respx.mock
async def test_submit_booking_key_changes_with_content(api: ApiClient) -> None:
    # изменённый черновик того же визарда → новый ключ (не 409 о переиспользовании),
    # тот же черновик → тот же ключ (повтор «Подтвердить» не создаёт дубль)
    route = respx.post("http://backend/v1/bookings").mock(
        return_value=httpx.Response(200, json={"confirmation_id": "c-1"})
    )
    api_client = BookingAPI(api)
    await api_client.submit_booking(
        draft_id="d1", user_id="u1", services=[], guests=2, address=None
    )
    await api_client.submit_booking(
        draft_id="d1", user_id="u1", services=[], guests=3, address=None
    )
    await api_client.submit_booking(
        draft_id="d1", user_id="u1", services=[], guests=2, address=None
    )
    keys = [c.request.headers["Idempotency-Key"] for c in route.calls]
    assert keys[0] != keys[1]
    assert keys[0] == keys[2]
