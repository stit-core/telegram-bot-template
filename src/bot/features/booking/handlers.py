"""handlers.py — шаги wizard'а: распаковка ввода → usecase → персист черновика → экран.

Доменных решений здесь нет: валидация/ветвление — usecase (handlers не импортят policy);
handler только мапит результат (address_required) и ошибку (views.error_text) на экран/текст.
Формат-валидация («это число?») — type_factory виджета → on_error.
"""

from __future__ import annotations

import uuid
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import ManagedTextInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.booking import views
from bot.features.booking.errors import BookingError
from bot.features.booking.state import BookingDraft, BookingSG
from bot.features.booking.usecase import BookingUsecase
from bot.platform.identity import BotIdentity
from bot.shared.i18n import render


def _fmt(manager: DialogManager) -> object:
    return manager.middleware_data.get(I18N_FORMAT_KEY)


def _draft(manager: DialogManager) -> BookingDraft:
    return BookingDraft.from_data(manager.dialog_data.get("draft"))


def _save(manager: DialogManager, draft: BookingDraft) -> None:
    manager.dialog_data["draft"] = draft.to_data()


async def on_dialog_start(start_data: Any, manager: DialogManager) -> None:
    # draft_id фиксируем на старте → идемпотентный ключ submit (повтор «Подтвердить» = тот же заказ)
    manager.dialog_data["draft_id"] = uuid.uuid4().hex


@inject
async def on_services_next(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[BookingUsecase],
) -> None:
    widget = manager.find("services")
    selected = list(widget.get_checked()) if widget is not None else []
    _save(manager, uc.set_services(_draft(manager), selected))
    await manager.switch_to(BookingSG.DETAILS)


@inject
async def on_guests_success(
    message: Message,
    widget: ManagedTextInput[int],
    manager: DialogManager,
    value: int,
    *,
    uc: FromDishka[BookingUsecase],
) -> None:
    try:
        step = uc.set_guests(_draft(manager), value)
    except BookingError as exc:
        await message.answer(render(_fmt(manager), views.error_text(exc)))
        return
    _save(manager, step.draft)
    await manager.switch_to(BookingSG.ADDRESS if step.address_required else BookingSG.CONFIRM)


async def on_guests_error(
    message: Message, widget: ManagedTextInput[int], manager: DialogManager, error: ValueError
) -> None:
    await message.answer(render(_fmt(manager), "booking-error-not-number"))


@inject
async def on_address_success(
    message: Message,
    widget: ManagedTextInput[str],
    manager: DialogManager,
    value: str,
    *,
    uc: FromDishka[BookingUsecase],
) -> None:
    try:
        draft = uc.set_address(_draft(manager), value)
    except BookingError as exc:
        await message.answer(render(_fmt(manager), views.error_text(exc)))
        return
    _save(manager, draft)
    await manager.switch_to(BookingSG.CONFIRM)


@inject
async def on_submit(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[BookingUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    draft_id = str(manager.dialog_data.get("draft_id") or uuid.uuid4().hex)
    try:
        result = await uc.submit(identity.backend_user_id, _draft(manager), draft_id)
    except BookingError as exc:
        await callback.answer(render(_fmt(manager), views.error_text(exc)), show_alert=True)
        return
    await callback.answer(
        render(_fmt(manager), "booking-submitted", {"id": result.confirmation_id})
    )
    await manager.done()
