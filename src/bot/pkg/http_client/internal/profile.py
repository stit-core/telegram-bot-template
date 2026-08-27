"""ProfileAPI — пользовательский срез core-бэкенда (/v1/users)."""

from __future__ import annotations

from bot.pkg.http_client.api import JsonApi
from bot.pkg.http_client.idempotency import idempotency_key
from bot.pkg.http_client.wire import WireModel


class User(WireModel):
    name: str
    email: str
    premium: bool


class ProfileAPI:
    def __init__(self, api: JsonApi) -> None:
        self._api = api

    async def get_user(self, user_id: str) -> User:
        return await self._api.get(f"/v1/users/{user_id}", model=User)

    async def rename_user(self, user_id: str, name: str) -> User:
        # ключ стабилен по (user_id, name): повтор того же rename не дублирует мутацию
        return await self._api.patch(
            f"/v1/users/{user_id}",
            json={"name": name},
            idempotency_key=idempotency_key("profile-rename", user_id, name),
            model=User,
        )
