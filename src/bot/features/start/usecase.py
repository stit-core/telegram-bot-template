"""usecase.py — оркестрация онбординга. Знает только про порт OnboardingStore (Protocol).

Не знает про cachekit/aiogram. status() читают и cross-feature потребители (profile —
через adapters.OnboardingReaderAdapter). mark_onboarded() пишет флаг + link tg→chat.
"""

from __future__ import annotations

from bot.features.start import policy
from bot.features.start.ports import OnboardingStore
from bot.features.start.state import OnboardingStatus


class StartUsecase:
    def __init__(self, store: OnboardingStore) -> None:
        self._store = store

    async def status(self, tg_id: int) -> OnboardingStatus:
        return OnboardingStatus(completed=await self._store.is_onboarded(tg_id))

    async def greeting_key(self, tg_id: int) -> str:
        return policy.greeting_key(await self.status(tg_id))

    async def mark_onboarded(self, tg_id: int, chat_id: int) -> None:
        await self._store.mark_onboarded(tg_id, chat_id)
