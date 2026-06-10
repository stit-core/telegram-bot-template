"""codec.py — валидация wire-ответов: ломаный контракт бэкенда = UnavailableError."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError
from pylibinfra.httpclient import UnavailableError


def parse[M: BaseModel](model: type[M], raw: object) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise UnavailableError(f"{model.__name__}: contract violation") from exc
