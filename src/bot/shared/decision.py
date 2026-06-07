"""Decision — единый тип результата policy всех фич (allow/deny + причина). PURE.

Аналог доменного решения у go-бэкенда: policy возвращает Decision, usecase решает,
бросать ли sentinel-ошибку. Единообразно во всех фичах — легко юнит-тестировать.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""


def allow() -> Decision:
    return Decision(True)


def deny(reason: str) -> Decision:
    return Decision(False, reason)
