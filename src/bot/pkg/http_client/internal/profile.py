"""ProfileAPI — пользовательский срез core-бэкенда (/v1/users)."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.internal.codec import parse


class User(BaseModel):
    name: str
    email: str
    premium: bool = False


class ProfileAPI:
    def __init__(self, api: ApiClient) -> None:
        self._api = api

    async def get_user(self, user_id: str) -> User:
        raw = await self._api.get(f"/v1/users/{user_id}")
        return parse(User, raw)

    async def rename_user(self, user_id: str, name: str) -> User:
        # Idempotency-Key уходит в latin-1 HTTP-заголовок: кириллица в name иначе падает
        # UnicodeEncodeError до запроса. sha256 стабилен по имени → идемпотентность цела.
        digest = hashlib.sha256(name.encode()).hexdigest()
        raw = await self._api.patch(
            f"/v1/users/{user_id}",
            json={"name": name},
            idempotency_key=f"profile-rename:{user_id}:{digest}",
        )
        return parse(User, raw)
