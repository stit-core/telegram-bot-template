"""provider.py — dishka Provider фичи booking. Порт BookingGateway → http-адаптер."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger

from bot.features.booking.gateway import HttpBookingGateway
from bot.features.booking.ports import BookingGateway
from bot.features.booking.usecase import BookingUsecase
from bot.platform.backend import BackendClient


class BookingProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, http: BackendClient) -> BookingGateway:
        return HttpBookingGateway(http)

    @provide
    def usecase(self, gw: BookingGateway, log: Logger) -> BookingUsecase:
        return BookingUsecase(gw, log)
