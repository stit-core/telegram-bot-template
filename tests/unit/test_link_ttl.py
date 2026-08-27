"""Unit: записи онбординга пишутся с LINK_TTL (дочистка заброшенных, не вечно в redis)."""

from __future__ import annotations

import pytest
from tests._fakes.cache import FakeCache

from bot.features.start.infra.store import CacheOnboardingStore
from bot.platform.links import LINK_TTL, chat_link_key, onboard_key

pytestmark = pytest.mark.unit


async def test_mark_onboarded_sets_link_ttl() -> None:
    cache = FakeCache()
    await CacheOnboardingStore(cache).mark_onboarded(7, 555)
    assert cache.store[onboard_key(7)] == b"1"
    assert cache.store[chat_link_key(7)] == b"555"
    # onboard и chat_link протухают вместе → нет рассинхрона флага онбординга и роутинга
    assert cache.ttls[onboard_key(7)] == LINK_TTL
    assert cache.ttls[chat_link_key(7)] == LINK_TTL
