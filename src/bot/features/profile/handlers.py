"""handlers.py — реакции на ввод/клики (usecase + навигация). @inject из aiogram_dialog.

Данные берём из аргументов виджета (value), не из getter. Навигация — manager.switch_to.
Ошибки usecase → текст через views.error_text, показываем без падения окна.
"""

from __future__ import annotations

from aiogram.types import Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import ManagedTextInput
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from bot.features.profile import errors, views
from bot.features.profile.state import ProfileSG
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity


@inject
async def on_save_name(
    message: Message,
    widget: ManagedTextInput[str],
    manager: DialogManager,
    value: str,
    *,
    uc: FromDishka[ProfileUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    try:
        await uc.rename(identity, value)
    except errors.ProfileError as exc:
        await message.answer(views.error_text(exc))
        return
    await manager.switch_to(ProfileSG.VIEW)  # успех → назад к просмотру (перерисует getter)


async def on_name_error(
    message: Message,
    widget: ManagedTextInput[str],
    manager: DialogManager,
    error: ValueError,
) -> None:
    # сюда попадаем, если type_factory кинул ValueError (для str не бывает; задел под typed-input)
    await message.answer("Некорректный ввод, попробуйте ещё раз.")
