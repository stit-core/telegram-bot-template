"""Integration: реальный Redis-TTL у DeliveryDedup/ChargeGuard.

Юниты гоняют дедуп через FakeRedis, который TTL не моделирует — поэтому «протухание
резервации» и «commit держит длинное окно» там не проверяемы (ложный зелёный). Здесь — боевой
redis (testcontainers): reserve ставит короткое окно (краш до commit не держит ключ вечно →
redelivery повторит), commit поднимает до длинного (нет задвоения доставки/выдачи).

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
            assert await dedup.reserve("order-paid:o1") is True
            assert await dedup.reserve("order-paid:o1") is False  # в окне reserve_ttl
            await asyncio.sleep(1.2)
            # окно истекло (краш консьюмера до commit) → redelivery снова резервирует, не дедлок
            assert await dedup.reserve("order-paid:o1") is True
        finally:
            await client.aclose()


async def test_delivery_dedup_commit_persists_past_reserve_window() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            dedup = DeliveryDedup(client, ttl=100.0, reserve_ttl=1.0)
            assert await dedup.reserve("order-paid:o2") is True
            await dedup.commit("order-paid:o2")
            await asyncio.sleep(1.2)  # переживает reserve_ttl
            # commit поднял TTL до длинного окна → дубликат после reserve_ttl всё ещё дедупится
            assert await dedup.reserve("order-paid:o2") is False
        finally:
            await client.aclose()


async def test_charge_guard_reserve_expires_then_commit_persists() -> None:
    async with start_redis() as rf:
        client: redis.Redis = redis.from_url(rf.url)
        try:
            guard = ChargeGuard(client, ttl=100.0, reserve_ttl=1.0)
            assert await guard.reserve("charge-1") is True
            await asyncio.sleep(1.2)
            # выдача упала до commit → ключ протух → повторный апдейт платежа выдаёт заново
            assert await guard.reserve("charge-1") is True
            await guard.commit("charge-1")
            await asyncio.sleep(1.2)
            # commit держит длинное окно → задвоения successful_payment нет
            assert await guard.reserve("charge-1") is False
        finally:
            await client.aclose()
