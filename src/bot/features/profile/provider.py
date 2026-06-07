"""provider.py — dishka Provider фичи profile. Здесь (и только здесь) порты связываются
с реализациями (DIP): gateway → http-адаптер, onboarding → cross-feature адаптер.

Scope.REQUEST: усекается на каждый Update. usecase получает оба порта + logkit.Logger.
"""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger

from bot.features.profile.adapters import OnboardingReaderAdapter
from bot.features.profile.gateway import HttpProfileGateway
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.features.profile.usecase import ProfileUsecase
from bot.features.start.usecase import StartUsecase
from bot.platform.backend import BackendClient


class ProfileProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, http: BackendClient) -> BackendGateway:
        return HttpProfileGateway(http)

    @provide
    def onboarding(self, start_uc: StartUsecase) -> OnboardingReader:
        return OnboardingReaderAdapter(start_uc)

    @provide
    def usecase(self, gw: BackendGateway, onb: OnboardingReader, log: Logger) -> ProfileUsecase:
        return ProfileUsecase(gw, onb, log)
