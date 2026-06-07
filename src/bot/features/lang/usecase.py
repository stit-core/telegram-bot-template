"""usecase.py — смена локали. Знает только порт LocaleStore и policy. PURE-оркестрация.

Невалидную локаль игнорируем (не падаем) — это presentation-инвариант (кнопки только из
поддерживаемых), но usecase защищается на случай прямого вызова.
"""

from __future__ import annotations

from bot.features.lang import policy
from bot.features.lang.ports import LocaleStore


class LangUsecase:
    def __init__(self, store: LocaleStore) -> None:
        self._store = store

    def available(self) -> tuple[str, ...]:
        return policy.SUPPORTED_LOCALES

    async def choose(self, user_id: int, locale: str) -> bool:
        if not policy.is_supported(locale):
            return False
        await self._store.set(user_id, locale)
        return True
