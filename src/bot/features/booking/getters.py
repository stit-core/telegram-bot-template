"""getters.py — данные окон wizard'а. Читают черновик из dialog_data, не из бэкенда.

Лейблы опций/итог переводятся i18n-функцией из middleware_data (как в start.getters); с
выключенным i18n (тесты) рендерится ключ.
"""

from __future__ import annotations

from typing import Any

from aiogram_dialog import DialogManager
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.booking.state import MAX_GUESTS, SERVICE_KEYS, BookingDraft


async def services_getter(**kwargs: Any) -> dict[str, Any]:
    fmt = kwargs.get(I18N_FORMAT_KEY)
    services = [(k, fmt(f"booking-svc-{k}", {}) if fmt else k) for k in SERVICE_KEYS]
    return {"services": services}


async def details_getter(**kwargs: Any) -> dict[str, Any]:
    return {"max": MAX_GUESTS}


async def confirm_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    draft = BookingDraft.from_data(dialog_manager.dialog_data.get("draft"))
    fmt = kwargs.get(I18N_FORMAT_KEY)
    labels = [fmt(f"booking-svc-{k}", {}) if fmt else k for k in draft.services]
    return {
        "services": ", ".join(labels) or "—",
        "guests": draft.guests,
        "address": draft.address or "—",
    }
