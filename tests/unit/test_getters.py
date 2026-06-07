"""Unit: getters профиля и оффера — доменная ошибка ловится в getter → мягкий плейсхолдер,
окно не падает в recovery.

Геттеры обёрнуты dishka @inject (aiogram_dialog): зависимости резолвятся из request-контейнера,
переданного kwarg'ом `dishka_container` (как kit зовёт getter со всем middleware_data).
"""

from __future__ import annotations

import pytest
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from pylibinfra.logkit import nop

from bot.features.payments import errors as pay_errors
from bot.features.payments.dto import Order
from bot.features.payments.getters import offer_getter
from bot.features.payments.usecase import PaymentsUsecase
from bot.features.profile import errors as prof_errors
from bot.features.profile.dto import ProfileView
from bot.features.profile.getters import profile_getter
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity

pytestmark = pytest.mark.unit

_IDENTITY = BotIdentity(tg_id=1, backend_user_id="1", role="user")


class _PayGateway:
    def __init__(self, order: Order | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error

    async def get_offer(self, offer_id: str) -> Order:
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def fulfill(self, order_id: str, charge_id: str) -> None:
        pass


class _ProfGateway:
    def __init__(self, view: ProfileView | None = None, error: Exception | None = None) -> None:
        self._view = view
        self._error = error

    async def load_profile(self, backend_user_id: str) -> ProfileView:
        if self._error is not None:
            raise self._error
        assert self._view is not None
        return self._view

    async def update_name(self, backend_user_id: str, name: str) -> ProfileView:
        assert self._view is not None
        return self._view


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
    order = Order(order_id="o1", title="Премиум", description="30д", amount=100, currency="XTR")
    container = _pay_container(_PayGateway(order=order))
    async with container() as rc:
        data = await offer_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["title"] == "Премиум"
    assert data["amount"] == 100
    await container.close()


async def test_offer_getter_soft_placeholder_on_error() -> None:
    # бэкенд оффера недоступен — окно показывает заглушку, не падает в recovery
    container = _pay_container(_PayGateway(error=pay_errors.PaymentError("down")))
    async with container() as rc:
        data = await offer_getter(dishka_container=rc)  # type: ignore[call-arg]
    assert data["amount"] == 0
    assert "недоступен" in data["description"]
    await container.close()


async def test_profile_getter_returns_window_data() -> None:
    view = ProfileView(name="Алиса", email="a@x.io", is_premium=True)
    container = _prof_container(_ProfGateway(view=view))
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
