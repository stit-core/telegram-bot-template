"""Integration: реальный Redis-TTL у DeliveryDedup/ChargeGuard.

Юниты гоняют дедуп через MemoryRedis с фейковыми часами; здесь — боевой redis (testcontainers):
reserve ставит короткое окно с токеном владения (краш до commit не держит ключ вечно →
redelivery повторит), commit поднимает до длинного (нет задвоения доставки/выдачи), а
чужой/истёкший резерв освободить или зафиксировать нельзя.

Гоняется только в `make test-integration` (Docker).
"""

from __future__ import annotations

import asyncio

import pytest
import redis.asyncio as redis
from pylibinfra.testkit import start_redis
from pylibinfra.tgbotkit import ChargeGuard, DeliveryDedup

pytestmark = pytest.mark.integration


async def test_delivery_dedup_reservation_expires_without_commit() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            dedup = DeliveryDedup(client, ttl=100.0, reserve_ttl=1.0)
            token = await dedup.reserve("order-paid:o1")
            assert token is not None
            assert await dedup.reserve("order-paid:o1") is None  # в окне reserve_ttl
            await asyncio.sleep(1.2)
            # окно истекло (краш консьюмера до commit) → redelivery снова резервирует, не дедлок
            assert await dedup.reserve("order-paid:o1") is not None
            # а истёкший токен первого владельца ключ соседа не трогает
            assert await dedup.commit("order-paid:o1", token) is False
            assert await dedup.release("order-paid:o1", token) is False
        finally:
            await client.aclose()


async def test_delivery_dedup_commit_persists_past_reserve_window() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            dedup = DeliveryDedup(client, ttl=100.0, reserve_ttl=1.0)
            token = await dedup.reserve("order-paid:o2")
            assert token is not None
            assert await dedup.commit("order-paid:o2", token) is True
            await asyncio.sleep(1.2)  # переживает reserve_ttl
            # commit поднял TTL до длинного окна → дубликат после reserve_ttl всё ещё дедупится
            assert await dedup.reserve("order-paid:o2") is None
        finally:
            await client.aclose()


async def test_charge_guard_reserve_expires_then_commit_persists() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            guard = ChargeGuard(client, ttl=100.0, reserve_ttl=1.0)
            assert await guard.reserve("charge-1") is not None
            await asyncio.sleep(1.2)
            # выдача упала до commit → ключ протух → повторный апдейт платежа выдаёт заново
            token = await guard.reserve("charge-1")
            assert token is not None
            assert await guard.commit("charge-1", token) is True
            await asyncio.sleep(1.2)
            # commit держит длинное окно → задвоения successful_payment нет
            assert await guard.reserve("charge-1") is None
        finally:
            await client.aclose()
