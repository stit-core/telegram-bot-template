"""Фасад фичи profile: Provider + dialog (Router) — всё, что видит app.py."""

from __future__ import annotations

from bot.features.profile.dialogs import profile_dialog as dialog
from bot.features.profile.provider import ProfileProvider as Provider

__all__ = ["Provider", "dialog"]
