"""handlers.py — шаги wizard'а: накопление черновика в dialog_data + условная навигация.

Каждый шаг читает черновик (BookingDraft.from_data), дописывает свой кусок, сохраняет обратно
(to_data — JSON-примитивы). Multiselect читаем через find().get_checked(); валидация ввода —
policy (Decision); ветвление шага адреса — policy.needs_address. Финал — submit черновика.
Сообщения-подсказки plain-текстом (как profile.handlers), подписи окон — I18NFormat.
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

from bot.features.booking import policy, views
from bot.features.booking.errors import BookingError
from bot.features.booking.state import BookingDraft, BookingSG
from bot.features.booking.usecase import BookingUsecase
from bot.platform.identity import BotIdentity


async def on_dialog_start(start_data: Any, manager: DialogManager) -> None:
    # draft_id фиксируем на старте → идемпотентный ключ submit (повтор «Подтвердить» = тот же заказ)
    manager.dialog_data["draft_id"] = uuid.uuid4().hex


async def on_services_next(callback: CallbackQuery, button: Button, manager: DialogManager) -> None:
    widget = manager.find("services")
    selected = list(widget.get_checked()) if widget is not None else []
    draft = BookingDraft.from_data(manager.dialog_data.get("draft"))
    draft.services = selected
    manager.dialog_data["draft"] = draft.to_data()
    await manager.switch_to(BookingSG.DETAILS)


async def on_guests_success(
    message: Message, widget: ManagedTextInput[int], manager: DialogManager, value: int
) -> None:
    if not policy.validate_guests(value).allowed:
        await message.answer("Введите число гостей от 1 до 10.")
        return
    draft = BookingDraft.from_data(manager.dialog_data.get("draft"))
    draft.guests = value
    manager.dialog_data["draft"] = draft.to_data()
    nxt = BookingSG.ADDRESS if policy.needs_address(draft.services) else BookingSG.CONFIRM
    await manager.switch_to(nxt)


async def on_guests_error(
    message: Message, widget: ManagedTextInput[int], manager: DialogManager, error: ValueError
) -> None:
    await message.answer("Это не число. Введите количество гостей цифрами.")


async def on_address_success(
    message: Message, widget: ManagedTextInput[str], manager: DialogManager, value: str
) -> None:
    if not policy.validate_address(value).allowed:
        await message.answer("Адрес слишком короткий, уточните.")
        return
    draft = BookingDraft.from_data(manager.dialog_data.get("draft"))
    draft.address = value
    manager.dialog_data["draft"] = draft.to_data()
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
    draft = BookingDraft.from_data(manager.dialog_data.get("draft"))
    idem = str(manager.dialog_data.get("draft_id") or uuid.uuid4().hex)
    try:
        result = await uc.submit(identity.backend_user_id, draft, idem)
    except BookingError as exc:
        await callback.answer(views.error_text(exc), show_alert=True)
        return
    await callback.answer(f"Заказ оформлен! Номер: {result.confirmation_id}")
    await manager.done()
