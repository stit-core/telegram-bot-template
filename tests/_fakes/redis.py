"""FakeRedis — минимальный in-memory redis.asyncio для ChargeGuard / DeliveryDedup.

Поддерживает SET с nx/ex (True при первой записи, None если ключ есть при nx=True) и DELETE.
Этого достаточно для reserve/commit/release-дедупа платежей и доставки. TTL не моделируется —
проверка протухания резервации/коммита идёт в integration (testcontainers redis).
"""

from __future__ import annotations

from typing import Any


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def set(
        self,
        name: str,
        value: Any,
        *args: Any,
        nx: bool = False,
        ex: Any = None,
        **kwargs: Any,
    ) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    async def delete(self, *names: str) -> int:
        return sum(self.store.pop(name, None) is not None for name in names)
