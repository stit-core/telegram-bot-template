"""Smoke composition root: контейнер собирается, Dispatcher резолвится (вся проводка
middleware/i18n/commands/routers/error-handlers), setup_dialogs не ловит коллизий StatesGroup.

Офлайн: NATS/Telegram не дёргаем (BotRunner не резолвим — он бы поднял соединения). redis —
ленивый (не подключается на сборке Dispatcher). telemetry — stdout-only.
"""

from __future__ import annotations

import pytest
from aiogram import Dispatcher
from aiogram_dialog import setup_dialogs
from opentelemetry.trace import Tracer

from bot import app
from bot.features import booking, lang, payments, profile, start

pytestmark = pytest.mark.dialog


async def test_container_assembles_and_dialogs_collision_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_STDOUT_ONLY", "true")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "bot-test")

    # dialog'и — module-level синглтоны; отвяжем от dispatcher'ов прошлых тестов
    for dialog in (start.dialog, profile.dialog, payments.dialog, lang.dialog, booking.dialog):
        dialog._parent_router = None  # type: ignore[attr-defined]

    container = app.build_container()
    try:
        await container.get(Tracer)  # триггерит telemetry.init
        dp = await container.get(Dispatcher)
        assert isinstance(dp, Dispatcher)
        setup_dialogs(dp)  # smoke: коллизии StatesGroup/состояний всплывут здесь
    finally:
        await container.close()
