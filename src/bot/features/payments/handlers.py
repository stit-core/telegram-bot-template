"""handlers.py — dialog-level (on_buy/on_subscribe) и dispatcher-level апдейты.

dialog on_click шлёт инвойс/подписочный линк; dispatcher-level (pre_checkout, successful_payment,
refunded_payment, /refund) регистрируются через CommandBundle (__init__.py). pre_checkout —
answer_pre_checkout (timeout-guard, fail-closed); successful_payment/refunded_payment —
at-least-once через Charge/RefundGuard (commit после, release на сбое); /refund — refund_charge.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from aiogram import Bot
from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram import inject as inject_dispatcher
from dishka.integrations.aiogram_dialog import inject as inject_dialog
from pylibinfra.tgbotkit import (
    ChargeGuard,
    RefundGuard,
    answer_pre_checkout,
    build_invoice,
    build_subscription_link,
    refund_charge,
)
from pylibinfra.tgbotkit.i18n import I18N_FORMAT_KEY

from bot.features.payments import errors, views
from bot.features.payments.state import DEMO_OFFER_ID
from bot.features.payments.usecase import PaymentsUsecase
from bot.platform.identity import BotIdentity
from bot.shared.i18n import render


@inject_dialog
async def on_buy(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[PaymentsUsecase],
    bot: FromDishka[Bot],
) -> None:
    try:
        order = await uc.offer(DEMO_OFFER_ID)
    except errors.PaymentError as exc:
        fmt = manager.middleware_data.get(I18N_FORMAT_KEY)
        await callback.answer(render(fmt, views.error_text(exc)), show_alert=True)
        return
    invoice = build_invoice(
        title=order.title,
        description=order.description,
        payload=order.order_id,  # связь с pre_checkout/successful_payment
        amount=order.price.amount_minor,
        currency=order.price.currency,
    )
    if callback.message is not None:
        await bot.send_invoice(callback.message.chat.id, **invoice)
    await callback.answer()


@inject_dialog
async def on_subscribe(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[PaymentsUsecase],
    bot: FromDishka[Bot],
) -> None:
    try:
        order = await uc.offer(DEMO_OFFER_ID)
    except errors.PaymentError as exc:
        fmt = manager.middleware_data.get(I18N_FORMAT_KEY)
        await callback.answer(render(fmt, views.error_text(exc)), show_alert=True)
        return
    # рекуррентные списания приходят тем же payload → fulfill идемпотентен по charge_id
    link = await build_subscription_link(
        bot,
        title=order.title,
        description=order.description,
        payload=order.order_id,
        price=order.price,
    )
    if callback.message is not None:
        fmt = manager.middleware_data.get(I18N_FORMAT_KEY)
        text = fmt("payments-subscription-link", {"link": link}) if fmt else link
        await callback.message.answer(text)
    await callback.answer()


@inject_dispatcher
async def on_pre_checkout(
    query: PreCheckoutQuery, *, uc: FromDishka[PaymentsUsecase], bot: FromDishka[Bot]
) -> None:
    async def decide(q: PreCheckoutQuery) -> bool:
        # цену/валюту сверяем на бэкенде (uc.confirm), НЕ доверяя q.total_amount как истине
        return await uc.confirm(q.invoice_payload, q.total_amount, q.currency)

    await answer_pre_checkout(bot, query, decide, deadline=9.0)


@inject_dispatcher
async def on_successful_payment(
    message: Message,
    *,
    uc: FromDishka[PaymentsUsecase],
    client: FromDishka[aioredis.Redis],
) -> None:
    sp = message.successful_payment
    if sp is None:
        return
    charge_id = sp.telegram_payment_charge_id
    # at-least-once: платёж может прийти дважды → reserve до выдачи, commit после
    guard = ChargeGuard(client)
    if not await guard.reserve(charge_id):
        return  # дубликат или выдача уже в процессе
    try:
        await uc.complete(sp.invoice_payload, charge_id)
    except Exception:
        await guard.release(charge_id)  # сбой выдачи → ключ снят, повтор апдейта сможет выдать
        raise
    await guard.commit(charge_id)


@inject_dispatcher
async def on_refunded_payment(
    message: Message,
    *,
    uc: FromDishka[PaymentsUsecase],
    client: FromDishka[aioredis.Redis],
) -> None:
    rp = message.refunded_payment
    if rp is None:
        return
    charge_id = rp.telegram_payment_charge_id
    # at-least-once (как successful_payment): откат выдачи ровно один раз → RefundGuard
    guard = RefundGuard(client)
    if not await guard.reserve(charge_id):
        return
    try:
        await uc.reverse(rp.invoice_payload, charge_id)
    except Exception:
        await guard.release(charge_id)
        raise
    await guard.commit(charge_id)


@inject_dispatcher
async def on_refund_command(
    message: Message,
    command: CommandObject,
    *,
    uc: FromDishka[PaymentsUsecase],
    bot: FromDishka[Bot],
    identity: FromDishka[BotIdentity],
) -> None:
    # admin-ops: ответы plain-текстом (не user-facing UX), gate по role из identity
    if identity.role != "admin":
        await message.answer("Команда доступна только администратору.")
        return
    charge_id = (command.args or "").strip()
    if not charge_id:
        await message.answer("Использование: /refund <telegram_payment_charge_id>")
        return
    user_id = await uc.payer_of(charge_id)
    if user_id is None:
        await message.answer(f"Плательщик для charge {charge_id} не найден.")
        return
    ok = await refund_charge(bot, user_id, charge_id)
    await message.answer("Возврат оформлен." if ok else "Возврат отклонён Telegram.")
