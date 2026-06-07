"""Flow-тест онбординга: /start поднимает корневое меню (BotClient прогоняет весь пайплайн)."""

from __future__ import annotations

import pytest
from pylibinfra.testkit.bottest import BotClient, MockMessageManager
from tests._fakes.harness import build_dp, make_container

from bot.features import start

pytestmark = pytest.mark.dialog


async def test_start_shows_root_menu() -> None:
    mm = MockMessageManager()
    container = make_container(start.Provider())
    dp = build_dp(container, mm, routers=[start.dialog], commands=[start.cmd_spec])
    client = BotClient(dp)
    try:
        await client.send("/start")
        msg = mm.one_message()
        # i18n не установлен в тест-контейнере → I18NFormat/greeting рендерят сам ключ;
        # mark_onboarded отработал до рендера → приветствие «с возвращением».
        assert msg.text == "start-welcome-back"
        texts = [b.text for row in msg.reply_markup.inline_keyboard for b in row]
        assert "start-btn-profile" in texts
        assert "start-btn-buy" in texts
        assert "start-btn-lang" in texts
    finally:
        await container.close()
