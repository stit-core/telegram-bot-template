"""views.py — результат/ошибка usecase → данные виджетов и ключ user-текста. PURE.

Единственное место маппинга доменной ошибки в сообщение: error_text отдаёт .ftl-ключ,
рендер — в presentation (bot.shared.i18n.render + I18N_FORMAT_KEY), тексты — в locales/.
"""

from __future__ import annotations

from typing import Any

from bot.features.profile import errors
from bot.pkg.http_client.internal.profile import User


def to_window(user: User) -> dict[str, Any]:
    return {
        "name": user.name,
        "email": user.email,
        "badge": "⭐ premium" if user.premium else "",
    }


def error_text(err: Exception) -> str:
    match err:
        case errors.ProfileNotFound():
            return "profile-error-not-found"
        case errors.ProfileForbidden():
            return "profile-error-forbidden"
        case errors.NameRejected():
            return "profile-error-name-rejected"
        case errors.ProfileConflict():
            return "profile-error-conflict"
        case errors.ProfileError():
            return "profile-error-unavailable"
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
