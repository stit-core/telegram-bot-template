"""ports.py — порт хранилища выбранной локали. PURE.

Удовлетворяется tgbotkit.LocalePrefStore (cachekit) — связывается в provider.py. Резолвер
i18n (FromCachePref) читает то же хранилище, поэтому смена языка применяется сразу.
"""

from __future__ import annotations

from typing import Protocol


class LocaleStore(Protocol):
    async def set(self, user_id: int, locale: str) -> None: ...
