"""provider.py — dishka Provider фичи payments. Порт PaymentsGateway → pkg-клиент (структурно)."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger

from bot.features.payments.ports import PaymentsGateway
from bot.features.payments.usecase import PaymentsUsecase
from bot.pkg.http_client.internal.payments import PaymentsAPI


class PaymentsProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, api: PaymentsAPI) -> PaymentsGateway:
        return api

    @provide
    def usecase(self, gw: PaymentsGateway, log: Logger) -> PaymentsUsecase:
        return PaymentsUsecase(gw, log)
