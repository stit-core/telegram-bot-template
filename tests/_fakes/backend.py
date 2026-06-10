"""FakeApiClient — заглушка pylibinfra.httpclient.ApiClient для flow-тестов.

Держит один JSON-объект в памяти: GET/POST возвращают его, PATCH мёржит json и возвращает
обновлённый (после rename последующий GET видит новое имя). Ошибки инжектятся через
get_error/patch_error (kit'овые NotFoundError/UnavailableError/...). Мокаем границу
бэкенда, не httpx (транспорт-граница покрыта respx-тестами в tests/pkg/).
"""

from __future__ import annotations

from typing import Any


class FakeApiClient:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload: dict[str, Any] = payload or {}
        self.get_error: Exception | None = None
        self.patch_error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("GET", path))
        if self.get_error is not None:
            raise self.get_error
        return dict(self.payload)

    async def post(
        self, path: str, *, json: Any | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("POST", path))
        if self.patch_error is not None:
            raise self.patch_error
        return dict(self.payload)

    async def patch(
        self, path: str, *, json: Any | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("PATCH", path))
        if self.patch_error is not None:
            raise self.patch_error
        if json:
            self.payload.update(json)
        return dict(self.payload)
