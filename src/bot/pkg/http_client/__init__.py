"""http_client — единственная дверь фич к бэкендам по HTTP.

internal/ — клиенты своих бэкендов, external/ — сторонних; errors.py — таксономия
typed-ошибок (реэкспорт кита), wire.py — база wire-моделей (extra="forbid", frozen),
idempotency.py — канон Idempotency-Key, api.py — JsonApi-Protocol поверхности клиента.
Фичи не импортят pylibinfra.httpclient и httpx напрямую (контракты importlinter.toml).
"""

from bot.pkg.http_client.provider import CORE_BACKEND
from bot.pkg.http_client.provider import InternalApiProvider as Provider

__all__ = ["CORE_BACKEND", "Provider"]
