"""dto.py — доменные DTO сценария (anti-corruption). PURE.

«Язык» фичи: gateway мапит сырой JSON бэкенда → сюда, presentation читает отсюда.
Меняется контракт бэкенда — правится только gateway.py, не вся фича.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProfileView(BaseModel):
    name: str
    email: str
    is_premium: bool = False
