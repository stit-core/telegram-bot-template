"""http_client — клиенты HTTP-API: internal/ (наши бэкенды), external/ (сторонние).

Каждый клиент — полноценная реализация области API (пути + wire-модели) поверх
pylibinfra.httpclient.ApiClient; typed-ошибки (NotFound/Conflict/Unavailable) — kit'а.
"""

from bot.pkg.http_client.provider import CORE_BACKEND
from bot.pkg.http_client.provider import InternalApiProvider as Provider

__all__ = ["CORE_BACKEND", "Provider"]
