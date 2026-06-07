"""dialogs.py — окно выбора языка. Кнопки статичны (id=lang_<code>), на клик — handlers."""

from __future__ import annotations

from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import Button, Column
from aiogram_dialog.widgets.text import Const
from pylibinfra.tgbotkit import I18NFormat

from bot.features.lang import handlers
from bot.features.lang.state import LangSG
from bot.platform.dialogs.common import back_to_menu

choose_window = Window(
    I18NFormat("lang-choose"),
    Column(
        Button(Const("🇷🇺 Русский"), id="lang_ru", on_click=handlers.on_pick_locale),
        Button(Const("🇬🇧 English"), id="lang_en", on_click=handlers.on_pick_locale),
    ),
    back_to_menu("lang_back"),
    state=LangSG.CHOOSE,
)

lang_dialog = Dialog(choose_window)
