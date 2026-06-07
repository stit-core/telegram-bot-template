"""Общие виджеты диалогов (i18n-aware). Фабрики, а не разделяемые инстансы — у каждого
окна свой объект кнопки (id уникален в пределах окна).
"""

from __future__ import annotations

from aiogram.fsm.state import State
from aiogram_dialog.widgets.kbd import Cancel, Start
from pylibinfra.tgbotkit import I18NFormat


def back_to_menu(button_id: str = "to_menu") -> Cancel:
    """Cancel-кнопка «назад» (закрывает текущий диалог, возвращает к вызвавшему)."""
    return Cancel(I18NFormat("common-back"), id=button_id)


def open_dialog(text_key: str, state: State, button_id: str) -> Start:
    """Start-кнопка перехода в другой диалог (по StatesGroup-состоянию)."""
    return Start(I18NFormat(text_key), id=button_id, state=state)
