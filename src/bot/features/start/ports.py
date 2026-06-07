"""ports.py — порты фичи start (Protocol). PURE.

OnboardingStore — узкий порт хранилища флага онбординга и link'а tg→chat (для
notifications). Реализация — над cachekit (gateway.py), связывается в provider.py (DIP).
"""

from __future__ import annotations

from typing import Protocol


class OnboardingStore(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...

    # пишет флаг онбординга И link tg_id→chat_id (его читает notifications.deliver_*)
    async def mark_onboarded(self, tg_id: int, chat_id: int) -> None: ...
