"""Фасад фичи payments: Provider, dialog, command_specs (dispatcher-level pre_checkout/on_paid).

command_specs регистрируются kit'ом через CommandBundle: pre_checkout_query и сообщение с
successful_payment — это апдейты ДИСПЕТЧЕРА, не dialog-callback.
"""

from __future__ import annotations

from aiogram import F
from pylibinfra.tgbotkit import CommandSpec

from bot.features.payments.dialogs import buy_dialog as dialog
from bot.features.payments.handlers import on_pre_checkout, on_successful_payment
from bot.features.payments.provider import PaymentsProvider as Provider

command_specs = (
    CommandSpec("pre_checkout_query", on_pre_checkout),
    CommandSpec("message", on_successful_payment, (F.successful_payment,)),
)

__all__ = ["Provider", "command_specs", "dialog"]
