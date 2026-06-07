"""dialogs.py — корневой диалог-меню. Presentation как разметка.

LaunchMode.ROOT: единственный «домашний» диалог (стек не растёт от повторного входа).
Кнопки ведут в другие фичи через их StatesGroup (из platform/dialogs/states — НЕ импорт
другой фичи). Dialog является Router → отдаётся в RouterBundle (см. __init__.py).
"""

from __future__ import annotations

from aiogram_dialog import Dialog, LaunchMode, Window
from aiogram_dialog.widgets.kbd import Column
from aiogram_dialog.widgets.text import Format

from bot.features.start import getters
from bot.platform.dialogs import states
from bot.platform.dialogs.common import open_dialog

menu_window = Window(
    Format("{greeting}"),
    Column(
        open_dialog("start-btn-profile", states.Profile.VIEW, "to_profile"),
        open_dialog("start-btn-buy", states.Payments.OFFER, "to_buy"),
        open_dialog("start-btn-lang", states.Lang.CHOOSE, "to_lang"),
    ),
    state=states.Start.MENU,
    getter=getters.menu_getter,
)

start_dialog = Dialog(menu_window, launch_mode=LaunchMode.ROOT)
