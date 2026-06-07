"""adapters.py — cross-feature anti-corruption. ЕДИНСТВЕННОЕ место (вместе с provider.py),
где импортим другую фичу (import-linter разрешает это исключение).

Адаптер мапит результат чужого usecase (start) в наш порт-контракт (OnboardingReader).
"""

from __future__ import annotations

from bot.features.start.usecase import StartUsecase


class OnboardingReaderAdapter:
    def __init__(self, start_uc: StartUsecase) -> None:
        self._start = start_uc

    async def is_onboarded(self, tg_id: int) -> bool:
        status = await self._start.status(tg_id)
        return status.completed
