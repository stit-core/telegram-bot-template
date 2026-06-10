"""store.py — реализация OnboardingStore поверх cachekit. Единственный I/O фичи start.

Структурно удовлетворяет ports.OnboardingStore (mypy проверит), связывается в provider.py.
Боту не нужен Postgres: флаг онбординга и link tg→chat живут в Redis (cachekit).
"""

from __future__ import annotations

from pylibinfra.cachekit import Cache

from bot.platform.links import LINK_TTL, chat_link_key, onboard_key


class CacheOnboardingStore:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def is_onboarded(self, tg_id: int) -> bool:
        _, found = await self._cache.get(onboard_key(tg_id))
        return found

    async def mark_onboarded(self, tg_id: int, chat_id: int) -> None:
        await self._cache.set(onboard_key(tg_id), b"1", LINK_TTL)
        # link для фоновой доставки notifications: user_ref(=tg_id) → chat_id
        await self._cache.set(chat_link_key(tg_id), str(chat_id).encode(), LINK_TTL)
