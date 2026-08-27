"""wire.py — база wire-моделей ответов бэкендов (схемы пишутся руками, не генерятся)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """extra="forbid": переименованное/лишнее поле бэкенда = ContractError на границе,
    а не молчаливый дрейф; frozen: wire-ответ не мутируется по пути в usecase.
    Поля без бизнес-дефолтов — отсутствие поля в ответе должно падать, не подставляться."""

    model_config = ConfigDict(extra="forbid", frozen=True)
