"""BookingAPI: payload сабмита + Idempotency-Key черновика."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.internal.booking import BookingAPI

pytestmark = pytest.mark.unit


@respx.mock
async def test_submit_booking_sends_payload_and_idempotency_key(api: ApiClient) -> None:
    route = respx.post("http://backend/v1/bookings").mock(
        return_value=httpx.Response(200, json={"confirmation_id": "c-1"})
    )
    result = await BookingAPI(api).submit_booking(
        user_id="u1",
        services=["cleaning"],
        guests=2,
        address="Тверская, 1",
        idempotency_key="draft-42",
    )
    assert result.confirmation_id == "c-1"
    req = route.calls.last.request
    assert req.headers["Idempotency-Key"] == "draft-42"
    assert json.loads(req.content) == {
        "user_id": "u1",
        "services": ["cleaning"],
        "guests": 2,
        "address": "Тверская, 1",
    }
