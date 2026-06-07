"""getters.py — данные окна меню. Дёргает usecase (не gateway). @inject из aiogram_dialog.

Геттер зовут со всем middleware_data (**kwargs) — оттуда берём пользователя и i18n-функцию
формата. Приветствие выбирает policy (по статусу онбординга) и рендерим его уже здесь, чтобы
окно осталось чистой разметкой Format("{greeting}").
"""

from __future__ import annotations

from typing import Any

from aiogram.types import User
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.start import policy
from bot.features.start.usecase import StartUsecase
from bot.platform.identity import BotIdentity


@inject
async def menu_getter(
    uc: FromDishka[StartUsecase],
    identity: FromDishka[BotIdentity],
    **kwargs: Any,
) -> dict[str, Any]:
    user: User | None = kwargs.get("event_from_user")
    username = user.full_name if user is not None else ""
    status = await uc.status(identity.tg_id)

    key = policy.greeting_key(status)
    fmt = kwargs.get(I18N_FORMAT_KEY)
    greeting = fmt(key, {"username": username}) if fmt is not None else key
    return {"greeting": greeting, "username": username}
