"""errors.py — таксономия ошибок HTTP-границы: реэкспорт typed-ошибок pylibinfra.httpclient.

Единственная дверь фич к ошибкам бэкенда (контракт «фичи не импортят pylibinfra.httpclient»,
importlinter.toml). Иерархия кита: ApiError — база (несёт method/path/status_code/retry_after/
body_snippet); RateLimitedError и ContractError — подклассы UnavailableError (transient для
caller'а); Auth/Forbidden/InvalidRequest — «ретрай не поможет», ловятся catch-all по ApiError.
"""

from pylibinfra.httpclient import (
    ApiError,
    AuthError,
    ConflictError,
    ContractError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    UnavailableError,
)

__all__ = [
    "ApiError",
    "AuthError",
    "ConflictError",
    "ContractError",
    "ForbiddenError",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitedError",
    "UnavailableError",
]
