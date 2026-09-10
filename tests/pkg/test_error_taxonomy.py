"""Транспорт-граница: негативный канон таксономии + ретраи/гейт мутаций.

Единственное место, где поведение retry/breaker/классификации проверяется через respx
(фичи мокают границу бэкенда фейком, не транспорт — rule tests-pipeline).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient, Client, Config

from bot.pkg.http_client.errors import (
    AuthError,
    ContractError,
    InvalidRequestError,
    RateLimitedError,
    UnavailableError,
)
from bot.pkg.http_client.internal.profile import ProfileAPI

pytestmark = pytest.mark.pkg

_USER = {"name": "Алиса", "email": "a@x.io", "premium": False}


@contextlib.asynccontextmanager
async def _api(max_retries: int = 2) -> AsyncIterator[ApiClient]:
    # backoff между попытками — миллисекунда: тест не спит по-настоящему
    cfg = Config.model_validate(
        {
            "HTTPCLIENT_BASE_URL": "http://backend",
            "HTTPCLIENT_MAX_RETRIES": max_retries,
            "HTTPCLIENT_RETRY_WAIT": 0.001,
            "HTTPCLIENT_RETRY_MAX_WAIT": 0.001,
        }
    )
    api = ApiClient(Client(cfg))
    try:
        yield api
    finally:
        await api.aclose()


@respx.mock
async def test_transport_error_maps_to_unavailable() -> None:
    respx.get("http://backend/v1/users/u1").mock(side_effect=httpx.ConnectError("boom"))
    async with _api(max_retries=0) as api:
        with pytest.raises(UnavailableError):
            await ProfileAPI(api).get_user("u1")


@respx.mock
async def test_401_maps_to_auth_error_with_status() -> None:
    respx.get("http://backend/v1/users/u1").mock(return_value=httpx.Response(401))
    async with _api() as api:
        with pytest.raises(AuthError) as err:
            await ProfileAPI(api).get_user("u1")
    assert err.value.status_code == 401


@respx.mock
async def test_422_maps_to_invalid_request() -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(422, json={"detail": "bad"})
    )
    async with _api() as api:
        with pytest.raises(InvalidRequestError) as err:
            await ProfileAPI(api).get_user("u1")
    assert "bad" in err.value.body_snippet


@respx.mock
async def test_429_maps_to_rate_limited_with_retry_after() -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3"})
    )
    async with _api() as api:
        with pytest.raises(RateLimitedError) as err:
            await ProfileAPI(api).get_user("u1")
    # transient: ловится и общим catch по UnavailableError
    assert isinstance(err.value, UnavailableError)
    assert err.value.retry_after == 3.0


@respx.mock
async def test_get_retries_5xx_then_succeeds() -> None:
    route = respx.get("http://backend/v1/users/u1")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=_USER)]
    async with _api(max_retries=2) as api:
        user = await ProfileAPI(api).get_user("u1")
    assert user.name == "Алиса"
    assert route.call_count == 2


@respx.mock
async def test_mutation_with_key_retries_5xx() -> None:
    # PATCH с Idempotency-Key (канон ProfileAPI) получает полный retry-бюджет
    route = respx.patch("http://backend/v1/users/u1")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=_USER)]
    async with _api(max_retries=2) as api:
        user = await ProfileAPI(api).rename_user("u1", "Алиса")
    assert user.name == "Алиса"
    assert route.call_count == 2


@respx.mock
async def test_mutation_without_key_is_single_attempt() -> None:
    # POST без Idempotency-Key не ретраится: потерянный ответ + слепой повтор = дубль
    route = respx.post("http://backend/v1/bookings").mock(return_value=httpx.Response(503))
    async with _api(max_retries=3) as api:
        with pytest.raises(UnavailableError):
            await api.post("/v1/bookings", json={})
    assert route.call_count == 1


@respx.mock
async def test_non_json_2xx_is_contract_error() -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, text="<html>WAF</html>")
    )
    async with _api() as api:
        with pytest.raises(ContractError):
            await ProfileAPI(api).get_user("u1")
