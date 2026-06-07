"""Unit: validate_webapp_user (поверх tgbotkit.validate_init_data) — валид/подделка."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from bot.platform.webapp import InitDataError, validate_webapp_user

pytestmark = pytest.mark.unit

_TOKEN = "123456:test-token"


def _sign(fields: dict[str, str], token: str) -> str:
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def test_valid_init_data_parses_user() -> None:
    init = _sign(
        {
            "auth_date": str(int(time.time())),
            "user": json.dumps({"id": 42, "first_name": "Bob", "username": "bob"}),
        },
        _TOKEN,
    )
    user = validate_webapp_user(init, _TOKEN)
    assert user.id == 42
    assert user.first_name == "Bob"
    assert user.username == "bob"


def test_tampered_init_data_rejected() -> None:
    init = _sign(
        {"auth_date": str(int(time.time())), "user": json.dumps({"id": 42, "first_name": "Bob"})},
        _TOKEN,
    )
    tampered = init.replace("Bob", "Eve")  # значение изменилось → hash не сойдётся
    with pytest.raises(InitDataError):
        validate_webapp_user(tampered, _TOKEN)
