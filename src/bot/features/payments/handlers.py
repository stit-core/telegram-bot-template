"""handlers.py — два сорта обработчиков:

- on_buy: dialog-level on_click — собирает XTR-инвойс (build_invoice) и шлёт send_invoice.
- on_pre_checkout / on_successful_payment: dispatcher-level апдейты (НЕ dialog-callback) —
  регистрируются через CommandBundle (__init__.py). pre_checkout отвечаем через
  answer_pre_checkout (timeout-guard к дедлайну Telegram 10с, fail-closed); successful_payment
  дедупим guard_charge по telegram_payment_charge_id (at-least-once). Связь invoice↔платёж —
  через invoice_payload (= order_id).
"""

from __future__ import annotations

import redis.asyncio as aioredis
from aiogram import Bot
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram import inject as inject_dispatcher
from dishka.integrations.aiogram_dialog import inject as inject_dialog
from pylibinfra.tgbotkit import answer_pre_checkout, build_invoice, guard_charge

from bot.features.payments.state import DEMO_OFFER_ID
from bot.features.payments.usecase import PaymentsUsecase


@inject_dialog
async def on_buy(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
    *,
    uc: FromDishka[PaymentsUsecase],
    bot: FromDishka[Bot],
) -> None:
    order = await uc.offer(DEMO_OFFER_ID)
    invoice = build_invoice(
        title=order.title,
        description=order.description,
        payload=order.order_id,  # связь с pre_checkout/successful_payment
        amount=order.amount,
        currency=order.currency,
    )
    if callback.message is not None:
        await bot.send_invoice(callback.message.chat.id, **invoice)
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
    # at-least-once: один платёж может прийти дважды → дедуп по charge_id
    if await guard_charge(client, sp.telegram_payment_charge_id):
        return
    await uc.complete(sp.invoice_payload, sp.telegram_payment_charge_id)
