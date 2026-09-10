"""Unit: intent-id диалогов в тестах уникальны в пределах секунды (фикстура tests/conftest.py).

Без неё два `Stack.push` в одну секунду делят id с вероятностью 1 % — flow-тесты с вложенным
диалогом флейкают `UnknownIntent` на `done()`.
"""

from __future__ import annotations

import pytest
from aiogram.fsm.state import State, StatesGroup
from aiogram_dialog.api.entities import Stack

pytestmark = pytest.mark.unit


class _SG(StatesGroup):
    A = State()
    B = State()


def test_nested_dialog_intents_never_collide() -> None:
    stack = Stack()
    ids: set[str] = set()
    for _ in range(200):
        ids.add(stack.push(_SG.A, None).id)
        stack.pop()  # стек ограничен 100 контекстами — проверяем id, не глубину
    assert len(ids) == 200
    assert all(id_.isalnum() for id_ in ids)
