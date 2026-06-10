"""provider.py — dishka Provider фичи start. Связывает порт OnboardingStore → infra-реализацию.

Scope.REQUEST: усекается на каждый Update (как identity/per-update контекст). StartUsecase
резолвится и cross-feature (profile-провайдер зависит от него — см. profile/adapters.py).
"""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.cachekit import Cache

from bot.features.start.infra.store import CacheOnboardingStore
from bot.features.start.ports import OnboardingStore
from bot.features.start.usecase import StartUsecase


class StartProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def store(self, cache: Cache) -> OnboardingStore:
        return CacheOnboardingStore(cache)

    @provide
    def usecase(self, store: OnboardingStore) -> StartUsecase:
        return StartUsecase(store)
