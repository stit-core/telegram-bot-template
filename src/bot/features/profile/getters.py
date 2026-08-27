"""getters.py — данные в окно профиля. Дёргает usecase (не gateway/httpx). @inject aiogram_dialog.

ОБЯЗАТЕЛЕН **kwargs (геттер зовут со всем middleware_data) и дефолты всех ключей Format.
Доменную ошибку ловим здесь и показываем мягко (status), чтобы окно не падало в recovery.
"""

from __future__ import annotations

from typing import Any

from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.profile import errors, views
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity
from bot.shared.i18n import render


@inject
async def profile_getter(
    uc: FromDishka[ProfileUsecase],
    identity: FromDishka[BotIdentity],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        view = await uc.view(identity)
    except errors.ProfileError as exc:
        status = render(kwargs.get(I18N_FORMAT_KEY), views.error_text(exc))
        return {"name": "—", "email": "", "badge": "", "status": status}
    data = views.to_window(view)
    data["status"] = ""
    return data
