"""Flow-тест payments: /start → меню → окно оффера с ценой и кнопкой «Купить».

Клик «Купить» не делаем (send_invoice требует реального бота) — это покрыто unit-тестами
usecase.confirm и kit-механикой. Здесь проверяем, что оффер с бэкенда дорисовывается в окно.
"""

from __future__ import annotations

import pytest
from aiogram_dialog.test_tools.keyboard import InlineButtonTextLocator
from pylibinfra.testkit.bottest import BotClient, MockMessageManager
from tests._fakes.backend import FakeApiClient
from tests._fakes.harness import build_dp, make_container

from bot.features import payments, start

pytestmark = pytest.mark.dialog


async def test_offer_window_shows_price() -> None:
    mm = MockMessageManager()
    backend = FakeApiClient(
        {
            "id": "premium-30d",
            "title": "Премиум",
            "description": "30 дней",
            "amount": 100,
            "currency": "XTR",
        }
    )
    container = make_container(start.Provider(), payments.Provider(), backend=backend)
    dp = build_dp(container, mm, routers=[start.dialog, payments.dialog], commands=[start.cmd_spec])
    client = BotClient(dp)
    try:
        await client.send("/start")
        menu = mm.one_message()
        mm.reset_history()
        await client.click(menu, InlineButtonTextLocator("start-btn-buy"))
        offer = mm.one_message()
        assert "Премиум" in offer.text
        assert "100" in offer.text
        texts = [b.text for row in offer.reply_markup.inline_keyboard for b in row]
        assert "payments-buy" in texts
    finally:
        await container.close()
