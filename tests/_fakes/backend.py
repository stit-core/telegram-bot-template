"""FakeApiClient — in-memory реализация JsonApi (bot.pkg.http_client.api) для flow-тестов.

Payload per-path (payloads[path]) с общим дефолтом payload; PATCH мёржит json и возвращает
обновлённый (после rename последующий GET видит новое имя). Ошибки инжектятся per-метод
(get_error/post_error/...) kit-классами из bot.pkg.http_client.errors. model= применяется
как в ките (model_validate) — flow-тесты проверяют и wire-контракт. Мокаем границу бэкенда,
не httpx (транспорт-граница покрыта respx-тестами в tests/pkg/).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class FakeApiClient:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload: dict[str, Any] = payload or {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.get_error: Exception | None = None
        self.post_error: Exception | None = None
        self.put_error: Exception | None = None
        self.patch_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.calls: list[tuple[str, str]] = []
        self.idempotency_keys: list[str] = []

    def _payload_for(self, path: str) -> dict[str, Any]:
        return self.payloads.get(path, self.payload)

    @staticmethod
    def _decode(raw: Any, model: type[BaseModel] | None) -> Any:
        return model.model_validate(raw) if model is not None else raw

    def _record(self, method: str, path: str, idempotency_key: str | None = None) -> None:
        self.calls.append((method, path))
        if idempotency_key is not None:
            self.idempotency_keys.append(idempotency_key)

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any:
        self._record("GET", path)
        if self.get_error is not None:
            raise self.get_error
        return self._decode(dict(self._payload_for(path)), model)

    async def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any:
        self._record("POST", path, idempotency_key)
        if self.post_error is not None:
            raise self.post_error
        return self._decode(dict(self._payload_for(path)), model)

    async def put(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any:
        self._record("PUT", path, idempotency_key)
        if self.put_error is not None:
            raise self.put_error
        if isinstance(json, dict):
            self._payload_for(path).update(json)
        return self._decode(dict(self._payload_for(path)), model)

    async def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any:
        self._record("PATCH", path, idempotency_key)
        if self.patch_error is not None:
            raise self.patch_error
        if isinstance(json, dict):
            self._payload_for(path).update(json)
        return self._decode(dict(self._payload_for(path)), model)

    async def delete(
        self,
        path: str,
        *,
        idempotency_key: str | None = None,
        model: type[BaseModel] | None = None,
    ) -> Any:
        self._record("DELETE", path, idempotency_key)
        if self.delete_error is not None:
            raise self.delete_error
        return self._decode(dict(self._payload_for(path)), model)
