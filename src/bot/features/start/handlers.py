"""handlers.py — точка входа /start (dispatcher-level). Дёргает usecase, ведёт навигацию.

Не диалоговый on_click, а команда диспетчера: dialog_manager приходит из middleware_data
aiogram_dialog (обычный kwarg, не FromDishka); usecase/identity — через @inject + FromDishka.
"""

from __future__ import annotations

from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from dishka import FromDishka
from dishka.integrations.aiogram import inject

from bot.features.start.usecase import StartUsecase
from bot.platform.dialogs import states
from bot.platform.identity import BotIdentity


@inject
async def on_start_command(
    message: Message,
    dialog_manager: DialogManager,
    uc: FromDishka[StartUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    await uc.mark_onboarded(identity.tg_id, message.chat.id)
    # /start ВСЕГДА RESET_STACK: иначе стек диалогов копится до лимита 100 → DialogStackOverflow
    await dialog_manager.start(states.Start.MENU, mode=StartMode.RESET_STACK)
