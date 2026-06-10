"""provider.py — dishka Provider фичи booking. Порт BookingGateway → pkg-клиент (структурно)."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger

from bot.features.booking.ports import BookingGateway
from bot.features.booking.usecase import BookingUsecase
from bot.pkg.http_client.internal.booking import BookingAPI


class BookingProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, api: BookingAPI) -> BookingGateway:
        return api

    @provide
    def usecase(self, gw: BookingGateway, log: Logger) -> BookingUsecase:
        return BookingUsecase(gw, log)
