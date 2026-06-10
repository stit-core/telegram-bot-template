"""provider.py — DI пакета: internal-клиенты поверх именованного ApiClient «core».

Имя бэкенда = ключ в BackendsConfig (config.py) = label breaker-метрик. Новый internal-
бэкенд: модуль в internal/, имя-константа, @provide здесь, запись в BackendsConfig.
"""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.httpclient import ApiClients

from bot.pkg.http_client.internal.booking import BookingAPI
from bot.pkg.http_client.internal.payments import PaymentsAPI
from bot.pkg.http_client.internal.profile import ProfileAPI

CORE_BACKEND = "core"


class InternalApiProvider(Provider):
    scope = Scope.APP

    @provide
    def profile(self, clients: ApiClients) -> ProfileAPI:
        return ProfileAPI(clients.get(CORE_BACKEND))

    @provide
    def booking(self, clients: ApiClients) -> BookingAPI:
        return BookingAPI(clients.get(CORE_BACKEND))

    @provide
    def payments(self, clients: ApiClients) -> PaymentsAPI:
        return PaymentsAPI(clients.get(CORE_BACKEND))
