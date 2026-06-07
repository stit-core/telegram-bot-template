"""Транспорт-ошибки бэкенда (не доменные — те живут в фичах). PURE.

BackendClient мапит сетевые сбои/HTTP-статусы в эти типы; gateway фичи ловит их и
переводит в свои sentinel-ошибки (anti-corruption). Шаблон различает «нет данных»
(NotFound/Conflict) и «сервис недоступен» (Unavailable — breaker/timeout/5xx).
"""

from __future__ import annotations


class BackendError(Exception):
    """База ошибок обращения к бэкенду."""


class BackendNotFound(BackendError):
    """404 — ресурса нет."""


class BackendConflict(BackendError):
    """409 — конфликт состояния (напр. идемпотентный повтор с другим телом)."""


class BackendUnavailable(BackendError):
    """Breaker open / timeout / 5xx-после-ретраев / прочий не-доменный сбой."""
