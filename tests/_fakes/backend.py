"""FakeBackendClient — заглушка platform.backend.BackendClient для flow-тестов.

Держит один профиль в памяти: GET возвращает его, PATCH мёржит json и возвращает обновлённый
(после rename последующий GET видит новое имя). Ошибки инжектятся через get_error/patch_error.
Мокаем порт/границу бэкенда, не реальный httpx (это для backend-тестов с respx).
"""

from __future__ import annotations

from typing import Any


class FakeBackendClient:
    def __init__(self, profile: dict[str, Any] | None = None) -> None:
        self.profile: dict[str, Any] = profile or {}
        self.get_error: Exception | None = None
        self.patch_error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str) -> dict[str, Any]:
        self.calls.append(("GET", path))
        if self.get_error is not None:
            raise self.get_error
        return dict(self.profile)

    async def post(
        self, path: str, *, json: dict[str, Any] | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("POST", path))
        if self.patch_error is not None:
            raise self.patch_error
        return dict(self.profile)

    async def patch(
        self, path: str, *, json: dict[str, Any] | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("PATCH", path))
        if self.patch_error is not None:
            raise self.patch_error
        if json:
            self.profile.update(json)
        return dict(self.profile)
