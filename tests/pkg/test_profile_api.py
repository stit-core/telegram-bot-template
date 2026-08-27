"""ProfileAPI: пути/payload/Idempotency-Key + валидация контракта (ломаный → ContractError)."""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.errors import ContractError, NotFoundError
from bot.pkg.http_client.internal.profile import ProfileAPI

pytestmark = pytest.mark.pkg


@respx.mock
async def test_get_user_returns_model(api: ApiClient) -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"name": "Алиса", "email": "a@x.io", "premium": True})
    )
    user = await ProfileAPI(api).get_user("u1")
    assert user.name == "Алиса"
    assert user.premium is True


@respx.mock
async def test_get_user_404_raises_kit_not_found(api: ApiClient) -> None:
    respx.get("http://backend/v1/users/ghost").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError):
        await ProfileAPI(api).get_user("ghost")


@respx.mock
async def test_get_user_broken_contract_raises_contract_error(api: ApiClient) -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    with pytest.raises(ContractError, match="does not match User"):
        await ProfileAPI(api).get_user("u1")


@respx.mock
async def test_get_user_extra_field_is_contract_drift(api: ApiClient) -> None:
    # extra="forbid": переименованное/лишнее поле бэкенда ловится на границе, не молчит
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(
            200,
            json={"name": "Алиса", "email": "a@x.io", "premium": True, "nickname": "al"},
        )
    )
    with pytest.raises(ContractError):
        await ProfileAPI(api).get_user("u1")


@respx.mock
async def test_rename_user_sends_ascii_idempotency_key(api: ApiClient) -> None:
    # кириллица в Idempotency-Key падала UnicodeEncodeError при latin-1-кодировании
    # заголовка ДО запроса — канон ключа: <operation>:<sha256(частей через \x1f)>
    route = respx.patch("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"name": "Пётр", "email": "a@x.io", "premium": False})
    )
    user = await ProfileAPI(api).rename_user("u1", "Пётр")
    assert user.name == "Пётр"
    key = route.calls.last.request.headers["Idempotency-Key"]
    key.encode("latin-1")  # HTTP-заголовок: не должно бросать
    digest = hashlib.sha256("u1\x1fПётр".encode()).hexdigest()
    assert key == f"profile-rename:{digest}"
