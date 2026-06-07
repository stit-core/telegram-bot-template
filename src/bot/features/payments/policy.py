"""policy.py — чистая сверка суммы платежа. PURE.

«Не доверять клиенту»: сумму из pre_checkout сверяем с авторитетной ценой бэкенда здесь,
а не принимаем как истину. Любая сумма должна быть положительной.
"""

from __future__ import annotations


def amount_matches(expected: int, got: int) -> bool:
    return got > 0 and got == expected
