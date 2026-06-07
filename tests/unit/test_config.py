"""Unit: парсинг admin-allowlist в AppConfig (csv → set[int])."""

from __future__ import annotations

import pytest

from bot.config import AppConfig

pytestmark = pytest.mark.unit


def test_admin_ids_parsed() -> None:
    cfg = AppConfig(admin_ids="10, 20 ,x,30")
    assert cfg.admin_id_set() == frozenset({10, 20, 30})


def test_empty_admin_ids() -> None:
    assert AppConfig(admin_ids="").admin_id_set() == frozenset()
