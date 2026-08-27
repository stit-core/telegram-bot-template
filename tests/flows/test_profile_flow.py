"""Flow-тест profile: /start → меню → просмотр профиля → правка имени → перерисованный профиль.

Мокаем границу бэкенда (FakeApiClient), не транспорт. Локаторы кнопок — по тексту (i18n не
установлен → I18NFormat рендерит ключ).
"""

from __future__ import annotations

import pytest
from aiogram_dialog.test_tools.keyboard import InlineButtonTextLocator
from pylibinfra.testkit.bottest import BotClient, MockMessageManager
from tests._fakes.backend import FakeApiClient
from tests._fakes.harness import build_dp, make_container

from bot.features import profile, start

pytestmark = pytest.mark.dialog


async def test_profile_view_then_rename() -> None:
    mm = MockMessageManager()
    backend = FakeApiClient({"name": "Алиса", "email": "a@example.com", "premium": True})
    container = make_container(start.Provider(), profile.Provider(), backend=backend)
    dp = build_dp(
        container,
        mm,
        routers=[start.dialog, profile.dialog],
        commands=[start.cmd_spec],
    )
    client = BotClient(dp)
    try:
        await client.send("/start")
        menu = mm.one_message()

        mm.reset_history()
        await client.click(menu, InlineButtonTextLocator("start-btn-profile"))
        view = mm.one_message()
        assert "Алиса" in (view.text or "")
        assert "premium" in (view.text or "")

        mm.reset_history()
        await client.click(view, InlineButtonTextLocator("profile-edit-name"))
        mm.one_message()  # окно ввода имени

        mm.reset_history()
        await client.send("Боб")  # TextInput.on_success → rename → switch_to VIEW
        after = mm.one_message()
        assert "Боб" in (after.text or "")
        assert ("PATCH", "/v1/users/1") in backend.calls
    finally:
        await container.close()
