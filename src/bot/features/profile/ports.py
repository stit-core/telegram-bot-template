"""ports.py — порты фичи profile (Protocol). PURE.

Сужены до методов ЭТОГО сценария (ISP), типизированы wire-моделями pkg-клиента —
ProfileAPI удовлетворяет порт структурно, без адаптера (связывает provider.py, DIP).
OnboardingReader — cross-feature порт, объявлен ЗДЕСЬ (в потребителе), а не в start.
"""

from __future__ import annotations

from typing import Protocol

from bot.pkg.http_client.internal.profile import User


class BackendGateway(Protocol):
    async def get_user(self, user_id: str) -> User: ...

    async def rename_user(self, user_id: str, name: str) -> User: ...


class OnboardingReader(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...
