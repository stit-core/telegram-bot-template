"""Конфиг шаблона: AppConfig (значения приложения) + AppConfigProvider — все *Config в одном месте.

Provider'ы китов свои Config не provide'ят (asymmetry note) — их регистрирует консьюмер. Каждый
kit-конфиг читается `<kit>.new_config()`: невалидный ENV валит старт `<kit>.ConfigError` без
значений полей; AppConfig грузится тем же путём через `pylibinfra.config.load`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from dishka import Provider, Scope, provide
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pylibinfra import cachekit, httpclient, httpkit, logkit, natskit, tgbotkit
from pylibinfra.config import load as load_config

from bot.pkg.http_client import CORE_BACKEND

# Каталог переводов внутри пакета (bot/locales/<locale>/<resource>.ftl). Дефолт-локаль
# шаблона — ru (kit-дефолт — en). Имена ресурсов = префиксы фич (один .ftl на фичу).
_LOCALES_DIR = Path(__file__).parent / "locales"
_I18N_RESOURCES = [
    "common.ftl",
    "start.ftl",
    "profile.ftl",
    "payments.ftl",
    "lang.ftl",
    "notifications.ftl",
    "booking.ftl",
]
_DEFAULT_LOCALE = "ru"


def _csv_ints(value: object) -> object:
    if isinstance(value, str):
        return frozenset(int(item) for item in value.split(",") if item.strip())
    return value


class AppConfig(BaseSettings):
    """Прикладной конфиг (что не покрыто kit'ами): admin-allowlist и идентичность сборки."""

    # case_sensitive: ENV читается по точным alias'ам; голое имя поля (`version`) переменной
    # окружения не соответствует — иначе CI-шный VERSION уехал бы в лог старта.
    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
        env_ignore_empty=True,
        frozen=True,
        case_sensitive=True,
    )

    # csv tg_id админов → роль "admin" в identity; не-число валит старт, а не молчит
    admin_ids: Annotated[frozenset[int], NoDecode] = Field(
        default=frozenset(), validation_alias="APP_ADMIN_IDS"
    )
    version: str = Field(default="dev", validation_alias="SERVICE_VERSION")
    commit: str = Field(default="unknown", validation_alias="GIT_COMMIT")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return _csv_ints(value)


class AppConfigProvider(Provider):
    """Единая точка регистрации всех Config (см. модуль-docstring)."""

    scope = Scope.APP

    @provide
    def app(self) -> AppConfig:
        return load_config(AppConfig)

    @provide
    def log(self) -> logkit.Config:
        return logkit.new_config()

    @provide
    def redact(self) -> logkit.OptionalRedactConfig:
        # перекрывает None-дефолт LogkitProvider: AppConfigProvider зарегистрирован после него
        return logkit.new_redact_config()

    @provide
    def cache(self) -> cachekit.Config:
        return cachekit.new_config()

    @provide
    def http(self) -> httpkit.Config:
        return httpkit.new_config()

    @provide
    def backends(self) -> httpclient.BackendsConfig:
        # HTTPCLIENT_BACKENDS (JSON) — дополнительные бэкенды поверх «core» из кода;
        # одноимённая запись из ENV перекрывает код (deploy-override)
        declared = httpclient.new_backends_config()
        backends = dict(declared.backends)
        if CORE_BACKEND not in backends:
            backends[CORE_BACKEND] = _core_backend()
        return declared.model_copy(update={"backends": backends})

    @provide
    def nats(self) -> natskit.Config:
        return natskit.new_config()

    @provide
    def bot(self) -> tgbotkit.Config:
        # Config frozen: каталог пакета подменяет i18n копией, а BOT_* уже прошли fail-fast
        return tgbotkit.new_config().model_copy(update={"i18n": _i18n_config()})


def _core_backend() -> httpclient.BackendConfig:
    """Единственный internal-бэкенд «core» (profile/booking/payments — один base_url).

    Политика — глобальные HTTPCLIENT_*; второй бэкенд — своя запись в BackendsConfig
    (skill scaffold, backend-port). Пустой base_url валит старт, не первого пользователя.
    """
    core = httpclient.new_config()
    if not core.base_url:
        # свой отказ: pydantic-текст BackendConfig не назвал бы переменную окружения
        raise httpclient.ConfigError(
            f"httpclient: invalid config: backend {CORE_BACKEND!r}: HTTPCLIENT_BASE_URL is required"
        )
    return httpclient.BackendConfig(
        base_url=core.base_url,
        timeout=core.timeout,
        max_retries=core.max_retries,
        retry_wait=core.retry_wait,
        retry_max_wait=core.retry_max_wait,
        retry_non_idempotent=core.retry_non_idempotent,
        max_redirects=core.max_redirects,
        allow_cross_host_redirects=core.allow_cross_host_redirects,
        sse_max_event_bytes=core.sse_max_event_bytes,
        breaker=httpclient.BackendBreakerConfig(
            failure_threshold=core.breaker.failure_threshold,
            recovery_timeout=core.breaker.recovery_timeout,
        ),
    )


def _i18n_config() -> tgbotkit.I18nConfig:
    # BOT_I18N_* из окружения приоритетнее дефолтов шаблона (каталог в пакете, локаль ru);
    # значения — по alias'ам (как ENV), валидация та же: каталог и дефолт-локаль существуют
    return tgbotkit.I18nConfig.model_validate(
        {
            "BOT_I18N_DEFAULT_LOCALE": os.environ.get("BOT_I18N_DEFAULT_LOCALE") or _DEFAULT_LOCALE,
            "BOT_I18N_PATH": os.environ.get("BOT_I18N_PATH") or str(_LOCALES_DIR),
            "BOT_I18N_RESOURCES": _I18N_RESOURCES,
        }
    )
