"""BotIdentity — кто пользователь в терминах бизнеса (REQUEST-scope). PURE-данные.

tg_id — из Telegram; backend_user_id — связанный аккаунт на бэкенде (identity-link);
role — для policy (admin-allowlist / бан). Резолвится из Update в provider.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BotIdentity:
    tg_id: int
    backend_user_id: str
    role: str  # "user" | "admin" | "banned"
