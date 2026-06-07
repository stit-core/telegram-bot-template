"""FakeRedis — минимальный in-memory redis.asyncio для guard_charge / DeliveryDedup.

Поддерживает SET с nx/ex: возвращает True при первой записи ключа, None — если ключ уже есть
(nx=True). Этого достаточно для проверки дедупа платежей и доставки.
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
