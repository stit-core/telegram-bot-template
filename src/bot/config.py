"""Конфиг шаблона: AppConfig (значения приложения) + AppConfigProvider.

Асимметрия dishka: Provider'ы китов НЕ provide'ят свои Config (чтобы не навязывать
источник) — их регистрирует caller. AppConfigProvider собирает ВСЕ *Config в одном
месте: kit'овые (telemetry/logkit/cachekit/httpclient/natskit/tgbotkit) + AppConfig.
Все они читают env через pydantic-settings; на проде секреты подаёт vault-agent в env.
"""

from __future__ import annotations

import os
from pathlib import Path

from dishka import Provider, Scope, provide
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pylibinfra.cachekit import Config as CacheConfig
from pylibinfra.httpclient import Config as HttpConfig
from pylibinfra.logkit import Config as LogConfig
from pylibinfra.logkit import RedactConfig
from pylibinfra.natskit import Config as NatsConfig
from pylibinfra.telemetry import Config as TelConfig
from pylibinfra.tgbotkit import Config as BotConfig
from pylibinfra.tgbotkit import I18nConfig

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
_DEFAULT_SERVICE_NAME = "telegram-bot"


class AppConfig(BaseSettings):
    """Прикладной конфиг (то, что не покрыто kit'ами): admin-allowlist и т.п."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # csv tg_id админов → роль "admin" в identity
    admin_ids: str = Field(default="", validation_alias="APP_ADMIN_IDS")

    def admin_id_set(self) -> frozenset[int]:
        return frozenset(int(x) for x in self.admin_ids.split(",") if x.strip().isdigit())


class AppConfigProvider(Provider):
    """Единая точка регистрации всех Config (см. модуль-docstring)."""

    scope = Scope.APP

    @provide
    def app(self) -> AppConfig:
        return AppConfig()

    @provide
    def telemetry(self) -> TelConfig:
        # service_name у telemetry обязателен — даём фолбэк, env (OTEL_SERVICE_NAME) приоритетнее.
        return TelConfig(service_name=os.environ.get("OTEL_SERVICE_NAME", _DEFAULT_SERVICE_NAME))

    @provide
    def logging(self) -> LogConfig:
        return LogConfig()

    @provide
    def redact(self) -> RedactConfig:
        return RedactConfig()

    @provide
    def cache(self) -> CacheConfig:
        return CacheConfig()

    @provide
    def http(self) -> HttpConfig:
        return HttpConfig()

    @provide
    def nats(self) -> NatsConfig:
        return NatsConfig()

    @provide
    def bot(self) -> BotConfig:
        cfg = BotConfig()
        # i18n включаем из коробки: каталог — внутри пакета, дефолт-локаль ru.
        # env (BOT_I18N_*) приоритетнее значений по умолчанию шаблона.
        cfg.i18n = I18nConfig(
            default_locale=os.environ.get("BOT_I18N_DEFAULT_LOCALE", _DEFAULT_LOCALE),
            locales_dir=os.environ.get("BOT_I18N_PATH") or str(_LOCALES_DIR),
            resources=_I18N_RESOURCES,
        )
        return cfg
