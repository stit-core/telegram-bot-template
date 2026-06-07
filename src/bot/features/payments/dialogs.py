"""dialogs.py — окно оффера с кнопкой «Купить» (шлёт XTR-инвойс через handlers.on_buy)."""

from __future__ import annotations

from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import Button
from aiogram_dialog.widgets.text import Format
from pylibinfra.tgbotkit import I18NFormat

from bot.features.payments import getters, handlers
from bot.features.payments.state import PaymentsSG
from bot.platform.dialogs.common import back_to_menu

offer_window = Window(
    Format("🛒 <b>{title}</b>\n{description}\n\n💎 {amount} ⭐"),
    Button(I18NFormat("payments-buy"), id="buy", on_click=handlers.on_buy),
    back_to_menu("pay_back"),
    state=PaymentsSG.OFFER,
    getter=getters.offer_getter,
)

buy_dialog = Dialog(offer_window)
