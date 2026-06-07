"""handlers.py — выбор локали (dialog on_click) + вход /language (dispatcher-level).

on_pick_locale читает локаль из id кнопки (lang_<code>), пишет через usecase и закрывает диалог.
Резолвер i18n подхватит новую локаль из cachekit на следующем рендере.
"""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from bot.features.lang.usecase import LangUsecase
from bot.platform.dialogs import states
from bot.platform.identity import BotIdentity


@inject
async def on_pick_locale(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[LangUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    locale = (button.widget_id or "").removeprefix("lang_")
    await uc.choose(identity.tg_id, locale)
    await callback.answer("✓")
    await manager.done()  # вернуться к вызвавшему диалогу (меню)


async def on_language_command(message: Message, dialog_manager: DialogManager) -> None:
    await dialog_manager.start(states.Lang.CHOOSE, mode=StartMode.NORMAL)
