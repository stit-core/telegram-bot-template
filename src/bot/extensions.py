"""ExtensionProvider — наполняет точки расширения tgbotkit бизнес-логикой шаблона.

Регистрируется ПОСЛЕ BotProvider (last-wins): override'ит его дефолты (Logger тоже override'ит
LogkitProvider). Здесь шаблон ДЕКЛАРИРУЕТ, что подключить (роутеры/команды/нотификаторы/ErrorUX/
резолвер локали/шину), а рантайм этого — в kit'е. Translator не провайдим: install_i18n сам
построит FluentTranslator из tgbotkit.Config.i18n (locales_dir задаёт config.py).
"""

from __future__ import annotations

import redis.asyncio as aioredis
from dishka import Provider, Scope, provide
from pylibinfra.cachekit import Cache
from pylibinfra.natskit import Config as NatsConfig
from pylibinfra.natskit import StreamBus
from pylibinfra.tgbotkit import (
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

from bot.features import lang, notifications, payments, profile, start
from bot.platform.dialogs import AppErrorUX


class ExtensionProvider(Provider):
    scope = Scope.APP

    @provide
    def routers(self) -> RouterBundle:
        return (start.dialog, profile.dialog, payments.dialog, lang.dialog)

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
