"""policy.py — чистые решения «можно ли / валидно ли». PURE: на вход уже загруженные данные.

Никаких портов/сети — только бизнес-правила, легко юнит-тестировать. Возвращает Decision
(общий тип из shared) — единообразно во всех фичах.
"""

from __future__ import annotations

from bot.shared.decision import Decision, allow, deny

MAX_NAME_LEN = 64


def can_view_profile(role: str) -> Decision:
    if role == "banned":
        return deny("Профиль недоступен")
    return allow()


def validate_name(raw: str) -> Decision:
    name = raw.strip()
    if not name:
        return deny("Имя не может быть пустым")
    if len(name) > MAX_NAME_LEN:
        return deny(f"Не длиннее {MAX_NAME_LEN} символов")
    return allow()
