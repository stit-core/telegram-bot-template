"""Unit: ProfileUsecase — anti-corruption: typed-ошибки HTTP-границы → sentinel'ы фичи
(включая catch-all ApiError), policy-гейты (доступ/валидация) до похода в порт.
"""

from __future__ import annotations

import pytest
from pylibinfra.logkit import nop

from bot.features.profile import errors
from bot.features.profile.usecase import ProfileUsecase
from bot.pkg.http_client.errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    UnavailableError,
)
from bot.pkg.http_client.internal.profile import User
from bot.platform.identity import BotIdentity

pytestmark = pytest.mark.unit

_IDENTITY = BotIdentity(tg_id=1, backend_user_id="1", role="user")


class _Gateway:
    def __init__(self, user: User | None = None, error: Exception | None = None) -> None:
        self._user = user
        self._error = error
        self.renames: list[str] = []

    async def get_user(self, user_id: str) -> User:
        if self._error is not None:
            raise self._error
        assert self._user is not None
        return self._user

    async def rename_user(self, user_id: str, name: str) -> User:
        if self._error is not None:
            raise self._error
        self.renames.append(name)
        assert self._user is not None
        return self._user


class _Onboarding:
    async def is_onboarded(self, tg_id: int) -> bool:
        return True


def _uc(gateway: _Gateway) -> ProfileUsecase:
    return ProfileUsecase(gateway, _Onboarding(), nop())


async def test_view_returns_user() -> None:
    user = User(name="Алиса", email="a@x.io", premium=False)
    assert await _uc(_Gateway(user=user)).view(_IDENTITY) is user


async def test_view_banned_role_is_forbidden_without_io() -> None:
    gw = _Gateway(error=AssertionError("порт не должен дёргаться"))
    banned = BotIdentity(tg_id=1, backend_user_id="1", role="banned")
    with pytest.raises(errors.ProfileForbidden):
        await _uc(gw).view(banned)


async def test_view_maps_not_found() -> None:
    with pytest.raises(errors.ProfileNotFound):
        await _uc(_Gateway(error=NotFoundError("404"))).view(_IDENTITY)


async def test_view_maps_unavailable_to_sentinel() -> None:
    with pytest.raises(errors.ProfileUnavailable):
        await _uc(_Gateway(error=UnavailableError("503"))).view(_IDENTITY)


async def test_view_catches_full_taxonomy() -> None:
    # catch-all по ApiError: 401 и прочие не-transient классы не протекают в recovery
    with pytest.raises(errors.ProfileUnavailable):
        await _uc(_Gateway(error=AuthError("401", status_code=401))).view(_IDENTITY)


async def test_rename_strips_and_passes_name() -> None:
    gw = _Gateway(user=User(name="Боб", email="a@x.io", premium=False))
    await _uc(gw).rename(_IDENTITY, "  Боб  ")
    assert gw.renames == ["Боб"]


async def test_rename_rejects_invalid_name_without_io() -> None:
    gw = _Gateway(error=AssertionError("порт не должен дёргаться"))
    with pytest.raises(errors.NameRejected):
        await _uc(gw).rename(_IDENTITY, "   ")


async def test_rename_maps_conflict_to_sentinel() -> None:
    # rename на 409 — тело успеха не приходит, исход неоднозначен → ProfileConflict
    with pytest.raises(errors.ProfileConflict):
        await _uc(_Gateway(error=ConflictError("409"))).rename(_IDENTITY, "Боб")


async def test_rename_maps_not_found() -> None:
    with pytest.raises(errors.ProfileNotFound):
        await _uc(_Gateway(error=NotFoundError("404"))).rename(_IDENTITY, "Боб")
