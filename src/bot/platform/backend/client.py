"""BackendClient — тонкий фасад над pylibinfra.httpclient.Client.

Добавляет доменный маппинг HTTP-статусов в транспорт-ошибки и Idempotency-Key поверх
готового клиента. X-Request-ID / retry / circuit breaker / OTel-span уже ВНУТРИ
httpclient.Client. ВАЖНО: httpclient райзит сам только на 5xx-после-ретраев
(HTTPStatusError); 4xx возвращает Response без исключения — поэтому статусы разбираем тут.
"""

from __future__ import annotations

from typing import Any

import httpx
from pylibinfra.httpclient import BreakerOpenError, Client
from pylibinfra.logkit import Logger

from bot.platform.backend.errors import BackendConflict, BackendNotFound, BackendUnavailable


class BackendClient:
    def __init__(self, http: Client, log: Logger) -> None:
        self._http = http
        self._log = log

    async def get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def post(
        self, path: str, *, json: dict[str, Any] | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=json, idempotency_key=idempotency_key)

    async def patch(
        self, path: str, *, json: dict[str, Any] | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return await self._request("PATCH", path, json=json, idempotency_key=idempotency_key)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            resp = await self._http.request(method, path, json=json, headers=headers)
        except BreakerOpenError as exc:
            raise BackendUnavailable("backend circuit breaker open") from exc
        except httpx.HTTPStatusError as exc:  # 5xx после ретраев
            raise BackendUnavailable(f"backend 5xx: {exc}") from exc
        except httpx.TransportError as exc:  # connect/read timeout, conn refused
            raise BackendUnavailable(f"backend transport error: {exc}") from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.is_success:
            if not resp.content:
                return {}
            body: dict[str, Any] = resp.json()
            return body
        if resp.status_code == 404:
            raise BackendNotFound(f"{resp.request.method} {resp.request.url}: 404")
        if resp.status_code == 409:
            raise BackendConflict(f"{resp.request.method} {resp.request.url}: 409")
        # прочие 4xx (400/401/403/422) — контрактный сбой, для UX это «недоступно»
        raise BackendUnavailable(f"backend status {resp.status_code}")
