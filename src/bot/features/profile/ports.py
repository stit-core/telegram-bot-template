"""ports.py — порты фичи profile (Protocol). PURE.

Сужены до методов ЭТОГО сценария (ISP), возвращают локальные DTO (anti-corruption).
Реализации (gateway/adapter) связываются в provider.py (DIP). OnboardingReader — cross-
feature порт, объявлен ЗДЕСЬ (в потребителе), а не в start.
"""

from __future__ import annotations

from typing import Protocol

from bot.features.profile.dto import ProfileView


class BackendGateway(Protocol):
    async def load_profile(self, backend_user_id: str) -> ProfileView: ...

    async def update_name(self, backend_user_id: str, name: str) -> ProfileView: ...


class OnboardingReader(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...
