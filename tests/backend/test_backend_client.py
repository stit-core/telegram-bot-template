"""Backend-тест: BackendClient мапит HTTP-статусы в транспорт-ошибки (respx мокает httpx).

Проверяем границу platform/backend: 2xx→dict, 404→NotFound, 409→Conflict, 5xx→Unavailable,
Idempotency-Key прокидывается. httpclient.Client (retry/breaker/X-Request-ID) — реальный.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from pylibinfra.httpclient import Client, Config
from pylibinfra.logkit import nop

from bot.platform.backend import BackendClient, BackendConflict, BackendNotFound, BackendUnavailable

pytestmark = pytest.mark.unit


def _client(max_retries: int = 0) -> BackendClient:
    cfg = Config(base_url="http://backend", max_retries=max_retries)
    http = httpx.AsyncClient(base_url="http://backend")
    return BackendClient(Client(cfg, http), nop())


@respx.mock
async def test_get_returns_json() -> None:
    respx.get("http://backend/v1/x").mock(return_value=httpx.Response(200, json={"a": 1}))
    assert await _client().get("/v1/x") == {"a": 1}


@respx.mock
async def test_2xx_non_json_body_maps_unavailable() -> None:
    # прокси/WAF отдал HTML на 2xx — доменная ошибка, а не JSONDecodeError наверх
    respx.get("http://backend/v1/x").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>oops</html>"
        )
    )
    with pytest.raises(BackendUnavailable):
        await _client().get("/v1/x")


@respx.mock
async def test_2xx_non_object_json_maps_unavailable() -> None:
    # валидный JSON, но не объект (список) — контракт dict нарушен
    respx.get("http://backend/v1/x").mock(return_value=httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(BackendUnavailable):
        await _client().get("/v1/x")


@respx.mock
async def test_get_404_maps_not_found() -> None:
    respx.get("http://backend/v1/x").mock(return_value=httpx.Response(404))
    with pytest.raises(BackendNotFound):
        await _client().get("/v1/x")


@respx.mock
async def test_409_maps_conflict() -> None:
    respx.post("http://backend/v1/x").mock(return_value=httpx.Response(409))
    with pytest.raises(BackendConflict):
        await _client().post("/v1/x", json={})


@respx.mock
async def test_5xx_maps_unavailable() -> None:
    respx.get("http://backend/v1/x").mock(return_value=httpx.Response(503))
    with pytest.raises(BackendUnavailable):
        await _client().get("/v1/x")


@respx.mock
async def test_patch_sends_idempotency_key() -> None:
    route = respx.patch("http://backend/v1/x").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await _client().patch("/v1/x", json={"n": "v"}, idempotency_key="k1")
    assert route.calls.last.request.headers["Idempotency-Key"] == "k1"
