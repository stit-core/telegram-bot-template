"""Unit: notifications.OrderDeliverer — дедуп доставки (резерв с токеном) + резолв chat_id по
link tg→chat. Redis — MemoryRedis lib'ы (те же Lua-CAS, что в проде), кэш — MemoryCache."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pylibinfra.cachekit import Cache, MemoryCache
from pylibinfra.clockkit import Tickable
from pylibinfra.logkit import Logger, nop
from pylibinfra.testkit.bottest import MemoryRedis
from pylibinfra.testkit.logtest import Capture
from pylibinfra.tgbotkit import DeliveryDedup, LocalePrefStore
from tests._fakes.delivery import DeliveryInjectedError, FakeDelivery

from bot.features.notifications.deliver import OrderDeliverer
from bot.platform.links import chat_link_key

pytestmark = pytest.mark.unit

_PAID = {"order_id": "o1", "user_ref": "1"}
_PAID_KEY = "notifications-order-paid"


async def _linked_cache() -> MemoryCache:
    cache = MemoryCache()
    await cache.set(chat_link_key("1"), b"555", 0)
    return cache


def _deliverer(
    cache: Cache, dedup: DeliveryDedup | None = None, log: Logger | None = None
) -> OrderDeliverer:
    dedup = dedup or DeliveryDedup(MemoryRedis())  # type: ignore[arg-type]
    return OrderDeliverer(cache, dedup, LocalePrefStore(cache), log or nop())


async def test_delivers_localized_when_linked() -> None:
    delivery = FakeDelivery()
    await _deliverer(await _linked_cache()).on_order_paid(_PAID, delivery)  # type: ignore[arg-type]
    # текст идёт через delivery.localize (i18n off в тестах → ключ), не хардкод
    assert delivery.messages == [(555, _PAID_KEY)]


async def test_dedup_skips_second_delivery() -> None:
    deliverer = _deliverer(await _linked_cache())
    delivery = FakeDelivery()
    await deliverer.on_order_paid(_PAID, delivery)  # type: ignore[arg-type]
    await deliverer.on_order_paid(_PAID, delivery)  # type: ignore[arg-type]
    assert len(delivery.messages) == 1


async def test_no_link_skips() -> None:
    delivery = FakeDelivery()
    await _deliverer(MemoryCache()).on_order_paid({"order_id": "o1", "user_ref": "99"}, delivery)  # type: ignore[arg-type]
    assert delivery.messages == []


async def test_delivery_failure_propagates_and_redelivery_succeeds() -> None:
    deliverer = _deliverer(await _linked_cache())
    delivery = FakeDelivery()
    delivery.fail_next = 1  # первая отправка падает (транзиентный сбой)

    # сбой ПРОБРАСЫВАЕТСЯ (не глотается) → JsBus сделает nak; сообщение не доставлено
    with pytest.raises(DeliveryInjectedError):
        await deliverer.on_order_paid(_PAID, delivery)  # type: ignore[arg-type]
    assert delivery.messages == []

    # release снял резерв → redelivery доставляет, а не дедупится в тихую потерю
    await deliverer.on_order_paid(_PAID, delivery)  # type: ignore[arg-type]
    assert delivery.messages == [(555, _PAID_KEY)]


class _SlowDelivery(FakeDelivery):
    """Доставка длиннее reserve_ttl: резерв истекает до commit."""

    def __init__(self, clock: Tickable) -> None:
        super().__init__()
        self._clock = clock

    async def send_message(self, *, chat_id: int, text: str, **kwargs: Any) -> None:
        self._clock.advance(2.0)
        await super().send_message(chat_id=chat_id, text=text, **kwargs)


async def test_lost_reservation_is_logged_not_swallowed() -> None:
    clock = Tickable(datetime(2026, 1, 1, tzinfo=UTC))
    log = Capture()
    dedup = DeliveryDedup(MemoryRedis(clock=clock), reserve_ttl=1.0)  # type: ignore[arg-type]
    deliverer = _deliverer(await _linked_cache(), dedup, log)
    delivery = _SlowDelivery(clock)

    await deliverer.on_order_paid(_PAID, delivery)  # type: ignore[arg-type]

    # сообщение ушло, а истёкший резерв (возможный дубль у соседа) — в логе, не проглочен
    assert delivery.messages == [(555, _PAID_KEY)]
    lost = log.find("notifications.reservation_lost", level="warn")
    assert lost is not None
    assert lost.str("key") == "order-paid:o1"
