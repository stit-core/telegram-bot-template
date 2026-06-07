"""BackendProvider — APP-scope: BackendClient поверх httpclient.Client (+ logkit)."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.httpclient import Client
from pylibinfra.logkit import Logger

from bot.platform.backend.client import BackendClient


class BackendProvider(Provider):
    scope = Scope.APP

    @provide
    def client(self, http: Client, log: Logger) -> BackendClient:
        return BackendClient(http, log)
