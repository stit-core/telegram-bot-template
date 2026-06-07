"""Ключи identity-link в cachekit — общие для identity-резолва, start-онбординга и
notifications-доставки. Вынесены сюда, чтобы фичи не импортили друг друга ради формата ключа.
PURE (только строки).

- BACKEND_LINK : tg_id → backend_user_id (identity-резолв; пишется при линковке аккаунта)
- ONBOARD      : tg_id → "1" (флаг пройденного онбординга)
- CHAT_LINK    : user_ref → chat_id (куда слать фоновые уведомления)
"""

from __future__ import annotations

BACKEND_LINK_PREFIX = "link:tg:"
ONBOARD_PREFIX = "onboard:tg:"
CHAT_LINK_PREFIX = "link:chat:"


def backend_link_key(tg_id: int) -> str:
    return f"{BACKEND_LINK_PREFIX}{tg_id}"


def onboard_key(tg_id: int) -> str:
    return f"{ONBOARD_PREFIX}{tg_id}"


def chat_link_key(user_ref: str | int) -> str:
    return f"{CHAT_LINK_PREFIX}{user_ref}"
