"""policy.py — поддерживаемые локали (источник истины контента). PURE.

Дефолт-локаль шаблона — ru (см. config.py). Список синхронен каталогам locales/<lang>/.
"""

from __future__ import annotations

SUPPORTED_LOCALES: tuple[str, ...] = ("ru", "en")


def is_supported(locale: str) -> bool:
    return locale in SUPPORTED_LOCALES
