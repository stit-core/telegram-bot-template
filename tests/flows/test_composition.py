"""Smoke composition root: контейнер собирается, Dispatcher резолвится (вся проводка
middleware/i18n/commands/routers/error-handlers), setup_dialogs не ловит коллизий StatesGroup,
все pkg-API и usecase'ы фич резолвятся (fail-fast: незаполненный бэкенд падает тут, не на юзере).

Офлайн: NATS/Telegram не дёргаем (BotRunner не резолвим — он бы поднял соединения). redis —
ленивый (не подключается на сборке Dispatcher).
"""

from __future__ import annotations

import pytest
from aiogram import Dispatcher
from aiogram_dialog import setup_dialogs
from pylibinfra.httpclient import ApiClients

from bot import app
from bot.features import booking, lang, payments, profile, start
from bot.features.booking.usecase import BookingUsecase
from bot.features.lang.usecase import LangUsecase
from bot.features.payments.usecase import PaymentsUsecase
from bot.features.profile.usecase import ProfileUsecase
from bot.features.start.usecase import StartUsecase
from bot.pkg.http_client import CORE_BACKEND
from bot.pkg.http_client.internal.booking import BookingAPI
from bot.pkg.http_client.internal.payments import PaymentsAPI
from bot.pkg.http_client.internal.profile import ProfileAPI

pytestmark = pytest.mark.dialog


async def test_container_assembles_and_dialogs_collision_free() -> None:
    # dialog'и — module-level синглтоны; отвяжем от dispatcher'ов прошлых тестов
    for dialog in (start.dialog, profile.dialog, payments.dialog, lang.dialog, booking.dialog):
        dialog._parent_router = None

    container = app.build_container()
    try:
        dp = await container.get(Dispatcher)
        assert isinstance(dp, Dispatcher)
        setup_dialogs(dp)  # smoke: коллизии StatesGroup/состояний всплывут здесь
    finally:
        await container.close()


async def test_backend_ports_resolve_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # BackendConfig требует base_url — контейнер с пустым HTTPCLIENT_BASE_URL падает
    # на резолве ApiClients, а не на первом апдейте юзера в проде
    monkeypatch.setenv("HTTPCLIENT_BASE_URL", "http://core.test")
    container = app.build_container()
    try:
        apis = await container.get(ApiClients)
        assert CORE_BACKEND in apis
        for api_cls in (ProfileAPI, BookingAPI, PaymentsAPI):
            assert await container.get(api_cls) is not None
        async with container() as rc:
            usecases = (ProfileUsecase, BookingUsecase, PaymentsUsecase, StartUsecase, LangUsecase)
            for uc_cls in usecases:
                assert await rc.get(uc_cls) is not None
    finally:
        await container.close()


async def test_missing_backend_base_url_fails_on_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTPCLIENT_BASE_URL", raising=False)
    container = app.build_container()
    try:
        with pytest.raises(Exception, match="base_url"):
            await container.get(ApiClients)
    finally:
        await container.close()
