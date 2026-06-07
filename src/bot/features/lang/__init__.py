"""Фасад фичи lang: Provider, dialog, cmd_spec (/language)."""

from __future__ import annotations

from aiogram.filters import Command
from pylibinfra.tgbotkit import CommandSpec

from bot.features.lang.dialogs import lang_dialog as dialog
from bot.features.lang.handlers import on_language_command
from bot.features.lang.provider import LangProvider as Provider

cmd_spec = CommandSpec("message", on_language_command, (Command("language"),))

__all__ = ["Provider", "cmd_spec", "dialog"]
