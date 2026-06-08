"""Composition root — тонкий: только список провайдеров и запуск runner'а из tgbotkit.

Вся инфра-проводка (storage/middleware/setup_dishka/setup_dialogs/polling|webhook/graceful
shutdown) — в kit'е. Порядок провайдеров важен: BotProvider даёт ДЕФОЛТЫ (Logger=nop,
bundles, ErrorUX, Optional*), поэтому LogkitProvider и ExtensionProvider регистрируются ПОСЛЕ
него (last-wins). AiogramProvider обязателен — даёт REQUEST-контекст (Update/middleware-data),
который читает IdentityProvider.
"""

from __future__ import annotations

from dishka import AsyncContainer, make_async_container
from dishka.integrations.aiogram import AiogramProvider
from opentelemetry.trace import Tracer
from pylibinfra.cachekit import CachekitProvider
from pylibinfra.httpclient import HttpClientProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.natskit import NatsProvider
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.tgbotkit import BotProvider, BotRunner

from bot.config import AppConfigProvider
from bot.extensions import ExtensionProvider
from bot.features import booking, lang, payments, profile, start
from bot.platform.backend import BackendProvider
from bot.platform.identity import IdentityProvider


def build_container() -> AsyncContainer:
    return make_async_container(
        # ── инфра (pylibinfra) ──
        TelemetryProvider(),
        CachekitProvider(),
        HttpClientProvider(),
        NatsProvider(),
        AiogramProvider(),
        BotProvider(),
        LogkitProvider(),  # реальный Logger — ПОСЛЕ BotProvider (его дефолт nop иначе победит)
        AppConfigProvider(),  # все *Config (asymmetry)
        # ── платформа (бизнес-общее) ──
        BackendProvider(),
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
