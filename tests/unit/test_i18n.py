"""Unit: каталоги locales/*.ftl парсятся, ключи резолвятся (FluentTranslator из kit)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pylibinfra.tgbotkit import FluentTranslator

import bot.config as config

pytestmark = pytest.mark.unit

_LOCALES = str(Path(config.__file__).parent / "locales")
_RESOURCES = ["common.ftl", "start.ftl", "profile.ftl", "payments.ftl", "lang.ftl"]


def test_ru_keys_resolve() -> None:
    fmt = FluentTranslator("ru", _LOCALES, _RESOURCES).for_locale("ru")
    assert fmt("start-btn-profile", None) == "👤 Профиль"
    assert "Вася" in fmt("start-welcome-new", {"username": "Вася"})
    assert fmt("common-back", None) == "⬅️ Назад"


def test_en_locale_renders() -> None:
    fmt = FluentTranslator("ru", _LOCALES, _RESOURCES).for_locale("en")
    assert fmt("start-btn-profile", None) == "👤 Profile"
