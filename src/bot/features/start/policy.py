"""policy.py — чистые решения фичи start. PURE: на вход — уже загруженный статус.

Тут нет I/O — только выбор приветствия по статусу онбординга. Легко юнит-тестировать.
"""

from __future__ import annotations

from bot.features.start.state import OnboardingStatus


def greeting_key(status: OnboardingStatus) -> str:
    """Ключ перевода приветствия: новый пользователь vs вернувшийся."""
    return "start-welcome-back" if status.completed else "start-welcome-new"
