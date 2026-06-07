"""backend — общий клиент бэкенда поверх httpclient + транспорт-ошибки."""

from bot.platform.backend.client import BackendClient
from bot.platform.backend.errors import (
    BackendConflict,
    BackendError,
    BackendNotFound,
    BackendUnavailable,
)
from bot.platform.backend.provider import BackendProvider

__all__ = [
    "BackendClient",
    "BackendConflict",
    "BackendError",
    "BackendNotFound",
    "BackendProvider",
    "BackendUnavailable",
]
