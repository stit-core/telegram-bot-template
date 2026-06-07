"""Unit: AppErrorUX — устаревшие кнопки (UnknownIntent/State) гасят «часики» с подсказкой
/start, прочее — нейтральное сообщение. Плюс роутинг stale-исключений через register_error_handlers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Dispatcher
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
from pylibinfra.tgbotkit import register_error_handlers

from bot.platform.dialogs.errors import _OOPS, _STALE, AppErrorUX

pytestmark = pytest.mark.unit


class FakeCallback:
    def __init__(self) -> None:
        self.answered: str | None = None

    async def answer(self, text: str, show_alert: bool = False) -> None:
        self.answered = text


def _event(callback: Any = None, message: Any = None, exception: Any = None) -> Any:
    return SimpleNamespace(
        update=SimpleNamespace(callback_query=callback, message=message),
        exception=exception,
    )


async def test_unknown_intent_answers_stale() -> None:
    cb = FakeCallback()
    await AppErrorUX().on_unknown_intent(_event(callback=cb), bot=None)  # type: ignore[arg-type]
    assert cb.answered == _STALE


async def test_unknown_state_answers_stale() -> None:
    cb = FakeCallback()
    await AppErrorUX().on_unknown_state(_event(callback=cb), bot=None)  # type: ignore[arg-type]
    assert cb.answered == _STALE


async def test_unhandled_answers_oops_on_callback() -> None:
    cb = FakeCallback()
    await AppErrorUX().on_unhandled(_event(callback=cb), bot=None)  # type: ignore[arg-type]
    assert cb.answered == _OOPS


async def test_unhandled_answers_oops_on_message() -> None:
    answered: list[str] = []

    async def answer(text: str) -> None:
        answered.append(text)

    msg = SimpleNamespace(answer=answer)
    await AppErrorUX().on_unhandled(_event(message=msg), bot=None)  # type: ignore[arg-type]
    assert answered == [_OOPS]


async def test_unhandled_silent_without_callback_or_message() -> None:
    # ни callback, ни message (напр. edited_message/poll) — нечем ответить, не падаем
    await AppErrorUX().on_unhandled(_event(), bot=None)  # type: ignore[arg-type]


async def test_unknown_intent_silent_without_callback() -> None:
    # stale пришёл не как callback (нет «часиков» гасить) — _answer_callback тихо выходит
    msg = SimpleNamespace(answer=lambda *a, **k: None)
    await AppErrorUX().on_unknown_intent(_event(message=msg), bot=None)  # type: ignore[arg-type]


async def test_register_routes_unknown_intent_to_app_ux() -> None:
    dp = Dispatcher()
    register_error_handlers(dp, AppErrorUX())
    cb = FakeCallback()
    event = _event(callback=cb, exception=UnknownIntent("stale"))
    await dp.errors.trigger(event, bot=None)  # type: ignore[arg-type]
    assert cb.answered == _STALE


async def test_register_routes_unknown_state_to_app_ux() -> None:
    dp = Dispatcher()
    register_error_handlers(dp, AppErrorUX())
    cb = FakeCallback()
    event = _event(callback=cb, exception=UnknownState("gone"))
    await dp.errors.trigger(event, bot=None)  # type: ignore[arg-type]
    assert cb.answered == _STALE
