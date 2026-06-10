"""Composition root — ЕДИНСТВЕННОЕ место сборки бота: ExtensionProvider наполняет точки
расширения tgbotkit бизнесом (роутеры/команды/нотификаторы/ErrorUX/локаль/шина), build_container
собирает провайдеры, run() запускает runner kit'а.

Вся инфра-проводка (storage/middleware/setup_dishka/setup_dialogs/polling|webhook/graceful
shutdown) — в kit'е. Порядок провайдеров важен: BotProvider даёт ДЕФОЛТЫ (Logger=nop,
bundles, ErrorUX, Optional*), поэтому LogkitProvider и ExtensionProvider регистрируются ПОСЛЕ
него (last-wins). AiogramProvider обязателен — даёт REQUEST-контекст (Update/middleware-data),
который читает IdentityProvider.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from dishka.integrations.aiogram import AiogramProvider
from opentelemetry.trace import Tracer
from pylibinfra.cachekit import Cache, CachekitProvider
from pylibinfra.httpclient import ApiClientsProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.natskit import Config as NatsConfig
from pylibinfra.natskit import NatsProvider, StreamBus
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.tgbotkit import (
    BotProvider,
    BotRunner,
    ChainResolver,
    CommandBundle,
    ErrorUX,
    FromCachePref,
    FromUserLanguage,
    LocalePrefStore,
    NotifierBundle,
    OptionalLocaleResolver,
    OptionalStreamBus,
    RouterBundle,
)

from bot.config import AppConfigProvider
from bot.features import booking, lang, notifications, payments, profile, start
from bot.pkg import http_client
from bot.platform.dialogs import AppErrorUX
from bot.platform.identity import IdentityProvider


class ExtensionProvider(Provider):
    """Декларация «что подключить» — рантайм этого в kit'е. Translator не провайдим:
    install_i18n сам построит FluentTranslator из tgbotkit.Config.i18n (см. config.py)."""

    scope = Scope.APP

    @provide
    def routers(self) -> RouterBundle:
        return (start.dialog, profile.dialog, payments.dialog, lang.dialog, booking.dialog)

    @provide
    def commands(self) -> CommandBundle:
        return (start.cmd_spec, *payments.command_specs, lang.cmd_spec)

    @provide
    def notifiers(self, cache: Cache, client: aioredis.Redis) -> NotifierBundle:
        return (notifications.build_router(cache, client),)

    @provide
    def error_ux(self) -> ErrorUX:
        return AppErrorUX()

    @provide
    def resolver(self, cache: Cache) -> OptionalLocaleResolver:
        # явный выбор локали (фича lang) приоритетнее language_code Telegram
        return ChainResolver(FromCachePref(LocalePrefStore(cache)), FromUserLanguage())

    @provide
    def stream_bus(self, bus: StreamBus, nats_cfg: NatsConfig) -> OptionalStreamBus:
        # notifications активны только при включённом JetStream; иначе None → runner их пропустит
        return bus if nats_cfg.jetstream.enabled else None


def build_container() -> AsyncContainer:
    return make_async_container(
        # ── инфра (pylibinfra) ──
        TelemetryProvider(),
        CachekitProvider(),
        ApiClientsProvider(),
        NatsProvider(),
        AiogramProvider(),
        BotProvider(),
        LogkitProvider(),  # реальный Logger — ПОСЛЕ BotProvider (его дефолт nop иначе победит)
        AppConfigProvider(),  # все *Config (asymmetry)
        # ── pkg (клиенты API) ──
        http_client.Provider(),
        # ── платформа (бизнес-общее) ──
        IdentityProvider(),
        # ── фичи (бизнес) ──
        start.Provider(),
        profile.Provider(),
        payments.Provider(),
        lang.Provider(),
        booking.Provider(),
        # ── точки расширения tgbotkit (override дефолтов BotProvider) ──
        ExtensionProvider(),
    )


async def run() -> None:
    container = build_container()
    # резолв Tracer триггерит telemetry.init (выставляет глобальные OTel-providers).
    # container.close() (его зовёт runner на shutdown) сделает telemetry-flush.
    await container.get(Tracer)
    runner = await container.get(BotRunner)
    await runner.run()
