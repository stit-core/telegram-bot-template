"""idempotency.py — канон Idempotency-Key: клиент вычисляет ключ сам из доменных частей."""

from __future__ import annotations

import hashlib

# Разделитель частей до хеширования: ("ab","c") и ("a","bc") дают разные ключи.
_SEP = "\x1f"


def idempotency_key(operation: str, *parts: str) -> str:
    """`<operation>:<sha256(parts)>` — ASCII-safe: заголовок уходит в latin-1, юникод в
    частях (имя, адрес) иначе роняет запрос UnicodeEncodeError ещё до отправки."""
    digest = hashlib.sha256(_SEP.join(parts).encode()).hexdigest()
    return f"{operation}:{digest}"
