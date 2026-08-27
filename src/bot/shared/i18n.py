"""render — .ftl-ключ → текст через формат-функцию i18n (I18N_FORMAT_KEY из middleware_data).

PURE: fmt приходит аргументом (Callable кита), сам модуль aiogram/tgbotkit не импортит.
Без i18n (тесты) возвращается сам ключ — flow-тесты матчат ключи, как и лейблы кнопок.
"""

from __future__ import annotations

from typing import Any


def render(fmt: object, key: str, args: dict[str, Any] | None = None) -> str:
    if callable(fmt):
        return str(fmt(key, args or {}))
    return key
