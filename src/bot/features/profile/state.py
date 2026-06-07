"""state.py — FSM-состояния и данные диалога profile. PURE (только JSON-примитивы).

Всё, что уезжает в dialog_data, обязано быть JSON-сериализуемым (datetime/Decimal/ORM —
нельзя, упадёт в Redis). Храним черновик ввода, не доменную сущность (она за gateway).
"""

from __future__ import annotations

from pydantic import BaseModel

from bot.platform.dialogs import states

ProfileSG = states.Profile


class ProfileDialogData(BaseModel):
    draft_name: str | None = None

    def has_unsaved(self) -> bool:
        return self.draft_name is not None
