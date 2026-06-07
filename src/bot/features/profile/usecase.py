"""usecase.py — оркестрация сценария. Знает ТОЛЬКО порты (Protocol) и policy.

Не знает про httpx/aiogram/redis. Собирает сценарий: проверка политики → вызов порта.
Конструктор принимает порты (их подставляет dishka, см. provider.py) и logkit.Logger.
"""

from __future__ import annotations

from pylibinfra.logkit import Logger

from bot.features.profile import errors, policy
from bot.features.profile.dto import ProfileView
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.platform.identity import BotIdentity


class ProfileUsecase:
    def __init__(self, gateway: BackendGateway, onboarding: OnboardingReader, log: Logger) -> None:
        self._gateway = gateway
        self._onboarding = onboarding
        self._log = log

    async def view(self, identity: BotIdentity) -> ProfileView:
        decision = policy.can_view_profile(identity.role)
        if not decision.allowed:
            raise errors.ProfileForbidden(decision.reason)
        return await self._gateway.load_profile(identity.backend_user_id)

    async def rename(self, identity: BotIdentity, raw_name: str) -> ProfileView:
        decision = policy.validate_name(raw_name)
        if not decision.allowed:
            raise errors.NameRejected(decision.reason)
        view = await self._gateway.update_name(identity.backend_user_id, raw_name.strip())
        self._log.info("profile.renamed", tg_id=identity.tg_id)
        return view

    async def is_first_time(self, tg_id: int) -> bool:
        return not await self._onboarding.is_onboarded(tg_id)
