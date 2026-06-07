"""Smoke: пакет бота импортируется и поверхность tgbotkit доступна (extra [tgbotkit])."""

import pytest

pytestmark = pytest.mark.unit


def test_bot_package_imports() -> None:
    import bot

    assert bot.__doc__


def test_tgbotkit_surface_available() -> None:
    from pylibinfra.tgbotkit import BotProvider, BotRunner, CommandSpec

    assert BotProvider is not None
    assert BotRunner is not None
    assert CommandSpec is not None
