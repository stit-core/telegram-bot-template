"""FakeCache — in-memory реализация cachekit.Cache (структурно). Без Redis/Docker.

Хранит bytes по ключу; TTL/tags игнорируются (тестам не нужны). Удовлетворяет порту
pylibinfra.cachekit.Cache — подставляется вместо RedisCache в unit/flow-контейнере.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> tuple[bytes | None, bool]:
        val = self.store.get(key)
        return (val, val is not None)

    async def set(
        self,
        key: str,
        value: bytes,
        ttl: timedelta | None = None,
        *,
        tags: Sequence[str] = (),
    ) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.store.pop(k, None)

    async def invalidate_by_tag(self, tag: str) -> None:
        pass

    async def ping(self) -> None:
        pass
