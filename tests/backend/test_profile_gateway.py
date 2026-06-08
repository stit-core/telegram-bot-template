"""Backend-тест: HttpProfileGateway маппинг транспорт→домен (respx мокает httpx).

Единственная точка маппинга BackendNotFound/Conflict/Unavailable → sentinel'ы profile.errors.
update_name шлёт Idempotency-Key (защита от двойных кликов/ретраев httpclient).
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx
from pylibinfra.httpclient import Client, Config
from pylibinfra.logkit import nop

from bot.features.profile import errors
from bot.features.profile.gateway import HttpProfileGateway
from bot.platform.backend import BackendClient

pytestmark = pytest.mark.unit


def _gateway() -> HttpProfileGateway:
    cfg = Config(base_url="http://backend", max_retries=0)
    http = httpx.AsyncClient(base_url="http://backend")
    return HttpProfileGateway(BackendClient(Client(cfg, http), nop()))


@respx.mock
async def test_load_profile_returns_view() -> None:
    respx.get("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"name": "Алиса", "email": "a@x.io", "premium": True})
    )
    view = await _gateway().load_profile("u1")
    assert view.name == "Алиса"
    assert view.is_premium is True


@respx.mock
async def test_load_profile_maps_404_to_not_found() -> None:
    respx.get("http://backend/v1/users/ghost").mock(return_value=httpx.Response(404))
    with pytest.raises(errors.ProfileNotFound):
        await _gateway().load_profile("ghost")


@respx.mock
async def test_load_profile_maps_unavailable_to_profile_error() -> None:
    respx.get("http://backend/v1/users/u1").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.ProfileError):
        await _gateway().load_profile("u1")


@respx.mock
async def test_update_name_returns_updated_view_with_idempotency_key() -> None:
    route = respx.patch("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"name": "Bob", "email": "a@x.io", "premium": False})
    )
    view = await _gateway().update_name("u1", "Bob")
    assert view.name == "Bob"
    expected = f"profile-rename:u1:{hashlib.sha256(b'Bob').hexdigest()}"
    assert route.calls.last.request.headers["Idempotency-Key"] == expected


@respx.mock
async def test_update_name_non_ascii_name_keeps_idempotency_key_ascii() -> None:
    # кириллическое имя в Idempotency-Key падало UnicodeEncodeError при latin-1-кодировании
    # заголовка (httpx) ДО запроса — мимо всех except. Ключ обязан быть ASCII-safe.
    route = respx.patch("http://backend/v1/users/u1").mock(
        return_value=httpx.Response(200, json={"name": "Пётр", "email": "a@x.io", "premium": False})
    )
    view = await _gateway().update_name("u1", "Пётр")
    assert view.name == "Пётр"
    key = route.calls.last.request.headers["Idempotency-Key"]
    key.encode("latin-1")  # HTTP-заголовок: не должно бросать
    assert key.startswith("profile-rename:u1:")


@respx.mock
async def test_update_name_maps_404_to_not_found() -> None:
    respx.patch("http://backend/v1/users/ghost").mock(return_value=httpx.Response(404))
    with pytest.raises(errors.ProfileNotFound):
        await _gateway().update_name("ghost", "Bob")


@respx.mock
async def test_update_name_maps_409_to_profile_error() -> None:
    # rename на 409 — тело успеха не приходит, исход неоднозначен → доменная ProfileError
    respx.patch("http://backend/v1/users/u1").mock(return_value=httpx.Response(409))
    with pytest.raises(errors.ProfileError):
        await _gateway().update_name("u1", "Bob")


@respx.mock
async def test_update_name_maps_unavailable_to_profile_error() -> None:
    respx.patch("http://backend/v1/users/u1").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.ProfileError):
        await _gateway().update_name("u1", "Bob")
