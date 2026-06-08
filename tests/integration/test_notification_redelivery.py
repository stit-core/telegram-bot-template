"""Integration golden: транзиентный сбой доставки не теряет push.

Боевой `OrderDeliverer` (deliver_*) поверх реального JetStream + Redis: первая отправка падает
→ release → проброс → JsBus nak → redelivery → вторая отправка успешна → commit. Сообщение
доставлено РОВНО раз — без тихой потери и без задвоения. Это сквозной контроль reserve/commit/
release + nak/redelivery, который фейки (FakeRedis без TTL, in-memory bus) не ловят.

Gating: только `make test-integration` (Docker; testcontainers redis + nats c JetStream).
"""

from __future__ import annotations

import asyncio

import nats
import pytest
import redis.asyncio as redis
from pylibinfra.cachekit import RedisCache
from pylibinfra.natskit import (
    Conn,
    JsBus,
    new_stream_bus,
    publish_stream_json,
    subscribe_stream_json,
)
from pylibinfra.natskit.config import Config, JetStreamConfig
from pylibinfra.testkit import start_redis
from pylibinfra.tgbotkit import DeliveryDedup
from testcontainers.nats import NatsContainer  # testkit.start_nats не включает JetStream
from tests._fakes.delivery import FakeDelivery

from bot.features.notifications.deliver import OrderDeliverer
from bot.platform.links import chat_link_key

pytestmark = pytest.mark.integration

_PAID_TEXT = "✅ Оплата заказа o1 получена. Спасибо!"


async def test_transient_delivery_failure_redelivers_then_commits_once() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            cache = RedisCache(client)
            await cache.set(chat_link_key("u1"), b"555")
            dedup = DeliveryDedup(client)
            deliverer = OrderDeliverer(cache, dedup)
            delivery = FakeDelivery()
            delivery.fail_next = 1  # первая доставка падает (транзиентный сбой)
            attempts = 0

            with NatsContainer(jetstream=True) as container:
                nc = await nats.connect(container.nats_uri())
                try:
                    cfg = Config(
                        jetstream=JetStreamConfig(
                            enabled=True,
                            stream_names=["orders"],
                            max_deliver=5,
                            backoff=[0.2],
                            ack_wait=0.5,
                            dlq_enabled=False,
                        )
                    )
                    bus = await new_stream_bus(Conn(nc), cfg)
                    assert isinstance(bus, JsBus)

                    async def handler(payload: object) -> None:
                        nonlocal attempts
                        attempts += 1
                        await deliverer.on_order_paid(payload, delivery)  # type: ignore[arg-type]

                    await subscribe_stream_json(
                        bus, "orders", "orders.paid", "bot-orders-paid", handler
                    )
                    await asyncio.sleep(0.2)
                    await publish_stream_json(
                        bus, "orders.paid", {"order_id": "o1", "user_ref": "u1"}
                    )

                    for _ in range(50):  # ждём nak→redelivery→успех (backoff 0.2s)
                        if delivery.messages:
                            break
                        await asyncio.sleep(0.1)

                    await bus.drain()
                finally:
                    await nc.drain()

            # nak вернул сообщение в консьюмер — путь redelivery реально пройден, не первый успех
            assert attempts >= 2
            # ровно одна доставка нужному чату — потери/задвоения нет
            assert delivery.messages == [(555, _PAID_TEXT)]
            # commit поднял дедуп-ключ → повторный reserve того же события дедупится
            assert await dedup.reserve("order-paid:o1") is False
        finally:
            await client.aclose()
