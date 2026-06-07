"""Фасад фичи start: Provider, dialog (Router), cmd_spec (/start) — всё, что видит app.py."""

from __future__ import annotations

from aiogram.filters import CommandStart
from pylibinfra.tgbotkit import CommandSpec

from bot.features.start.dialogs import start_dialog as dialog
from bot.features.start.handlers import on_start_command
from bot.features.start.provider import StartProvider as Provider

# dispatcher-level вход: observer="message" + фильтр CommandStart()
cmd_spec = CommandSpec("message", on_start_command, (CommandStart(),))

__all__ = ["Provider", "cmd_spec", "dialog"]
