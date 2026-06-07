"""state.py — FSM-состояния и данные фичи start. PURE (только JSON-примитивы).

StatesGroup живёт централизованно (platform/dialogs/states); тут локальный re-export
для читаемости + pydantic-модель статуса онбординга.
"""

from __future__ import annotations

from pydantic import BaseModel

from bot.platform.dialogs import states

StartSG = states.Start


class OnboardingStatus(BaseModel):
    """Статус онбординга пользователя (для приветствия и cross-feature-чтения)."""

    completed: bool = False
