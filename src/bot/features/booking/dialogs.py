"""dialogs.py — wizard заказа: 4 окна с условным шагом адреса. Presentation как разметка.

SERVICES (Multiselect опций) → DETAILS (валидируемое число гостей) → [ADDRESS, если выбрана
доставка] → CONFIRM (итог + submit). Шаг адреса решает usecase (GuestsStep.address_required).
Навигация назад — SwitchTo на явные состояния (а не Back), чтобы не упереться в пропущенное окно.
"""

from __future__ import annotations

import operator

from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import TextInput
from aiogram_dialog.widgets.kbd import Button, Column, Multiselect, SwitchTo
from aiogram_dialog.widgets.text import Format
from pylibinfra.tgbotkit import I18NFormat

from bot.features.booking import getters, handlers
from bot.features.booking.state import BookingSG
from bot.platform.dialogs.common import back_to_menu

services_window = Window(
    I18NFormat("booking-services-title"),
    Column(
        Multiselect(
            Format("✅ {item[1]}"),
            Format("▫️ {item[1]}"),
            id="services",
            item_id_getter=operator.itemgetter(0),
            items="services",
            type_factory=str,
        ),
    ),
    Button(I18NFormat("booking-next"), id="svc_next", on_click=handlers.on_services_next),
    back_to_menu("booking_cancel"),
    state=BookingSG.SERVICES,
    getter=getters.services_getter,
)

details_window = Window(
    I18NFormat("booking-guests-prompt"),
    TextInput(
        id="guests",
        type_factory=int,
        on_success=handlers.on_guests_success,
        on_error=handlers.on_guests_error,
    ),
    SwitchTo(I18NFormat("common-back"), id="d_back", state=BookingSG.SERVICES),
    state=BookingSG.DETAILS,
    getter=getters.details_getter,
)

address_window = Window(
    I18NFormat("booking-address-prompt"),
    TextInput(id="address", type_factory=str, on_success=handlers.on_address_success),
    SwitchTo(I18NFormat("common-back"), id="a_back", state=BookingSG.DETAILS),
    state=BookingSG.ADDRESS,
)

confirm_window = Window(
    I18NFormat("booking-confirm"),
    Button(I18NFormat("booking-submit"), id="submit", on_click=handlers.on_submit),
    SwitchTo(I18NFormat("common-back"), id="c_back", state=BookingSG.SERVICES),
    state=BookingSG.CONFIRM,
    getter=getters.confirm_getter,
)

booking_dialog = Dialog(
    services_window,
    details_window,
    address_window,
    confirm_window,
    on_start=handlers.on_dialog_start,
)
