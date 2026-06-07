"""Unit: notifications.OrderDeliverer — дедуп доставки + резолв chat_id по link tg→chat."""

from __future__ import annotations

import pytest
from pylibinfra.tgbotkit import DeliveryDedup
from tests._fakes.cache import FakeCache
from tests._fakes.delivery import DeliveryInjectedError, FakeDelivery
from tests._fakes.redis import FakeRedis

from bot.features.notifications.deliver import OrderDeliverer
from bot.platform.links import chat_link_key

pytestmark = pytest.mark.unit


def _deliverer(cache: FakeCache) -> OrderDeliverer:
    return OrderDeliverer(cache, DeliveryDedup(FakeRedis()))  # type: ignore[arg-type]


async def test_delivers_when_linked() -> None:
    cache = FakeCache()
    cache.store[chat_link_key("1")] = b"555"
    delivery = FakeDelivery()
    await _deliverer(cache).on_order_paid({"order_id": "o1", "user_ref": "1"}, delivery)  # type: ignore[arg-type]
    assert len(delivery.messages) == 1
    assert delivery.messages[0][0] == 555


async def test_dedup_skips_second_delivery() -> None:
    cache = FakeCache()
    cache.store[chat_link_key("1")] = b"555"
    deliverer = _deliverer(cache)
    delivery = FakeDelivery()
    await deliverer.on_order_paid({"order_id": "o1", "user_ref": "1"}, delivery)  # type: ignore[arg-type]
    await deliverer.on_order_paid({"order_id": "o1", "user_ref": "1"}, delivery)  # type: ignore[arg-type]
    assert len(delivery.messages) == 1


async def test_no_link_skips() -> None:
    delivery = FakeDelivery()
    await _deliverer(FakeCache()).on_order_paid({"order_id": "o1", "user_ref": "99"}, delivery)  # type: ignore[arg-type]
    assert delivery.messages == []


async def test_delivery_failure_propagates_and_redelivery_succeeds() -> None:
    cache = FakeCache()
    cache.store[chat_link_key("1")] = b"555"
    deliverer = _deliverer(cache)
    delivery = FakeDelivery()
    delivery.fail_next = 1  # первая отправка падает (транзиентный сбой)

    # сбой ПРОБРАСЫВАЕТСЯ (не глотается) → JsBus сделает nak; сообщение не доставлено
    with pytest.raises(DeliveryInjectedError):
        await deliverer.on_order_paid({"order_id": "o1", "user_ref": "1"}, delivery)  # type: ignore[arg-type]
    assert delivery.messages == []

    # release снял резервацию → redelivery доставляет, а не дедупится в тихую потерю
    await deliverer.on_order_paid({"order_id": "o1", "user_ref": "1"}, delivery)  # type: ignore[arg-type]
    assert len(delivery.messages) == 1
    assert delivery.messages[0][0] == 555
