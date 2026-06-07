"""identity — Update → BotIdentity (REQUEST-scope провайдер)."""

from bot.platform.identity.identity import BotIdentity
from bot.platform.identity.provider import IdentityProvider

__all__ = ["BotIdentity", "IdentityProvider"]
