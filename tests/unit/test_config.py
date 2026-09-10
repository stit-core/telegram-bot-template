"""Unit: AppConfig — admin-allowlist парсится в frozenset[int] на валидации (fail-fast, как у
kit'ов: мусор валит старт, а не молчит), загрузка через pylibinfra.config.load даёт ConfigError,
голые имена полей из окружения не читаются."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pylibinfra.config import ConfigError, load

from bot.config import AppConfig

pytestmark = pytest.mark.unit


def test_admin_ids_parsed() -> None:
    cfg = AppConfig.model_validate({"APP_ADMIN_IDS": "10, 20 ,30"})
    assert cfg.admin_ids == frozenset({10, 20, 30})


def test_empty_admin_ids() -> None:
    assert AppConfig.model_validate({"APP_ADMIN_IDS": ""}).admin_ids == frozenset()


def test_garbage_admin_id_rejected() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"APP_ADMIN_IDS": "10,x"})


def test_load_reads_env_and_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ADMIN_IDS", "7")
    monkeypatch.setenv("SERVICE_VERSION", "v1.2.3")
    monkeypatch.setenv("GIT_COMMIT", "abc123")
    cfg = load(AppConfig)
    assert cfg.admin_ids == frozenset({7})
    assert (cfg.version, cfg.commit) == ("v1.2.3", "abc123")

    monkeypatch.setenv("APP_ADMIN_IDS", "7,admin")
    with pytest.raises(ConfigError):
        load(AppConfig)


def test_bare_field_names_are_not_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI-шный VERSION не должен подменять SERVICE_VERSION в логе старта
    monkeypatch.delenv("SERVICE_VERSION", raising=False)
    monkeypatch.setenv("VERSION", "ci")
    assert load(AppConfig).version == "dev"
