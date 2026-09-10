"""Валидация Telegram WebApp initData + извлечение пользователя.

HMAC-проверку и свежесть делает kit (tgbotkit.validate_init_data) — НЕ дублируем алгоритм.
Здесь — продуктовый слой: распарсить проверенное поле user в доменный WebAppUser. Канал
доставки — путь B (свой бэкенд-эндпоинт принимает initData; в webhook-режиме поверх httpkit).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import SecretStr
from pylibinfra.tgbotkit import InitDataError, validate_init_data


@dataclass(frozen=True, slots=True)
class WebAppUser:
    id: int
    first_name: str
    username: str | None = None


def validate_webapp_user(
    init_data: str, bot_token: SecretStr | str, *, max_age: int = 300
) -> WebAppUser:
    # demo-only: reference валидатор initData; нет живого вызывающего — wire или prune.
    fields = validate_init_data(init_data, bot_token, max_age=max_age)  # raise InitDataError
    raw_user = fields.get("user")
    if not raw_user:
        raise InitDataError("init data has no user")
    try:
        data = json.loads(raw_user)
    except (TypeError, ValueError) as exc:
        raise InitDataError("init data user is not valid JSON") from exc
    uid = data.get("id")
    if not isinstance(uid, int):
        raise InitDataError("init data user has no id")
    return WebAppUser(
        id=uid, first_name=str(data.get("first_name", "")), username=data.get("username")
    )
