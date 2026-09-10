"""Общие фикстуры тестов бота: детерминированные intent-id aiogram_dialog.

aiogram_dialog собирает intent-id из `int(time.time())` и `random(0..99)`: два диалога,
стартовавшие в одну секунду (flow-тест: `/start` → кнопка `Start` вложенной фичи), в 1 %
случаев получают один id, и `done()` вложенного диалога стирает контекст родителя →
`UnknownIntent` на возврате в меню. Счётчик на тест снимает коллизию целиком.
"""

from __future__ import annotations

import itertools

import pytest
from aiogram_dialog.api.entities import stack as dialog_stack


@pytest.fixture(autouse=True)
def _unique_intent_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = itertools.count(1)
    monkeypatch.setattr(dialog_stack, "new_int_id", lambda: next(counter))
