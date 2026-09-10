"""Хелпер pkg-тестов: ApiClient без ретраев на http://backend (respx мокает транспорт httpx)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pylibinfra.httpclient import ApiClient, Client, Config


@pytest.fixture
async def api() -> AsyncIterator[ApiClient]:
    # значения — по alias'ам конфига (как ENV), ретраев нет: транспорт-граница без пауз
    cfg = Config.model_validate(
        {"HTTPCLIENT_BASE_URL": "http://backend", "HTTPCLIENT_MAX_RETRIES": 0}
    )
    client = ApiClient(Client(cfg))
    try:
        yield client
    finally:
        await client.aclose()
