"""ЕДИНЫЙ каталог StatesGroup всех фич (разрыв циклов импорта между диалогами).

Эволюция состояний — только через deprecation (не удалять/переименовывать живые State:
сломает кнопки у пользователей в открытых диалогах → UnknownState). См. rule state-lifecycle.
"""

from aiogram.fsm.state import State, StatesGroup


class Start(StatesGroup):
    MENU = State()


class Profile(StatesGroup):
    VIEW = State()
    EDIT_NAME = State()


class Payments(StatesGroup):
    OFFER = State()


class Lang(StatesGroup):
    CHOOSE = State()


class Booking(StatesGroup):
    SERVICES = State()
    DETAILS = State()
    ADDRESS = State()
    CONFIRM = State()
