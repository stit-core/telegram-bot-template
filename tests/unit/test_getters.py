"""Unit: getters профиля и оффера — доменная ошибка ловится в getter → мягкий плейсхолдер,
окно не падает в recovery.

Геттеры обёрнуты dishka @inject (aiogram_dialog): зависимости резолвятся из request-контейнера,
переданного kwarg'ом `dishka_container` (как kit зовёт getter со всем middleware_data).
"""

from __future__ import annotations

import pytest
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from pylibinfra.httpclient import UnavailableError
from pylibinfra.logkit import nop

from bot.features.payments.getters import offer_getter
from bot.features.payments.usecase import PaymentsUsecase
from bot.features.profile import errors as prof_errors
from bot.features.profile.getters import profile_getter
from bot.features.profile.usecase import ProfileUsecase
from bot.pkg.http_client.internal.payments import Offer
from bot.pkg.http_client.internal.profile import User
from bot.platform.identity import BotIdentity

pytestmark = pytest.mark.unit

_IDENTITY = BotIdentity(tg_id=1, backend_user_id="1", role="user")


class _PayGateway:
    def __init__(self, offer: Offer | None = None, error: Exception | None = None) -> None:
        self._offer = offer
        self._error = error

    async def get_offer(self, offer_id: str) -> Offer:
        if self._error is not None:
            raise self._error
        assert self._offer is not None
        return self._offer


class _ProfGateway:
    def __init__(self, user: User | None = None, error: Exception | None = None) -> None:
        self._user = user
        self._error = error

    async def get_user(self, user_id: str) -> User:
        if self._error is not None:
            raise self._error
        assert self._user is not None
        return self._user

    async def rename_user(self, user_id: str, name: str) -> User:
        assert self._user is not None
        return self._user


class _Onboarding:
    async def is_onboarded(self, tg_id: int) -> bool:
        return True


class _PayDeps(Provider):
    scope = Scope.APP

    def __init__(self, gateway: _PayGateway) -> None:
        super().__init__()
        self._gateway = gateway

    @provide
    def usecase(self) -> PaymentsUsecase:
        return PaymentsUsecase(self._gateway, nop())  # type: ignore[arg-type]


class _ProfDeps(Provider):
    scope = Scope.APP

    def __init__(self, gateway: _ProfGateway) -> None:
        super().__init__()
        self._gateway = gateway

    @provide
    def usecase(self) -> ProfileUsecase:
        return ProfileUsecase(self._gateway, _Onboarding(), nop())  # type: ignore[arg-type]

    @provide
    def identity(self) -> BotIdentity:
        return _IDENTITY


def _pay_container(gateway: _PayGateway) -> AsyncContainer:
    return make_async_container(_PayDeps(gateway))


def _prof_container(gateway: _ProfGateway) -> AsyncContainer:
    return make_async_container(_ProfDeps(gateway))


async def test_offer_getter_returns_offer_data() -> None:
    offer = Offer(id="o1", title="Премиум", description="30д", amount=100)
    container = _pay_container(_PayGateway(offer=offer))
    async with container() as rc:
        data = await offer_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["title"] == "Премиум"
    assert data["amount"] == 100
    await container.close()


async def test_offer_getter_soft_placeholder_on_error() -> None:
    # бэкенд оффера недоступен — окно показывает заглушку, не падает в recovery
    container = _pay_container(_PayGateway(error=UnavailableError("down")))
    async with container() as rc:
        data = await offer_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["amount"] == 0
    assert "недоступен" in data["description"]
    await container.close()


async def test_profile_getter_returns_window_data() -> None:
    user = User(name="Алиса", email="a@x.io", premium=True)
    container = _prof_container(_ProfGateway(user=user))
    async with container() as rc:
        data = await profile_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["name"] == "Алиса"
    assert data["status"] == ""
    await container.close()


async def test_profile_getter_soft_status_on_domain_error() -> None:
    # ProfileError (бэкенд недоступен) → мягкий status, плейсхолдеры, окно живо
    container = _prof_container(_ProfGateway(error=prof_errors.ProfileError("down")))
    async with container() as rc:
        data = await profile_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["name"] == "—"
    assert data["status"]  # непустой текст ошибки в окне
    await container.close()
