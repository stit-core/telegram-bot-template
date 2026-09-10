"""IdentityProvider — Update → BotIdentity (REQUEST-scope).

Юзера берём из middleware_data aiogram (ключ event_from_user), который dishka кладёт в
REQUEST-контекст как AiogramMiddlewareData (см. AiogramProvider в app.py — он ОБЯЗАН быть
в контейнере). backend_user_id — из identity-link в cachekit (link:tg:<id>), пишется при
онбординге (start.usecase); фолбэк до линковки — сам tg_id. role — из admin-allowlist.
"""

from __future__ import annotations

from typing import Any

from dishka import Provider, Scope, provide
from dishka.integrations.aiogram import AiogramMiddlewareData
from pylibinfra.cachekit import Cache

from bot.config import AppConfig
from bot.platform.identity.identity import BotIdentity
from bot.platform.links import backend_link_key


class IdentityProvider(Provider):
    scope = Scope.REQUEST

    @provide
    async def identity(
        self, data: AiogramMiddlewareData, cache: Cache, app: AppConfig
    ) -> BotIdentity:
        user: Any = data.get("event_from_user")
        if user is None:
            # апдейты без from_user (часть service-сообщений) — синтетический «нулевой» юзер
            return BotIdentity(tg_id=0, backend_user_id="", role="user")
        tg_id = int(user.id)
        backend_user_id = await self._resolve_backend_id(cache, tg_id)
        role = "admin" if tg_id in app.admin_ids else "user"
        return BotIdentity(tg_id=tg_id, backend_user_id=backend_user_id, role=role)

    async def _resolve_backend_id(self, cache: Cache, tg_id: int) -> str:
        raw = await cache.get(backend_link_key(tg_id))
        return raw.decode() if raw is not None else str(tg_id)
