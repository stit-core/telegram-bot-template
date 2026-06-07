"""views.py — результат/ошибка usecase → данные виджетов и user-текст. PURE.

Единственное место, где доменная ошибка превращается в человеческое сообщение
(аналог delivery/http/view.go: FromEntity + mapErr).
"""

from __future__ import annotations

from typing import Any

from bot.features.profile import errors
from bot.features.profile.dto import ProfileView


def to_window(view: ProfileView) -> dict[str, Any]:
    return {
        "name": view.name,
        "email": view.email,
        "badge": "⭐ premium" if view.is_premium else "",
    }


def error_text(err: Exception) -> str:
    match err:
        case errors.ProfileNotFound():
            return "Профиль не найден. Попробуйте /start."
        case errors.ProfileForbidden() | errors.NameRejected():
            return str(err) or "Действие недоступно."
        case errors.ProfileError():
            return "Сервис временно недоступен, попробуйте позже."
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
