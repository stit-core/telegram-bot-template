# 18 — Граница pylibinfra↔шаблон: новый kit `botkit` (спинной хребет рефайнмента)

> **Главная директива архитектора.** ВСЯ инфраструктура бота сокрыта в `pylibinfra`
> как переиспользуемый kit; в шаблоне — ТОЛЬКО бизнес-логика (фичи/диалоги/контент),
> которая дёргает то, что предоставляет kit. `aiogram`/`aiogram_dialog` — это
> framework/transport (как FastAPI в `httpkit`, asyncpg в `pgkit`), а НЕ продуктовая
> специфика, поэтому они легитимно живут в новом kit'е **опциональной extra**
> (`pylibinfra[bot]`, паттерн `pylibinfra[testkit]` уже есть в `pyproject.toml`).
> Продуктовая специфика (конкретные диалоги, команды, бизнес-флоу, тексты) в kit
> НЕ попадает.
>
> Дата: 2026-06-07. Версии: aiogram 3.28, aiogram_dialog 2.6, dishka 1.10.1,
> pylibinfra (локальный). Источники-якоря (цитируются по путям):
> `design/_research/14` (composition root + раскладка — БОЛЬШАЯ часть переезжает),
> `design/_research/15` (webhook→httpkit: `build_app(lifespan=)`, `shared_secret_guard`),
> `design/_research/04` (telemetry/logkit/httpkit/timerkit/bizmetric API + Provider/Config),
> `design/_research/05` (cachekit/natskit/httpclient), `design/_research/06` (dishka↔aiogram).
> Конвенции: `pylibinfra/README.md` (§Принципы, §Пакеты, §Стабильность API),
> `pylibinfra/CLAUDE.md` (dishka-first, asymmetry note, observability-by-default,
> «минимум зависимостей»), `pylibinfra/pyproject.toml` (extras),
> `pylibinfra/src/pylibinfra/cachekit/module.py` + `httpkit/module.py` (паттерн
> Provider/Config/`new_config`/optional-deps через type-wrappers),
> `go-backend-template/cmd/api/main.go` (три яруса `infra/platform/domain`,
> `group:"health"`/`group:"timer.job"`-реестры).
>
> Метки: **[ПРОВЕРЕНО]** — из локального кода pylibinfra / aiogram(_dialog)-доков;
> **[ТРЕБУЕТ ПРОВЕРКИ]** — вывод по аналогии, проверить на целевых версиях при
> имплементации PR.

---

## 0. TL;DR

- **Имя kit'а: `botkit`** (по конвенции `<area>kit`, нижний регистр, без подчёркиваний —
  `add-kit/SKILL.md` шаг 1). Кандидат `tgkit` отвергнут: kit не product/Telegram-specific
  по контракту (он про aiogram-transport-bootstrap), и `bot` читается так же, как
  `http`/`cache`. Extra — `pylibinfra[bot]`.
- **Что прячет:** `Bot`-фабрика (session + `DefaultBotProperties`), `Dispatcher`-фабрика,
  RedisStorage-проводка (key_builder `with_bot_id`+`with_destiny`, `RedisEventIsolation`
  поверх `cachekit`-`redis.Redis`), **стандартная outer-middleware-цепочка** (request-id
  bind → dedup `update_id` через `cachekit` → throttle → RED+span observability апдейта →
  recovery), регистрация error-handlers (`UnknownIntent`/`UnknownState`→reset),
  `dishka`-`aiogram` setup, **runner** для polling И webhook (webhook поверх `httpkit`
  из 15), graceful shutdown (drain→`container.close`→`session.close`), `tg_updates_*`
  метрики, и вызов `setup_dialogs` (последним) + проброс `BgManagerFactory` в DI.
- **Поверхность для шаблона — 4 реестра-точки расширения** (идиома dishka: provide
  типизированного списка/bundle, как `timerkit.list[PeriodicJob]` и httpkit-`ProbeBundle`):
  `RouterBundle` (фиче-роутеры+диалоги), `CommandBundle` (dispatcher-level хендлеры),
  `NotifierBundle` (notification-подписчики), `list[PeriodicJob]` (джобы, уже из timerkit).
  Плюс `i18n`-каталоги и `ErrorUX`-override.
- **Шаблон тончает до ~3 файлов рантайма:** `__main__.py` (≈3 строки), `app.py`
  (≈25–35 строк: список kit-провайдеров + фиче-провайдеров → `BotRunner`), `config.py`
  (`AppConfigProvider` со всеми `*Config`, asymmetry note). Вся проводка
  `Bot`/`Dispatcher`/storage/middleware/`setup_dishka`/`setup_dialogs`/lifecycle
  уезжает в `botkit`. `platform/webhook/` (≈40 строк из 15) тоже схлопывается в kit.
- **Согласование:** kit-on-kit допустим (`botkit` зависит от `cachekit`/`httpkit`/`natskit`/
  `logkit`/`timerkit` — как `bruteforcekit` зависит от `pgkit`); asymmetry note соблюдена
  (`botkit` не provide'ит свой `Config`); observability-by-default (`tg_updates_*` +
  span на апдейт); «framework не продукт» — никаких текстов/команд/флоу в kit.
- **INFRA-HANDOFF — два PR в pylibinfra:** (1) новый `botkit` + extra `[bot]` (aiogram,
  aiogram_dialog); (2) httpkit-PR из 15 §4 (`build_app(lifespan=)`, `Server(autostart=)`,
  `dishka_lifespan`, `SharedSecretConfig`/`shared_secret_guard`) — `botkit` его консьюмит.

---

## 1. Имя и назначение kit'а

**`botkit`** — bootstrap aiogram-бота как переиспользуемый инфраструктурный примитив:
поднимает `Bot`/`Dispatcher`/FSM-storage, навешивает стандартную observability+resilience
middleware-цепочку, error-recovery, dishka-Update-scope и `aiogram_dialog`, и запускает
бота в одном из двух режимов (polling/webhook) с graceful-shutdown. Аналогия в
экосистеме: `httpkit` относится к FastAPI так же, как `botkit` — к aiogram (оба прячут
framework-bootstrap + middleware-цепочку + lifecycle за `Provider`'ом и `Config`'ом).

**Инвариант границы** (зеркало 15 §3.1): в `botkit` едет только то, что про
aiogram-как-transport и про generic-resilience апдейта. Конкретные тексты, команды,
StatesGroup, бизнес-флоу, маппинг `backend_user_id→chat_id` — НЕ сюда (это продукт,
живёт в шаблоне). `botkit` **знает** про aiogram (это его framework, как FastAPI у
httpkit), но **не знает** про конкретный бот.

Подпакет `pylibinfra/testkit/bottest/` (конвенция `add-kit/SKILL.md` шаг 5,
`cachekit`→`cachetest`): `MockedBot`/`BotClient`-фикстуры, `JsonMemoryStorage`,
`build_test_runner()` — чтобы консьюмер гонял flow-тесты диалогов без Telegram.

---

## 2. Поверхность kit'а — публичный API + Provider(ы) + Config

### 2.1. Публичный API (`pylibinfra/botkit/__init__.py`)

| Символ | Сигнатура / суть | Тип |
|---|---|---|
| `BotProvider` | dishka `Provider`, `Scope.APP`; provide'ит `Bot`, `Dispatcher`, `RedisStorage`, `BgManagerFactory`, `BotRunner` (см. §2.3) | Provider |
| `Config` | `BaseSettings` со всеми env-полями kit'а (§2.4); **public API** | Config (pydantic-settings) |
| `BotRunner` (Protocol) | `async run() -> None` — выбирает polling/webhook по `cfg.mode`, держит lifecycle | runtime-объект |
| `RouterBundle` | `tuple[Router, ...]` — фиче-роутеры/диалоги (точка расширения, §3.1) | type-wrapper |
| `CommandBundle` | `tuple[CommandSpec, ...]` — dispatcher-level хендлеры (команды, pre_checkout, §3.2) | type-wrapper |
| `CommandSpec` | frozen dataclass: `observer: str`, `handler: Callable`, `filters: tuple[...]` (§3.2) | dataclass |
| `NotifierBundle` | `tuple[Notifier, ...]` — notification-подписчики (§3.3) | type-wrapper |
| `Notifier` (Protocol) | `async subscribe(bus: Bus, bg: BgManagerFactory, bot: Bot) -> None` (§3.3) | Protocol |
| `ErrorUX` (Protocol) | `on_unknown_intent`/`on_unknown_state`/`on_unhandled(event, exc, manager?)` — кастомизируемый error-UX (§3.5) | Protocol |
| `default_error_ux() -> ErrorUX` | дефолт: reset-стека на `Unknown*`, «что-то пошло не так» на `on_unhandled` | factory |
| `I18nConfig` | каталоги/дефолт-локаль (`BOT_I18N_*`); опц. (§3.4) | Config |
| `probe(bot) -> Callable[[], Awaitable[None]]` | health-probe (`get_me()`); не provide'ится (тип коллизит, как `cachekit.probe`) | factory |
| `new_config() -> Config` | дешёвый дефолт Config (asymmetry note) | factory |
| `tg_metrics` | reference на `tg_updates_*` инструменты (см. §5) | — |

> Все type-wrapper-bundle'ы — это паттерн «optional/list-зависимость через
> именованный тип» из `httpkit/module.py:15-22` (`OptionalStore`/`ProbeBundle`) и
> `timerkit/module.py:10-11` (`list[PeriodicJob]`): dishka не умеет optional по
> `X | None`, поэтому kit даёт пустой дефолт, а consumer override'ит своим Provider'ом
> ПОСЛЕ `BotProvider` (last-wins).

### 2.2. Что именно сокрыто (таблица «было в шаблоне (14 §4) → стало в botkit»)

| Артефакт (14 §4 `app.py`/15 `platform/webhook/`) | Куда | Деталь |
|---|---|---|
| `Bot(token, default=DefaultBotProperties(parse_mode=HTML))` + `session` | **botkit** `BotProvider.bot` | session-фабрика, `DefaultBotProperties` из Config; APP-scope, yield→`session.close()` |
| `Dispatcher(storage=...)` сборка | **botkit** `BotProvider.dispatcher` | navешивает middleware, error-handlers, `setup_dishka`, `setup_dialogs` (§2.6) |
| `RedisStorage.from_url(redis_dsn)` | **botkit** `BotProvider.storage` | поверх `cachekit`-`redis.Redis` (один инстанс, шарится — 05 §2); key_builder `with_bot_id`+`with_destiny`, `RedisEventIsolation` |
| `RedisEventIsolation(redis=storage.redis)` | **botkit** (внутри §2.6) | распределённая изоляция ≥2 воркера (dialog-ref 01 §10.10) |
| стандартная outer-middleware-цепочка (request-id, dedup, throttle, RED+span, recovery) | **botkit** `middleware/*` | §2.5 — generic, не знает про фичи |
| `dp.errors.register(on_unknown_intent/state, ...)` | **botkit** (§2.6) | дефолт из `default_error_ux()`, override через `ErrorUX` (§3.5) |
| `setup_dishka(container, router=dp)` | **botkit** (§2.6) | dishka-Update-scope; consumer не зовёт руками |
| `setup_dialogs(dp, events_isolation=...)` + `dp["bg_factory"]=...` | **botkit** (§2.6, §6) | СТРОГО последним; `BgManagerFactory` provide'ится в DI |
| `dp.emit_startup()` smoke-инвариант | **botkit** `BotRunner.run` | ловит коллизии StatesGroup на старте (dialog-ref 01 §10.4) |
| polling: `start_polling(allowed_updates=resolve_used_update_types())` + finally | **botkit** `runner/polling.py` | graceful: drain→`container.close`→`session.close` (06 §5) |
| webhook: FastAPI-роут + secret-guard + `feed_update` + `set_webhook` single-flight | **botkit** `runner/webhook.py` | поверх httpkit `build_app(lifespan=)` + `shared_secret_guard` (15 §3.2) |
| `allowed_updates=dp.resolve_used_update_types()` | **botkit** (оба runner'а) | не хардкодить (15 риск 4); kit считает сам |
| `container.close()` lifecycle | **botkit** оба runner'а | обязателен — telemetry flush + aclose (06 §5) |

### 2.3. Provider — `BotProvider` (псевдокод, паттерн `cachekit/module.py`)

```python
# pylibinfra/botkit/module.py
from collections.abc import AsyncIterator
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, RedisEventIsolation, DefaultKeyBuilder
from aiogram_dialog import BgManagerFactory, setup_dialogs
import redis.asyncio as redis
from dishka import Provider, Scope, provide
from dishka.integrations.aiogram import AiogramProvider, setup_dishka

from pylibinfra.logkit import Logger
from .config import Config
from .errorux import ErrorUX, default_error_ux
from .runner import BotRunner, PollingRunner, WebhookRunner
from .middleware import install_standard_middleware

# optional/list-зависимости — type-wrappers (httpkit/module.py:15-22, timerkit:10)
RouterBundle = tuple["Router", ...]
CommandBundle = tuple["CommandSpec", ...]
NotifierBundle = tuple["Notifier", ...]

# botkit не provide'ит Config (asymmetry note, см. cachekit/module.py:13) — caller
# регистрирует Config сам; new_config() ниже. redis.Redis берётся ИЗ cachekit
# (kit-on-kit), один инстанс шарится между aiogram-storage и cachekit (05 §2).
class BotProvider(Provider):
    scope = Scope.APP

    # пустые дефолты точек расширения (consumer override'ит ПОСЛЕ BotProvider)
    @provide
    def default_routers(self) -> RouterBundle: return ()
    @provide
    def default_commands(self) -> CommandBundle: return ()
    @provide
    def default_notifiers(self) -> NotifierBundle: return ()
    @provide
    def default_error_ux(self) -> ErrorUX: return default_error_ux()

    @provide
    async def bot(self, cfg: Config) -> AsyncIterator[Bot]:
        b = Bot(cfg.token, default=DefaultBotProperties(parse_mode=cfg.parse_mode))
        yield b
        await b.session.close()          # после container.close (06 §5)

    @provide
    def storage(self, client: redis.Redis, cfg: Config) -> RedisStorage:
        # с cachekit-redis; with_bot_id+with_destiny — изоляция мульти-бот/мульти-FSM
        return RedisStorage(client, key_builder=DefaultKeyBuilder(
            with_bot_id=True, with_destiny=True))

    @provide
    def dispatcher(
        self, storage: RedisStorage, client: redis.Redis, log: Logger,
        routers: RouterBundle, commands: CommandBundle, errux: ErrorUX, cfg: Config,
    ) -> Dispatcher:
        dp = Dispatcher(storage=storage)
        install_standard_middleware(dp, cfg, log)        # §2.5 (generic цепочка)
        for c in commands:                               # §3.2 dispatcher-level
            dp.observers[c.observer].register(c.handler, *c.filters)
        register_error_handlers(dp, errux)               # §3.5
        for r in routers:                                # §3.1 фиче-роутеры/диалоги
            dp.include_router(r)
        return dp                                        # setup_dishka/dialogs — §2.6

    @provide
    def bg_factory(self, dp: Dispatcher, isolation_src: ...) -> BgManagerFactory:
        return dp["bg_factory"]                          # из setup_dialogs, §6

    @provide
    async def runner(
        self, cfg, bot, dp, container, notifiers: NotifierBundle, log,
    ) -> AsyncIterator[BotRunner]:
        r = WebhookRunner(...) if cfg.mode == "webhook" else PollingRunner(...)
        yield r
        # lifecycle закрывается тут / в BotRunner.run finally (06 §5)
```

> ⚠️ `setup_dishka(container, dp)` и `setup_dialogs(dp)` требуют **готовый
> container**, но container строится из провайдеров (циклическая зависимость на
> уровне сборки). Поэтому они вызываются **не внутри фабрики**, а в `BotRunner.run`
> (или отдельным `bind(container)`-шагом), когда container уже есть — ровно так,
> как httpkit deferred-start решает «add_middleware только до старта» (15 §2.3).
> `BotRunner` получает `container` как `from_context`-зависимость (06 §1).

### 2.4. Config — `botkit.Config` (поля = public API, env-alias по конвенции `BOT_*`)

Конвенция: `BaseSettings`, `extra="ignore"`, `populate_by_name=True`, `validation_alias`
= env-имя; таймауты — float-секунды (04 §0). Per-concern endpoint: `BOT_*` для самого
бота; Redis приходит из `cachekit` (`REDIS_URL`), не дублируется.

| Поле | env-alias | default | Назначение |
|---|---|---|---|
| `token` | `BOT_TOKEN` | **обязателен** | токен Telegram (кандидат на Vault через `config`-kit, 04 §1) |
| `mode` | `BOT_MODE` | `"polling"` | `polling` \| `webhook` |
| `parse_mode` | `BOT_PARSE_MODE` | `"HTML"` | `DefaultBotProperties.parse_mode` |
| `dedup_ttl` | `BOT_DEDUP_TTL` | `600.0` | TTL маркера `update_id` (Telegram ретраит, 05 §2; 15 риск 2) |
| `dedup_enabled` | `BOT_DEDUP_ENABLED` | `True` | вкл/выкл dedup-middleware |
| `throttle_rps` | `BOT_THROTTLE_RPS` | `0` (off) | per-user троттлинг апдейтов (0→off, как httpkit rate-limit) |
| `webhook_path` | `BOT_WEBHOOK_PATH` | `"/tg/webhook"` | путь POST-роута (webhook-режим) |
| `webhook_base_url` | `BOT_WEBHOOK_BASE_URL` | `""` | публичный base для `set_webhook` |
| `webhook_secret` | `BOT_WEBHOOK_SECRET` | `""` | секрет `X-Telegram-Bot-Api-Secret-Token` (Vault) |
| `drop_pending_updates` | `BOT_DROP_PENDING` | `False` | при `set_webhook`/start_polling |
| `shutdown_drain` | `BOT_SHUTDOWN_DRAIN` | `10.0` | сек на drain in-flight апдейтов |

Вложенный `I18nConfig` (опц., §3.4): `BOT_I18N_DEFAULT_LOCALE`, `BOT_I18N_PATH`.
`webhook_*` в polling-режиме игнорируются (как httpkit-поля без сервера).

### 2.5. Стандартная outer-middleware-цепочка (generic, в botkit)

Порядок (снаружи→внутрь; outer на «сырой» Update до фильтров — dialog-ref 01 §5):

| # | Middleware | Что делает | Зависит от |
|---|---|---|---|
| 1 | **RequestIdBind** | `request_id.set(f"tg-{update.update_id}")` (в contextvar `httpclient.reqid`, 05 §1) + `structlog.bind_contextvars(update_id, tg_user_id, chat_id)` (04 §3) | logkit, httpclient.reqid |
| 2 | **Dedup** | `update_id` уже виден? (`cachekit.Cache`/`IdempotencyStore`, короткий TTL `dedup_ttl`) → drop (05 §2; 15 риск 2). Off если `dedup_enabled=False` | cachekit |
| 3 | **Throttle** (opt) | per-user token-bucket в Redis (`INCR`+TTL); off при `throttle_rps=0` | cachekit |
| 4 | **Observability** | span `tg.update {type}` (telemetry.span, 04 §2) + `tg_updates_total{type,result}` + `tg_update_duration_seconds` (§5) | telemetry/bizmetric |
| 5 | **Recovery** | ловит необработанные исключения хендлеров → `tg_update_panics_total`, лог error-span, не валит процесс (аналог httpkit Recovery / natskit panic-recovery 05 §3) | logkit |

Все пять — generic (не знают про фичи/тексты). Дублируют семантику httpkit-цепочки
(RequestID/Metrics/Recovery, 04 §8) на язык aiogram-апдейта. **Также вешаются на
`DIALOG_EVENT_NAME` (`aiogd_update`)** — иначе фоновые рендеры не увидят DI/observability
(14 §4, dialog-ref 01 §5.4).

### 2.6. Порядок проводки Dispatcher (что kit делает строго в этом порядке)

Зеркало 14 §4 `build_dispatcher`, но внутри kit:

1. `install_standard_middleware(dp)` — цепочка §2.5 (на все нужные observers + `aiogd_update`).
2. dispatcher-level хендлеры из `CommandBundle` (§3.2): `dp.observers[obs].register(...)`.
3. error-handlers `UnknownIntent`/`UnknownState`→reset (из `ErrorUX`, §3.5) — **обязательны
   для прода** (dialog-ref 01 §5.5, building-a-template §5).
4. фиче-роутеры/диалоги из `RouterBundle` (§3.1): `dp.include_router(r)`.
5. `setup_dishka(container, router=dp)` — dishka-Update-scope (06 §2). **[deferred:
   нужен container]**.
6. `dp["bg_factory"] = setup_dialogs(dp, events_isolation=RedisEventIsolation(...))` —
   **СТРОГО последним** (dialog-ref 01 §10.1), после всех `include_router`. **[deferred]**.
7. `await dp.emit_startup()` — smoke (коллизии StatesGroup, dialog-ref 01 §10.4).

Шаги 5–7 — в `BotRunner.run` (container уже собран), 1–4 — в `dispatcher`-фабрике.

---

## 3. Точки расширения для шаблона (API подключения бизнес-логики, НЕ трогая инфру)

Идиома для dishka (выбрана осознанно): **типизированный bundle/реестр, который kit
читает как зависимость, а consumer наполняет своим Provider'ом** — это нативный
паттерн pylibinfra (`timerkit.list[PeriodicJob]`, httpkit-`ProbeBundle`/`OptionalStore`,
go-`group:"health"`/`group:"timer.job"` в `cmd/api/main.go`). Не декораторы-с-глобальным-
реестром (теряют DI и тестируемость), не наследование (анти-OCP).

### 3.1. Фиче-роутеры/диалоги → `RouterBundle`

```python
# bot/platform/dialogs/registry.py (ШАБЛОН) — собирает роутеры всех фич
from pylibinfra.botkit import RouterBundle
from dishka import Provider, Scope, provide
from bot.features.start.provider import start_dialog
from bot.features.profile.provider import profile_dialog

class RoutersProvider(Provider):
    scope = Scope.APP
    @provide
    def routers(self) -> RouterBundle:
        return (start_dialog, profile_dialog)   # Dialog является Router (dialog-ref 01 §3)
```

kit делает `include_router` в порядке кортежа (14 §4 шаг 3). Порядок include — за
шаблоном (он владеет приоритетом роутеров).

### 3.2. Dispatcher-level хендлеры (команды, pre_checkout) → `CommandBundle`

Не-диалоговые входы (`/start`, `pre_checkout_query`, `successful_payment` — payments из 16):

```python
# pylibinfra/botkit: CommandSpec
@dataclass(frozen=True)
class CommandSpec:
    observer: str                      # "message" | "pre_checkout_query" | ...
    handler: Callable
    filters: tuple[Any, ...] = ()

# bot/platform/commands.py (ШАБЛОН)
from pylibinfra.botkit import CommandBundle, CommandSpec
from aiogram.filters import CommandStart
from bot.features.start.handlers import on_start_command
from bot.features.payments.handlers import on_pre_checkout

class CommandsProvider(Provider):
    scope = Scope.APP
    @provide
    def commands(self) -> CommandBundle:
        return (
            CommandSpec("message", on_start_command, (CommandStart(),)),
            CommandSpec("pre_checkout_query", on_pre_checkout),
        )
```

kit регистрирует через `dp.observers[spec.observer].register(spec.handler, *spec.filters)`
(шаг §2.6.2). Хендлеры — обычные `@inject`-функции шаблона (06 §3.1).

### 3.3. Notification-подписчики → `NotifierBundle`

Подписка «событие бэкенда (NATS) → сообщение в Telegram» (05 §3). kit запускает их на
старте (long-running, в том же event-loop) и даёт `Conn.drain()` на shutdown:

```python
# pylibinfra/botkit: Notifier
class Notifier(Protocol):
    async def subscribe(self, bus: Bus, bg: BgManagerFactory, bot: Bot) -> None: ...

# bot/features/orders/notifier.py (ШАБЛОН)
class OrderPaidNotifier:                       # удовлетворяет Notifier структурно
    async def subscribe(self, bus, bg, bot):
        async def on_paid(evt: dict) -> None:
            chat_id = await self._resolve_chat(evt["user_id"])   # маппинг — ШАБЛОН (05 §3)
            if chat_id:
                await bot.send_message(chat_id, f"Заказ {evt['order_id']} оплачен")
        await subscribe_json(bus, "orders.paid", on_paid)
```

kit передаёт каждому `Notifier` `Bus` (natskit), `BgManagerFactory` (для фонового старта
диалога получателю, §6) и `Bot` (для прямого `send_message`). Маппинг
`backend_user_id→chat_id` — продуктовая логика, остаётся в шаблоне (05 §3).

### 3.4. i18n-каталоги → `I18nConfig` + опц. middleware

kit опционально ставит i18n-middleware (`aiogram` I18n или fluent), если задан
`I18nConfig` (каталоги/дефолт-локаль). Сами `.ftl`/`.po`-каталоги и выбор локали по
юзеру (`event_from_user.language_code` / профиль с бэкенда) — контент шаблона
(`bot/platform/i18n/` + `locales/`). kit даёт только проводку middleware + `I18NFormat`-
совместимый getter (14 §1 `platform/i18n/`).

### 3.5. Кастомизация error-UX → `ErrorUX`-Protocol

```python
class ErrorUX(Protocol):
    async def on_unknown_intent(self, event, exc) -> None: ...   # дефолт: reset stack
    async def on_unknown_state(self, event, exc) -> None: ...    # дефолт: reset stack
    async def on_unhandled(self, event, exc, manager=None) -> None: ...  # «что-то пошло не так»
```

`default_error_ux()` — прод-безопасный дефолт (reset на `Unknown*` — dialog-ref 01 §5.5).
Шаблон override'ит своим Provider'ом (тексты ошибок на своём языке/брендинге), не трогая
регистрацию error-handlers. `BreakerOpenError` из httpclient (бэкенд недоступен, 05 §1)
маппится тут в «сервис временно недоступен».

### 3.6. Джобы → `list[PeriodicJob]` (уже из timerkit, kit ничего не добавляет)

Напоминания/синки — через **существующий** `timerkit` (04 §6): шаблон provide'ит
`list[PeriodicJob]`, добавляет `TimerkitProvider()` в контейнер. `botkit` про джобы не
знает — это ортогональный kit. (Так же `cmd/api` регистрирует `group:"timer.job"`
отдельно от http.)

---

## 4. Что ОСТАЁТСЯ в шаблоне + обновлённая раскладка репо

### 4.1. Новый тонкий `__main__.py` + `app.py` (псевдокод)

```python
# src/bot/__main__.py — ВЕСЬ файл (≈3 строки)
import asyncio
from bot.app import run
asyncio.run(run())
```

```python
# src/bot/app.py — ВЕСЬ composition root (≈30 строк; было ~90 в 14 §4)
from dishka import make_async_container
# ── ярус infra (pylibinfra kit-провайдеры) ──────────────────────
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpclient import HttpClientProvider     # backend-gateway (05 §1)
from pylibinfra.cachekit import CachekitProvider         # FSM-redis + dedup (05 §2)
from pylibinfra.natskit import NatsProvider              # notifications (опц., 05 §3)
from pylibinfra.timerkit import TimerkitProvider         # джобы (опц., 04 §6)
from pylibinfra.botkit import BotProvider, BotRunner     # ← ВСЯ bot-инфра
# ── config (asymmetry note: kit'ы не provide'ят свой Config) ─────
from bot.config import AppConfigProvider, load_config
# ── ярус platform (тонкая регистрация — точки расширения §3) ─────
from bot.platform.backend.provider import BackendProvider
from bot.platform.identity.provider import IdentityProvider
from bot.platform.dialogs.registry import RoutersProvider     # RouterBundle (§3.1)
from bot.platform.commands import CommandsProvider            # CommandBundle (§3.2)
from bot.platform.errorux import ErrorUXProvider              # ErrorUX (§3.5)
from bot.platform.jobs import JobsProvider                    # list[PeriodicJob] (§3.6)
# ── ярус features (бизнес-провайдеры) ───────────────────────────
from bot.features.start.provider import StartProvider
from bot.features.profile.provider import ProfileProvider
from bot.features.orders.provider import OrdersProvider       # + NotifierBundle (§3.3)


def build_container():
    cfg = load_config()
    return make_async_container(
        TelemetryProvider(), LogkitProvider(), HttpClientProvider(),
        CachekitProvider(), NatsProvider(), TimerkitProvider(),
        BotProvider(),                       # ← Bot/Dispatcher/storage/mw/lifecycle
        AppConfigProvider(cfg),              # ВСЕ *Config (asymmetry note, 06 §1)
        BackendProvider(), IdentityProvider(),
        # точки расширения (override дефолтов BotProvider — last-wins) ──
        RoutersProvider(), CommandsProvider(), ErrorUXProvider(), JobsProvider(),
        StartProvider(), ProfileProvider(), OrdersProvider(),
        context={"mode": "polling"},         # из_context для BotRunner
    )


async def run() -> None:
    container = build_container()
    runner: BotRunner = await container.get(BotRunner)   # триггерит telemetry init
    await runner.run()                                   # polling/webhook + lifecycle
    # graceful shutdown (drain→container.close→session.close) — ВНУТРИ runner.run
```

Шаблон больше **не пишет**: ни `Bot(...)`, ни `Dispatcher(...)`, ни `RedisStorage`, ни
middleware, ни `setup_dishka`, ни `setup_dialogs`, ни `run_polling`/`run_webhook`, ни
`container.close()`. Всё это — в `botkit`.

### 4.2. Обновлённая раскладка репо (что в kit / что в шаблоне)

```
telegram-bot-template/
├── pyproject.toml         # deps: pylibinfra[bot] (тащит aiogram/aiogram_dialog транзитивно)
├── importlinter.toml      # контракты границ (14 §5)
├── src/bot/
│   ├── __main__.py        # ← ТОНКИЙ (3 строки)
│   ├── app.py             # ← ТОНКИЙ composition root (§4.1)
│   ├── config.py          # AppConfigProvider + все *Config (вкл. botkit.Config) — ОСТАЁТСЯ
│   ├── platform/          # специфично проекту, НЕ фича — ОСТАЁТСЯ (тоньше)
│   │   ├── identity/      #   Update→BotIdentity (REQUEST-scope) — ОСТАЁТСЯ (продукт)
│   │   ├── backend/       #   общий httpclient.Client-обёртка к бэкенду — ОСТАЁТСЯ (продукт)
│   │   ├── dialogs/
│   │   │   ├── states.py  #   ЕДИНЫЙ каталог StatesGroup всех фич — ОСТАЁТСЯ (14 §2.1)
│   │   │   ├── common.py  #   переиспользуемые виджеты («В меню») — ОСТАЁТСЯ (контент)
│   │   │   └── registry.py#   RoutersProvider → RouterBundle (§3.1) — ОСТАЁТСЯ (тонкая регистрация)
│   │   ├── commands.py    #   CommandsProvider → CommandBundle (§3.2) — ОСТАЁТСЯ
│   │   ├── errorux.py     #   ErrorUXProvider (тексты ошибок) — ОСТАЁТСЯ (контент)
│   │   ├── jobs.py        #   JobsProvider → list[PeriodicJob] (§3.6) — ОСТАЁТСЯ
│   │   └── i18n/+locales/ #   каталоги переводов — ОСТАЁТСЯ (контент)
│   │   # ⚠ platform/webhook/ из 15 — УДАЛЁН (уехал в botkit.runner.webhook)
│   ├── features/          # ФИЧИ — ОСТАЮТСЯ ЦЕЛИКОМ (вся бизнес-логика, 14 §2)
│   │   ├── start/  profile/  orders/ ...
│   │   │   # state·dto·errors·policy·ports·usecase·gateway·dialogs·getters·
│   │   │   # handlers·views·provider·adapters (+notifier для §3.3)
│   └── shared/            # pure-утилиты (decision/result/types) — ОСТАЁТСЯ
└── tests/                 # unit (моки портов) + flows (botkit.testkit.bottest) — ОСТАЁТСЯ
```

**Исчезает из шаблона (уезжает в botkit):** вся проводка `app.py`-рантайма
(Bot/Dispatcher/storage/middleware/setup_dishka/setup_dialogs/runner/lifecycle) +
`platform/webhook/` целиком. **Остаётся в шаблоне:** `features/` (вся бизнес-логика),
`platform/` контент+тонкая регистрация (states-каталог, виджеты, тексты ошибок, i18n,
4 Provider'а точек расширения), `config.py`, `shared/`. Раскладка фичи (14 §2) не
меняется — kit прячет только composition root и transport.

---

## 5. Согласование с принципами pylibinfra + extras

| Принцип (README/CLAUDE) | Как соблюдён в `botkit` |
|---|---|
| **Никакой продуктовой специфики** | kit знает про aiogram (framework, как FastAPI у httpkit), НЕ про конкретный бот: ни текстов, ни команд, ни StatesGroup, ни `user_id→chat_id`. Всё это — через точки расширения из шаблона (§3). |
| **dishka-first** | `BotProvider` — единственная точка входа; consumer собирает контейнер из kit-провайдеров (CLAUDE §Стиль). |
| **Asymmetry note** | `BotProvider` **не** provide'ит `botkit.Config` (как `cachekit`/`httpkit`/`timerkit`); caller регистрирует в `AppConfigProvider`; есть `new_config()` (cachekit/module.py:50). |
| **Observability-by-default** | эмитит `tg_updates_total{type,result}`, `tg_update_duration_seconds`, `tg_update_panics_total`, `tg_updates_deduped_total` + span `tg.update {type}` на апдейт (через глоб. `metrics.get_meter("app")`/`telemetry.span`, no-op без telemetry — 04 §0). Имена не-biz (инфра-метрики, как `http_requests_total`), но при желании — `biz_tg_*` через `bizmetric` в хендлерах шаблона (04 §7). |
| **async-first** | весь I/O — asyncio (aiogram/redis.asyncio/httpx). |
| **pydantic-settings Config = public API** | `botkit.Config` (+`I18nConfig`) попадают в README §Стабильность API; env-alias `BOT_*` менять = breaking. |
| **Минимум зависимостей** | новые сторонние deps — `aiogram`, `aiogram_dialog` — **обсуждаются** (CLAUDE §Сначала спросить) и едут в **опциональную extra `[bot]`**, не в core (как `testkit`). dishka/redis/httpx/fastapi — уже core. |
| **kit-on-kit** | **допустим** — прецедент `bruteforcekit`→`pgkit` (05 §6) и `cachekit.IdempotencyStore`→httpkit (README §Пакеты). `botkit` зависит от `cachekit` (FSM-redis/dedup), `logkit` (Logger), `httpkit` (webhook-runner), `natskit` (notifier-проводка опц.), `telemetry`/`bizmetric` (метрики). Все — внутри pylibinfra, без внешних связей. |

### extras в `pyproject.toml` (PR §1)

```toml
[project.optional-dependencies]
# botkit шипится в пакете, но aiogram/aiogram_dialog нужны только тем, кто строит
# Telegram-бота: `uv add "pylibinfra[bot]"` (паттерн testkit)
bot = [
    "aiogram>=3.28,<4",
    "aiogram-dialog>=2.6,<3",
]
```

`botkit/module.py` импортирует aiogram лениво / гейтит понятной ошибкой при отсутствии
extra (как делают optional-импорты). Core-зависимости (`redis`, `fastapi`, `dishka`,
`httpx`) уже в `[project].dependencies` — extra добавляет только два aiogram-пакета.

### Что эмитит `botkit` (для README §Что эмитит каждый пакет)

| Пакет | Метрики | Спаны |
|---|---|---|
| `botkit` | `tg_updates_total{type,result}`, `tg_update_duration_seconds`, `tg_update_panics_total`, `tg_updates_deduped_total` | per-update span `tg.update {type}` (trace-context из webhook-POST сшивается с httpkit-span) |

---

## 6. aiogram_dialog-увязка

- **`setup_dialogs` зовёт `botkit`** (не шаблон) — СТРОГО последним, после всех
  `include_router` из `RouterBundle` (§2.6.6, dialog-ref 01 §10.1). Шаблон не касается
  `setup_dialogs` вообще — он только отдаёт `Dialog`'и через `RouterBundle`. Это снимает
  с шаблона риск «забыл вызвать последним» / «вызвал дважды» (dialog-ref 01 §10.1).
- **`events_isolation`** — `botkit` собирает `RedisEventIsolation(redis=<cachekit redis>)`
  (распределённая изоляция, обязательна при ≥2 воркера — dialog-ref 01 §10.10; 14 §4).
  Шаблон про изоляцию не думает.
- **`BgManagerFactory`** — то, что возвращает `setup_dialogs` (dialog-ref 01 §2,
  06-bgmanager §2). `botkit` provide'ит его в DI (`BotProvider.bg_factory`) и кладёт в
  `dp["bg_factory"]`. Используется в двух местах: (а) внутри хендлеров доступен как
  `dialog_bg_factory` через middleware (dialog-ref 06 §2) — шаблон инжектит штатно;
  (б) в **notification-подписчиках** (§3.3) — `botkit` передаёт `BgManagerFactory`
  каждому `Notifier`, чтобы тот мог `.bg(bot, user_id=..., chat_id=..., load=True)`
  и фоном стартовать/обновить диалог получателю вне апдейта (06-bgmanager §2,
  сигнатура `bg(bot, user_id, chat_id, ...)`; `load=True` для реального Chat/User —
  06-bgmanager §7). Маппинг `backend_user_id→(user_id,chat_id)` — продукт (шаблон).
- **Сосуществование kit ↔ dialog-механика:** `botkit` владеет проводкой
  (`setup_dishka`→`setup_dialogs`→`emit_startup` в правильном порядке, §2.6), а
  декларация диалогов (`Dialog(Window(...))`, getters/handlers с
  `dishka.integrations.aiogram_dialog.FromDishka`) — целиком в фичах шаблона (14 §2,
  06 §3.2). Встроенный `about_dialog` подключается `setup_dialogs` автоматически
  (dialog-ref 01 §10.5) — kit это учитывает при `emit_startup`-smoke. Middleware-цепочка
  `botkit` (§2.5) вешается и на `aiogd_update`, чтобы фоновые рендеры видели DI/observability
  (14 §4, dialog-ref 01 §5.4).

---

## 7. INFRA-HANDOFF (в репозиторий `pylibinfra`)

Два PR. PR-B (httpkit) — это handoff из 15 §4, `botkit` его консьюмит; делается первым
или параллельно.

### PR-A — новый kit `botkit` + extra `[bot]` (через `/add-kit`)

**Размер:** M (новый пакет ~400–550 строк прод + ~250 тестов + testkit-сабпакет).
**Файлы:**
- `src/pylibinfra/botkit/__init__.py` — реэкспорт API §2.1 + `__all__` + package-doc.
- `src/pylibinfra/botkit/module.py` — `BotProvider` (§2.3), `new_config`, `probe`.
- `src/pylibinfra/botkit/config.py` — `Config`+`I18nConfig` (§2.4, public API).
- `src/pylibinfra/botkit/storage.py` — RedisStorage+key_builder+`RedisEventIsolation` поверх cachekit-redis.
- `src/pylibinfra/botkit/middleware/*` — стандартная цепочка §2.5 (request-id/dedup/throttle/observability/recovery).
- `src/pylibinfra/botkit/errorux.py` — `ErrorUX`-Protocol + `default_error_ux` + `register_error_handlers` (§3.5).
- `src/pylibinfra/botkit/extension.py` — `RouterBundle`/`CommandBundle`/`CommandSpec`/`NotifierBundle`/`Notifier` (§3).
- `src/pylibinfra/botkit/runner/{polling.py,webhook.py}` — `BotRunner` + deferred setup_dishka/dialogs (§2.6, lifecycle 06 §5).
- `src/pylibinfra/botkit/metrics.py` — `tg_updates_*` инструменты (§5).
- `src/pylibinfra/testkit/bottest/*` — `MockedBot`/`BotClient`/`JsonMemoryStorage`/`build_test_runner` (§1).
- `pyproject.toml` — extra `[bot]` (aiogram, aiogram_dialog).
- `README.md` — строка в §Пакеты + §Что эмитит + §Стабильность API (`botkit.Config`, `botkit.I18nConfig`).

**Зависимости (обсудить с пользователем — CLAUDE §Сначала спросить):** `aiogram>=3.28,<4`,
`aiogram-dialog>=2.6,<3` — только в extra `[bot]`. dishka-интеграции
(`dishka.integrations.aiogram`/`aiogram_dialog`) — уже в dishka (core dep).

**Инвариант соблюдён:** в core ничего aiogram-специфичного не просачивается (только extra);
продуктовой специфики в kit нет (§5).

### PR-B — httpkit (handoff из 15 §4, `botkit.runner.webhook` его консьюмит)

**Размер:** S (~120–180 строк + ~150 тестов, 15 §5). **Файлы:** `httpkit/server.py`,
`httpkit/module.py`, `httpkit/webhook_secret.py` (новый), `httpkit/__init__.py`.
**Поверхность:** `build_app(..., lifespan=None)`; `Server(..., lifespan=None, autostart=True)`;
`dishka_lifespan(container)`; `SharedSecretConfig`+`shared_secret_guard` (generic,
aiogram-agnostic — 15 §4b). `botkit.runner.webhook` использует `build_app(lifespan=
dishka_lifespan(container))` + `shared_secret_guard(SharedSecretConfig(header=
"X-Telegram-Bot-Api-Secret-Token", secret=cfg.webhook_secret))`, а
`Update.model_validate`+`feed_update`+`set_webhook` — внутри `botkit` (это aiogram, 15 §4c).

> Поэтапность (15 §5): без PR-B `botkit.runner.webhook` навешивает `setup_dishka`+роут+
> закрытие контейнера снаружи на `server.app` (вариант B, 15 §2.2) и держит свой guard.
> PR-B — рефактор-улучшение, переносящий generic-плумбинг в инфру; не блокирует первую
> версию `botkit`.

---

## 8. Решения и риски (сухой остаток)

1. **Имя `botkit` (не `tgkit`).** `bot` = aiogram-transport-bootstrap (как `http`=FastAPI),
   не Telegram-продукт; читается ровно. Extra `pylibinfra[bot]`.
2. **Deferred setup_dishka/dialogs.** `setup_dishka`/`setup_dialogs` требуют готовый
   container → вызываются в `BotRunner.run`, не в фабрике (зеркало httpkit deferred-start,
   15 §2.3). **[ТРЕБУЕТ ПРОВЕРКИ]** lifecycle при этом порядке.
3. **kit-on-kit принят** (`botkit`→cachekit/httpkit/natskit/logkit/timerkit) — прецедент
   `bruteforcekit`→`pgkit`. Риск связности kit'ов; митигация — зависимости только внутри
   pylibinfra, через публичные Provider'ы/порты.
4. **Точки расширения = type-wrapper-bundles** (RouterBundle/CommandBundle/NotifierBundle +
   `list[PeriodicJob]`), не декораторы — сохраняет DI/тестируемость/OCP; нативно для dishka
   (timerkit/httpkit) и go-`group:"..."`.
5. **Риск «слишком толстый kit».** `botkit` шире httpkit (прячет ещё и dialog/storage/runner).
   Митигация: всё product-specific вынесено в 4 реестра+ErrorUX+i18n; kit не растёт от
   новых фич. **[ТРЕБУЕТ ПРОВЕРКИ]** не утекает ли что-то Telegram-Bot-API-специфичное
   (set_webhook/allowed_updates) — оно остаётся, но это **aiogram-framework**, не продукт
   (граница 15 §3.1: aiogram легитимен в kit'е, конкретный бот — нет).
6. **Шаблон тончает радикально:** рантайм = `__main__.py`(3) + `app.py`(~30) + `config.py`;
   вся бизнес-логика — в `features/` (не меняется, 14 §2), вся проводка — за `BotProvider`.
</content>
</invoke>
