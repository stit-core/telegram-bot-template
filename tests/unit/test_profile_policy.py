"""Unit: чистые правила policy профиля (без I/O)."""

from __future__ import annotations

import pytest

from bot.features.profile import policy

pytestmark = pytest.mark.unit


def test_banned_cannot_view() -> None:
    assert policy.can_view_profile("banned").allowed is False


def test_user_can_view() -> None:
    assert policy.can_view_profile("user").allowed is True


def test_empty_name_rejected() -> None:
    d = policy.validate_name("   ")
    assert d.allowed is False
    assert d.reason


def test_too_long_name_rejected() -> None:
    assert policy.validate_name("x" * (policy.MAX_NAME_LEN + 1)).allowed is False


def test_valid_name_allowed() -> None:
    assert policy.validate_name("  Алиса  ").allowed is True
