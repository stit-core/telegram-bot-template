"""Composition root — ЕДИНСТВЕННОЕ место сборки бота: ExtensionProvider наполняет точки
расширения kit'ов бизнесом (роутеры/команды/нотификаторы/ErrorUX/локаль/шина/пробы),
build_container собирает провайдеры, run() запускает runner kit'а.

Вся инфра-проводка (storage/middleware/setup_dishka/setup_dialogs/polling|webhook/graceful
shutdown/HTTP-порт) — в kit'е. Порядок провайдеров значим (в dishka побеждает последний):
kit'ы дают ДЕФОЛТЫ своих Optional*/кортежей (LogkitProvider — redact, HttpProvider — пробы,
BotProvider — bundles/ErrorUX/Optional*), поэтому AppConfigProvider и ExtensionProvider
регистрируются ПОСЛЕ них. AiogramProvider обязателен — даёт REQUEST-контекст
(Update/middleware-data), который читает IdentityProvider.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from aiogram import Bot
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from dishka.integrations.aiogram import AiogramProvider
from pylibinfra import healthkit, natskit, tgbotkit
from pylibinfra.cachekit import Cache, CachekitProvider
from pylibinfra.clockkit import ClockProvider
from pylibinfra.httpclient import ApiClientsProvider
from pylibinfra.httpkit import HttpProvider
from pylibinfra.logkit import Logger, LogkitProvider
from pylibinfra.natskit import Config as NatsConfig
from pylibinfra.natskit import NatsProvider, StreamBus
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

from bot.config import AppConfig, AppConfigProvider
from bot.features import booking, lang, notifications, payments, profile, start
from bot.pkg import http_client
from bot.platform.dialogs import AppErrorUX
from bot.platform.identity import IdentityProvider

SERVICE = "bot"


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
    def notifiers(self, cache: Cache, client: aioredis.Redis, log: Logger) -> NotifierBundle:
        return (notifications.build_router(cache, client, log),)

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

    @provide
    def probes(self, bot: Bot, client: aioredis.Redis, conn: natskit.Conn) -> healthkit.Probes:
        # /ready красный без Bot API, Redis (FSM/dedup/identity-link) или NATS (push-события)
        return (tgbotkit.probe(bot), tgbotkit.redis_probe(client), natskit.probe(conn))


def build_container() -> AsyncContainer:
    return make_async_container(
        # ── инфра (pylibinfra): дефолты Optional*/кортежей перекрывают провайдеры ниже ──
        LogkitProvider(),
        ClockProvider(),
        CachekitProvider(),
        ApiClientsProvider(),
        NatsProvider(),
        HttpProvider(autostart=False),  # порт /health,/ready (и вебхука) занимает BotRunner
        BotProvider(),
        AiogramProvider(),
        # ── конфиги: все *Config (после LogkitProvider — перекрывает его redact-дефолт) ──
        AppConfigProvider(),
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
        # ── точки расширения tgbotkit/httpkit (override дефолтов BotProvider/HttpProvider) ──
        ExtensionProvider(),
    )


async def run() -> None:
    container = build_container()
    try:
        log = await container.get(Logger)
        app = await container.get(AppConfig)
        log.info("starting", service=SERVICE, version=app.version, commit=app.commit)
        runner = await container.get(BotRunner)
    except BaseException:
        # сорванный старт (невалидный ENV, недоступный Redis/NATS) отпускает уже открытое
        await container.close()
        raise
    # runner владеет жизненным циклом: на shutdown он зовёт container.close()
    await runner.run()
