"""provider.py — dishka Provider фичи payments: порт PaymentsGateway → pkg-клиент (структурно),
гварды платёжных апдейтов (APP-scope: один резерв-реестр на процесс поверх общего Redis)."""

from __future__ import annotations

import redis.asyncio as aioredis
from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger
from pylibinfra.tgbotkit import ChargeGuard, RefundGuard

from bot.features.payments.ports import PaymentsGateway
from bot.features.payments.usecase import PaymentsUsecase
from bot.pkg.http_client.internal.payments import PaymentsAPI


class PaymentsProvider(Provider):
    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def charge_guard(self, client: aioredis.Redis) -> ChargeGuard:
        return ChargeGuard(client)

    @provide(scope=Scope.APP)
    def refund_guard(self, client: aioredis.Redis) -> RefundGuard:
        return RefundGuard(client)

    @provide
    def gateway(self, api: PaymentsAPI) -> PaymentsGateway:
        return api

    @provide
    def usecase(self, gw: PaymentsGateway, log: Logger) -> PaymentsUsecase:
        return PaymentsUsecase(gw, log)
