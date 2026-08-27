"""api.py — JsonApi: типизированная поверхность ApiClient кита как Protocol.

Клиенты пакета зависят от контракта, не от класса: pylibinfra.httpclient.ApiClient
удовлетворяет его структурно, тестовый фейк (tests/_fakes/backend.py) — тоже, без
type: ignore. Сигнатуры зеркалят ApiClient (model= — декод в wire-модель)."""

from __future__ import annotations

from typing import Any, Protocol, overload

from pydantic import BaseModel


class JsonApi(Protocol):
    @overload
    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any: ...

    @overload
    async def get[M: BaseModel](
        self, path: str, *, params: dict[str, Any] | None = None, model: type[M]
    ) -> M: ...

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any: ...

    @overload
    async def post(
        self, path: str, *, json: Any | None = None, idempotency_key: str | None = None
    ) -> Any: ...

    @overload
    async def post[M: BaseModel](
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[M],
    ) -> M: ...

    async def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any: ...

    @overload
    async def put(
        self, path: str, *, json: Any | None = None, idempotency_key: str | None = None
    ) -> Any: ...

    @overload
    async def put[M: BaseModel](
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[M],
    ) -> M: ...

    async def put(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any: ...

    @overload
    async def patch(
        self, path: str, *, json: Any | None = None, idempotency_key: str | None = None
    ) -> Any: ...

    @overload
    async def patch[M: BaseModel](
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[M],
    ) -> M: ...

    async def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any: ...

    @overload
    async def delete(self, path: str, *, idempotency_key: str | None = None) -> Any: ...

    @overload
    async def delete[M: BaseModel](
        self, path: str, *, idempotency_key: str | None = None, model: type[M]
    ) -> M: ...

    async def delete(
        self,
        path: str,
        *,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any: ...
