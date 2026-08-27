"""getters.py — данные окна оффера (дёргает usecase). @inject из aiogram_dialog."""

from __future__ import annotations

from typing import Any

from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.payments import errors, views
from bot.features.payments.state import DEMO_OFFER_ID
from bot.features.payments.usecase import PaymentsUsecase
from bot.shared.i18n import render


@inject
async def offer_getter(uc: FromDishka[PaymentsUsecase], **kwargs: Any) -> dict[str, Any]:
    try:
        order = await uc.offer(DEMO_OFFER_ID)
    except errors.PaymentError as exc:
        description = render(kwargs.get(I18N_FORMAT_KEY), views.error_text(exc))
        return {"title": "—", "description": description, "amount": 0}
    return views.to_offer(order)
