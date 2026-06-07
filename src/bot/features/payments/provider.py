"""provider.py — dishka Provider фичи payments. Порт PaymentsGateway → http-адаптер."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger

from bot.features.payments.gateway import HttpPaymentsGateway
from bot.features.payments.ports import PaymentsGateway
from bot.features.payments.usecase import PaymentsUsecase
from bot.platform.backend import BackendClient


class PaymentsProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, http: BackendClient) -> PaymentsGateway:
        return HttpPaymentsGateway(http)

    @provide
    def usecase(self, gw: PaymentsGateway, log: Logger) -> PaymentsUsecase:
        return PaymentsUsecase(gw, log)
