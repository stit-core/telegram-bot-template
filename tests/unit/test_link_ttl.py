"""Unit: записи онбординга живут LINK_TTL и протухают вместе (дочистка заброшенных юзеров)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pylibinfra.cachekit import MemoryCache
from pylibinfra.clockkit import Tickable

from bot.features.start.infra.store import CacheOnboardingStore
from bot.platform.links import LINK_TTL, chat_link_key, onboard_key

pytestmark = pytest.mark.unit


async def test_mark_onboarded_links_expire_together() -> None:
    clock = Tickable(datetime(2026, 1, 1, tzinfo=UTC))
    cache = MemoryCache(clock)
    store = CacheOnboardingStore(cache)

    await store.mark_onboarded(7, 555)
    assert await store.is_onboarded(7) is True
    assert await cache.get(chat_link_key(7)) == b"555"

    clock.advance(LINK_TTL - 1)
    assert await store.is_onboarded(7) is True

    # onboard и chat_link протухают вместе → нет рассинхрона флага онбординга и роутинга
    clock.advance(2)
    assert await store.is_onboarded(7) is False
    assert await cache.get(onboard_key(7)) is None
    assert await cache.get(chat_link_key(7)) is None
