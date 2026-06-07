"""dialogs.py — Dialog/Window профиля. Presentation как разметка.

Один Dialog ⇄ одна StatesGroup. getter даёт данные, on_success/on_error — реакции (handlers).
Динамические данные — Format("{...}"); статические подписи кнопок — I18NFormat (перевод по ключу).
"""

from __future__ import annotations

from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import TextInput
from aiogram_dialog.widgets.kbd import Back, Cancel, Row, SwitchTo
from aiogram_dialog.widgets.text import Format
from pylibinfra.tgbotkit import I18NFormat

from bot.features.profile import getters, handlers
from bot.features.profile.state import ProfileSG

view_window = Window(
    Format("👤 <b>{name}</b> {badge}\n✉️ {email}\n{status}"),
    Row(
        SwitchTo(I18NFormat("profile-edit-name"), id="edit_name", state=ProfileSG.EDIT_NAME),
        Cancel(I18NFormat("common-back")),
    ),
    state=ProfileSG.VIEW,
    getter=getters.profile_getter,
)

edit_name_window = Window(
    I18NFormat("profile-enter-name"),
    TextInput(
        id="name_input",
        type_factory=str,
        on_success=handlers.on_save_name,
        on_error=handlers.on_name_error,
    ),
    Back(I18NFormat("common-back")),
    state=ProfileSG.EDIT_NAME,
)

profile_dialog = Dialog(view_window, edit_name_window)
