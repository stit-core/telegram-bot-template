"""Хелпер pkg-тестов: ApiClient без ретраев на http://backend (respx мокает httpx)."""

from __future__ import annotations

import httpx
import pytest
from pylibinfra.httpclient import ApiClient, Client, Config


@pytest.fixture
def api() -> ApiClient:
    cfg = Config(base_url="http://backend", max_retries=0)
    http = httpx.AsyncClient(base_url="http://backend")
    return ApiClient(Client(cfg, http))
