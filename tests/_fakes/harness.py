"""Тест-харнес: сборка dishka-контейнера с фейками инфры + Dispatcher с привязкой диалогов.

Повторяет проводку рантайма kit'а в миниатюре: AiogramProvider (REQUEST-контекст), фейк
Cache/Logger/AppConfig + pkg-клиенты поверх FakeApiClient, IdentityProvider + переданные
фиче-провайдеры; затем bind_dialogs (setup_dishka + setup_dialogs с MockMessageManager).
"""

from __future__ import annotations

from collections.abc import Iterable

from aiogram import Dispatcher
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from dishka.integrations.aiogram import AiogramProvider
from pylibinfra.cachekit import Cache
from pylibinfra.logkit import Logger, nop
from pylibinfra.testkit.bottest import JsonMemoryStorage, MockMessageManager, bind_dialogs
from pylibinfra.tgbotkit import CommandSpec

from bot.config import AppConfig
from bot.pkg.http_client.internal.booking import BookingAPI
from bot.pkg.http_client.internal.payments import PaymentsAPI
from bot.pkg.http_client.internal.profile import ProfileAPI
from bot.platform.identity import IdentityProvider
from tests._fakes.backend import FakeApiClient
from tests._fakes.cache import FakeCache


class FakesProvider(Provider):
    scope = Scope.APP

    def __init__(self, cache: Cache, app: AppConfig, backend: FakeApiClient) -> None:
        super().__init__()
        self._cache = cache
        self._app = app
        self._backend = backend

    @provide
    def cache(self) -> Cache:
        return self._cache

    @provide
    def logger(self) -> Logger:
        return nop()

    @provide
    def app_config(self) -> AppConfig:
        return self._app

    # pkg-клиенты поверх фейкового транспорта: фичи получают реальные API-классы,
    # I/O подменён in-memory заглушкой (мокаем границу бэкенда, не httpx)
    @provide
    def profile_api(self) -> ProfileAPI:
        return ProfileAPI(self._backend)  # type: ignore[arg-type]

    @provide
    def booking_api(self) -> BookingAPI:
        return BookingAPI(self._backend)  # type: ignore[arg-type]

    @provide
    def payments_api(self) -> PaymentsAPI:
        return PaymentsAPI(self._backend)  # type: ignore[arg-type]


def make_container(
    *feature_providers: Provider,
    cache: Cache | None = None,
    app: AppConfig | None = None,
    backend: FakeApiClient | None = None,
) -> AsyncContainer:
    return make_async_container(
        FakesProvider(
            cache or FakeCache(),
            app or AppConfig(),
            backend or FakeApiClient(),
        ),
        AiogramProvider(),
        IdentityProvider(),
        *feature_providers,
    )


def build_dp(
    container: AsyncContainer,
    message_manager: MockMessageManager,
    *,
    routers: Iterable[object] = (),
    commands: Iterable[CommandSpec] = (),
) -> Dispatcher:
    dp = Dispatcher(storage=JsonMemoryStorage())
    for spec in commands:
        dp.observers[spec.observer].register(spec.handler, *spec.filters)
    for router in routers:
        # dialog'и — module-level синглтоны; в прошлом тесте уже привязаны к другому
        # Dispatcher. Детачим, чтобы переиспользовать в этом тесте (тесты идут последовательно).
        router._parent_router = None  # type: ignore[attr-defined]
        dp.include_router(router)
    bind_dialogs(dp, container, message_manager=message_manager)
    return dp
