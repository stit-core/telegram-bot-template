"""Unit: выбор приветствия по статусу онбординга (pure)."""

from __future__ import annotations

import pytest

from bot.features.start import policy
from bot.features.start.state import OnboardingStatus

pytestmark = pytest.mark.unit


def test_new_user_greeting() -> None:
    assert policy.greeting_key(OnboardingStatus(completed=False)) == "start-welcome-new"


def test_returning_user_greeting() -> None:
    assert policy.greeting_key(OnboardingStatus(completed=True)) == "start-welcome-back"
