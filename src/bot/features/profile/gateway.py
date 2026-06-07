"""gateway.py — HTTP-реализация BackendGateway. Единственная точка маппинга транспорт→домен.

Структурно удовлетворяет ports.BackendGateway (mypy проверит), связывается в provider.py.
httpx скрыт за platform/backend.BackendClient; транспорт-ошибки → sentinel-ошибки фичи.
"""

from __future__ import annotations

from typing import Any

from bot.features.profile import errors
from bot.features.profile.dto import ProfileView
from bot.platform.backend import (
    BackendClient,
    BackendConflict,
    BackendNotFound,
    BackendUnavailable,
)


class HttpProfileGateway:
    def __init__(self, http: BackendClient) -> None:
        self._http = http

    async def load_profile(self, backend_user_id: str) -> ProfileView:
        try:
            raw = await self._http.get(f"/v1/users/{backend_user_id}")
        except BackendNotFound as exc:
            raise errors.ProfileNotFound(str(exc)) from exc
        except BackendUnavailable as exc:
            raise errors.ProfileError("Сервис временно недоступен") from exc
        return self._to_view(raw)

    async def update_name(self, backend_user_id: str, name: str) -> ProfileView:
        try:
            # Idempotency-Key защищает от двойных кликов/ретраев httpclient
            raw = await self._http.patch(
                f"/v1/users/{backend_user_id}",
                json={"name": name},
                idempotency_key=f"profile-rename:{backend_user_id}:{name}",
            )
        except BackendNotFound as exc:
            raise errors.ProfileNotFound(str(exc)) from exc
        except BackendConflict as exc:
            # rename возвращает обновлённый профиль — на 409 тела нет, успех неоднозначен
            raise errors.ProfileError("Не удалось обновить профиль") from exc
        except BackendUnavailable as exc:
            raise errors.ProfileError("Сервис временно недоступен") from exc
        return self._to_view(raw)

    @staticmethod
    def _to_view(raw: dict[str, Any]) -> ProfileView:
        return ProfileView(
            name=raw["name"], email=raw["email"], is_premium=bool(raw.get("premium", False))
        )
