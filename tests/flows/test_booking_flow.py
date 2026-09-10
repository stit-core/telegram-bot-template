"""Flow-тест booking-wizard: Multiselect → валидируемый ввод → условный шаг адреса → submit.

Проверяем обе ветки policy.needs_address: с «доставкой» появляется шаг адреса, без неё — сразу
подтверждение. Локаторы — по callback_data (Multiselect) и тексту-ключу (i18n off). Накопленный
в dialog_data черновик доезжает до бэкенда (POST /v1/bookings). JsonMemoryStorage заодно ловит
несериализуемое в dialog_data.
"""

from __future__ import annotations

import pytest
from aiogram.types import Message
from aiogram_dialog.test_tools.keyboard import InlineButtonDataLocator, InlineButtonTextLocator
from dishka import AsyncContainer
from pylibinfra.testkit.bottest import BotClient, MockMessageManager
from tests._fakes.backend import FakeApiClient
from tests._fakes.harness import build_dp, make_container

from bot.features import booking, start

pytestmark = pytest.mark.dialog


def _client(backend: FakeApiClient) -> tuple[BotClient, MockMessageManager, AsyncContainer]:
    mm = MockMessageManager()
    container = make_container(start.Provider(), booking.Provider(), backend=backend)
    dp = build_dp(container, mm, routers=[start.dialog, booking.dialog], commands=[start.cmd_spec])
    return BotClient(dp), mm, container


async def _open_services(client: BotClient, mm: MockMessageManager) -> Message:
    await client.send("/start")
    menu = mm.last_message()
    mm.reset_history()
    await client.click(menu, InlineButtonTextLocator("start-btn-book"))
    services = mm.last_message()
    assert "booking-services-title" in (services.text or "")
    mm.reset_history()
    return services


async def test_wizard_with_delivery_asks_address_then_submits() -> None:
    backend = FakeApiClient({"confirmation_id": "BK-7"})
    client, mm, container = _client(backend)
    try:
        services = await _open_services(client, mm)
        # callback_data Multiselect-кнопки = "<intent_id>\x1dservices:<key>" → матчим суффикс
        await client.click(services, InlineButtonDataLocator(r".*services:delivery"))
        services = mm.last_message()  # перерисовка: доставка отмечена
        mm.reset_history()

        await client.click(services, InlineButtonTextLocator("booking-next"))
        details = mm.last_message()
        assert "booking-guests-prompt" in (details.text or "")
        mm.reset_history()

        await client.send("3")  # валидное число → доставка выбрана → шаг адреса
        address = mm.last_message()
        assert "booking-address-prompt" in (address.text or "")
        mm.reset_history()

        await client.send("Тверская улица 7")
        confirm = mm.last_message()
        assert "booking-confirm" in (confirm.text or "")
        mm.reset_history()

        await client.click(confirm, InlineButtonTextLocator("booking-submit"))
        assert ("POST", "/v1/bookings") in backend.calls
    finally:
        await container.close()


async def test_wizard_without_delivery_skips_address() -> None:
    backend = FakeApiClient({"confirmation_id": "BK-8"})
    client, mm, container = _client(backend)
    try:
        services = await _open_services(client, mm)
        # ничего не выбираем — сразу «Далее»
        await client.click(services, InlineButtonTextLocator("booking-next"))
        details = mm.last_message()
        assert "booking-guests-prompt" in (details.text or "")
        mm.reset_history()

        await client.send("2")  # доставки нет → шаг адреса ПРОПУСКАЕТСЯ → сразу подтверждение
        confirm = mm.last_message()
        assert "booking-confirm" in (confirm.text or "")
        assert "booking-address-prompt" not in (confirm.text or "")
        mm.reset_history()

        await client.click(confirm, InlineButtonTextLocator("booking-submit"))
        assert ("POST", "/v1/bookings") in backend.calls
    finally:
        await container.close()
