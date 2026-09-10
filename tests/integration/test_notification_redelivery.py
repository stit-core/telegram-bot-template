"""Integration golden: транзиентный сбой доставки не теряет push.

Боевой `OrderDeliverer` (deliver_*) поверх реального JetStream + Redis: первая отправка падает
→ release → проброс → JsBus nak → redelivery → вторая отправка успешна → commit. Сообщение
доставлено РОВНО раз — без тихой потери и без задвоения. Это сквозной контроль reserve/commit/
release + nak/redelivery, который фейки (MemoryRedis, in-memory bus) не ловят.

Gating: только `make test-integration` (Docker; testcontainers redis + nats c JetStream).
"""

from __future__ import annotations

import asyncio

import pytest
import redis.asyncio as redis
from pylibinfra.cachekit import RedisCache
from pylibinfra.logkit import nop
from pylibinfra.natskit import publish_stream_json, subscribe_stream_json
from pylibinfra.testkit import start_nats, start_redis
from pylibinfra.tgbotkit import DeliveryDedup, LocalePrefStore
from tests._fakes.delivery import FakeDelivery

from bot.features.notifications.deliver import OrderDeliverer
from bot.platform.links import chat_link_key

pytestmark = pytest.mark.integration

# FakeDelivery.localize без translator отдаёт ключ (i18n off) — golden проверяет доставку/дедуп,
# не рендер текста (рендер локали покрыт kit-тестами Delivery.localize)
_PAID_KEY = "notifications-order-paid"
# быстрый ретрай, а не kit-дефолты (1s backoff, 30s ack_wait): тест ждёт секунды, не минуты
_JETSTREAM = {"stream_names": ("orders",), "max_deliver": 5, "nak_backoff": 0.2, "ack_wait": 1.0}


async def test_transient_delivery_failure_redelivers_then_commits_once() -> None:
    async with start_redis() as rf, start_nats(jetstream=True) as ns:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            cache = RedisCache(client)
            await cache.set(chat_link_key("u1"), b"555", 0)
            dedup = DeliveryDedup(client)
            deliverer = OrderDeliverer(cache, dedup, LocalePrefStore(cache), nop())
            delivery = FakeDelivery()
            delivery.fail_next = 1  # первая доставка падает (транзиентный сбой)
            attempts = 0

            async with ns.stream_bus(jetstream=_JETSTREAM) as bus:

                async def handler(payload: object) -> None:
                    nonlocal attempts
                    attempts += 1
                    await deliverer.on_order_paid(payload, delivery)  # type: ignore[arg-type]

                sub = await subscribe_stream_json(
                    bus, "orders", "orders.paid", "bot-orders-paid", handler
                )
                await publish_stream_json(bus, "orders.paid", {"order_id": "o1", "user_ref": "u1"})

                for _ in range(50):  # ждём nak→redelivery→успех (backoff 0.2s)
                    if delivery.messages:
                        break
                    await asyncio.sleep(0.1)

                await sub.drain(timeout=5)

            # nak вернул сообщение в консьюмер — путь redelivery реально пройден, не первый успех
            assert attempts >= 2
            # ровно одна доставка нужному чату — потери/задвоения нет
            assert delivery.messages == [(555, _PAID_KEY)]
            # commit поднял дедуп-ключ → повторный reserve того же события дедупится
            assert await dedup.reserve("order-paid:o1") is None
        finally:
            await client.aclose()
