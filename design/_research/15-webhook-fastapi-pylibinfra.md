# 15 — Приём вебхуков на FastAPI/httpkit + граница pylibinfra↔бот

> Артефакт зоны webhook-deploy. Проектирует приём Telegram-вебхуков как **единое
> ASGI-приложение** на `pylibinfra.httpkit` (FastAPI), закрывает GAP из `06 §4.2`
> (httpkit `build_app()` не вешает dishka-lifespan и не зовёт `setup_dishka`),
> и фиксирует чёткую границу «что прячем в pylibinfra vs что остаётся в боте».
>
> Дата: 2026-06-07. Версии: aiogram 3.28, aiogram_dialog 2.6, dishka **1.10.1**,
> pylibinfra (локальный). Исходники httpkit прочитаны целиком.
>
> Метки: **[ПРОВЕРЕНО]** — из локального кода pylibinfra/aiogram-доков, либо из
> офиц. доков/исходников dishka (сверено веб-поиском 2026-06); **[ВЕБ]** —
> подтверждено веб-поиском по dishka 1.10.x; **[ТРЕБУЕТ ПРОВЕРКИ]** — вывод по
> аналогии, проверить на целевых версиях.

---

## 0. TL;DR

- **Один ASGI-app** (`Server.app` из httpkit) хостит `/health` + `/ready` всегда,
  и в webhook-режиме — `POST {WEBHOOK_PATH}` (тонкий: сверка
  `X-Telegram-Bot-Api-Secret-Token` → `dp.feed_update(bot, update)`).
- **GAP закрывается** так: `setup_dishka(container, app)` и mount webhook-роута
  делаются **между** `build_app()` и `Server.start()` (uvicorn-serve), а
  `container.close()` подвешивается на FastAPI-**lifespan** (после `yield`), чтобы
  отработали telemetry-flush/aclose. Текущий `HttpProvider.server` авто-стартует
  uvicorn внутри dishka-фабрики — это **и есть** место поломки: нет окна вставить
  setup+routes до старта (см. §2.3).
- **В pylibinfra (httpkit-PR, S-размер):** (а) `build_app(..., lifespan=...)` +
  first-class dishka-lifespan хелпер; (б) generic `SharedSecretConfig` +
  `shared_secret_guard()` (FastAPI-dependency, **aiogram-agnostic**). Оба —
  чистая инфра, не продуктовая специфика.
- **В боте остаётся** тонкий `platform/webhook/` (≈40 строк): mount роута, валидация
  через httpkit-guard, `feed_update`, set_webhook single-flight, `allowed_updates`.
- **Вердикт: НЕ геморрой.** PR в httpkit ~120–180 строк + тесты; риски известны и
  малы. Без PR бот тоже соберётся (всё навешивается на `server.app` снаружи), но
  closing-контейнера будет «сбоку», а guard продублируется в проде.

---

## 1. Wiring: единое ASGI-приложение

### 1.1 Что хостим

| Эндпоинт | Режим | Источник |
|---|---|---|
| `GET /health` (liveness) | всегда | httpkit `register_health` (есть из коробки) |
| `GET /ready` (readiness, гоняет probes) | всегда | httpkit `register_health` |
| `POST {WEBHOOK_PATH}` (Telegram) | только webhook | бот, `platform/webhook/` |
| `POST /hooks/<backend>` (backend webhook-in, опц.) | опц. | бот, тот же паттерн |

`/health`+`/ready` уже регистрируются в `build_app()` (`server.py:53`), поэтому
**даже polling-режим** может поднять httpkit ради k8s-проб (с `rps=0`, без
бизнес-роутов) — но это опционально (`04 §webhook-vs-polling`).

### 1.2 Цепочка middleware (как есть в httpkit) и её влияние на вебхук

`build_app()` навешивает (снаружи→внутрь):
**CORS → Auth(opt) → RateLimit → MaxBody → RequestID → Recovery → SecurityHeaders →
AccessLog → Metrics → Idempotency(opt)** (`server.py:55–71`). Для вебхука важно:

- **RateLimit per-IP** (`ratelimit.py`, token-bucket по `scope["client"][0]`):
  Telegram шлёт с **пула IP** — per-IP-лимит может бить 429 на легитимных
  апдейтах. В webhook-режиме **`HTTP_RATE_LIMIT_RPS=0`** (off) — это явный
  инвариант (`04 §8 warn4`, `12 §6.2`). [ПРОВЕРЕНО по коду: `rps<=0` → лимитер skip,
  `ratelimit.py:44`]
- **MaxBody 1 MiB** (`maxbody.py`) — норм для Telegram-update; повышать только при
  больших media-payload (там и так file_id, не байты).
- **Idempotency** — НЕ включать для вебхука: ключуется по заголовку
  `Idempotency-Key`, которого у Telegram нет → middleware просто пропускает
  (`idempotency.py:55–58`), reuse-риска нет. Идемпотентность апдейтов решается на
  уровне aiogram (`update_id` dedupe, см. §4 риски), а не httpkit-store.
- **Auth(opt) AuthMiddleware** — это **не** наш путь для secret-token: оно про
  identity в `request.state.auth`, бьёт 401, и навешивается на **весь** app. Для
  Telegram-secret лучше точечный per-route guard (см. §3.2), а не глобальный Auth.

### 1.3 Код проводки (бот, webhook-режим)

```python
# app/bootstrap/webhook.py — собирает контейнер и единый ASGI-app
import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka           # [ВЕБ]
from fastapi import FastAPI

from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpkit import HttpProvider, Server

from app.di import AppConfigProvider, BotProvider, AiogramProvider  # + бизнес-провайдеры
from app.platform.webhook import mount_telegram_webhook, set_webhook_single_flight
from app.config import WebhookConfig


async def build_runtime() -> tuple[Server, AsyncContainer, Bot, Dispatcher]:
    container = make_async_container(
        TelemetryProvider(), LogkitProvider(), HttpProvider(),
        AppConfigProvider(),            # все *Config (asymmetry note), вкл. httpkit.Config
        BotProvider(),                  # Bot + Dispatcher (APP-scope)
        AiogramProvider(),              # dishka.integrations.aiogram provider
        # ...бизнес-провайдеры
    )

    # 1) telemetry init лениво триггерится первым резолвом (Tracer/Meter/Logger)
    # 2) Server резолвится из контейнера — НО его старт нужно отложить (см. §2.3)
    server: Server = await container.get(Server)   # текущий HttpProvider тут уже стартует uvicorn!
    bot: Bot = await container.get(Bot)
    dp: Dispatcher = await container.get(Dispatcher)
    return server, container, bot, dp
```

> ⚠️ Текущий `HttpProvider.server` (`module.py:47–59`) внутри фабрики делает
> `await srv.start()` — uvicorn стартует в момент `container.get(Server)`. Это не
> оставляет окна навесить `setup_dishka` и webhook-роут ДО старта сервера.
> add_middleware после старта = `RuntimeError: Cannot add middleware after an
> application has started` [ВЕБ]. Решение — §2.3 (httpkit-PR `defer_start`/lifespan).

Идеальная форма (после httpkit-PR из §3) — единая dishka-фабрика и lifespan делают
всё:

```python
# app/platform/webhook/asgi.py — целевая форма с httpkit-PR
def build_webhook_app(container, *, cfg, bot, dp, webhook_cfg) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup: единоразово прописать webhook у Telegram (single-flight)
        await set_webhook_single_flight(bot, dp, webhook_cfg)   # бот-код, §4
        yield
        # shutdown: drain уже сделал uvicorn; гасим контейнер → telemetry flush/aclose
        await container.close()                                 # обязателен (06 §5)

    app = build_app(cfg.http, log, probes=probes, lifespan=lifespan)  # ← НОВЫЙ param (PR §3a)
    setup_dishka(container, app)                                # REQUEST-scope на HTTP (см. §2.4)
    mount_telegram_webhook(app, bot=bot, dp=dp, webhook_cfg=webhook_cfg)  # бот, §3-бот
    return app
```

`setup_dishka(container, app)` здесь нужен **только** если в webhook-роуте хочется
`FromDishka`. Для тонкого роута (валидация + feed_update) он **не обязателен** —
см. §2.4. Bot/Dispatcher проще достать из APP-контейнера один раз и замкнуть в
роут через `app.state`/closure, чем тянуть через per-request DI.

---

## 2. Закрытие GAP из 06 §4.2

### 2.1 Суть GAP [ПРОВЕРЕНО]

`build_app()` (`server.py:40–77`) делает `app = FastAPI(title=..., version=...)` —
**без** `lifespan=`. `setup_dishka` нигде в горячем пути не зовётся (есть лишь
тонкая обёртка `httpkit.setup(app, container)` в `module.py:66`, но её надо звать
руками и она НЕ закрывает контейнер). Сам `setup_dishka(container, app)` из dishka
**не регистрирует lifespan** — он только добавляет `ContainerMiddleware` и кладёт
`app.state.dishka_container` [ВЕБ, develop/src/dishka/integrations/fastapi.py].
Значит закрытие контейнера надо подвесить **явно**.

### 2.2 Куда вешать `container.close()` — три варианта, выбран B

| Вариант | Как | Вердикт |
|---|---|---|
| A. FastAPI-lifespan (after `yield`) | `FastAPI(lifespan=...)` → `await container.close()` | **канон dishka** [ВЕБ], но требует прокинуть `lifespan` в `build_app` (PR §3a) |
| B. После `Server.stop()` в bootstrap-finally | `try: ... finally: await server.stop(); await container.close()` | **работает без PR**, держит порядок shutdown явным (§5); выбран как базовый |
| C. `dp.shutdown.register(container.close)` | привязка к Dispatcher | для polling ок; в webhook Dispatcher не «владеет» циклом — не годится |

**Рекомендация:** целевой — **A** (после httpkit-PR, чистый dishka-канон). До PR —
**B** (закрыть контейнер в `finally` главного bootstrap после `server.stop()`),
функционально эквивалентно: uvicorn graceful-drain → затем `container.close()`
гасит APP-ресурсы и flush'ит telemetry (`TelemetryProvider.providers` делает
`shutdown()` на закрытии скоупа, `06 §5`).

### 2.3 Проблема порядка: middleware/routes только ДО старта uvicorn

[ВЕБ] FastAPI/Starlette строит middleware-stack лениво при первом запросе/старте;
`add_middleware` после старта → `RuntimeError: Cannot add middleware after an
application has started`. Цепочка ограничений:

1. `setup_dishka(container, app)` вызывает `app.add_middleware(ContainerMiddleware)`
   → должен быть **до** старта serve.
2. Mount webhook-роута (`@app.post`) добавляет route в `app.router` (не в
   middleware-stack) — формально допустим и позже, но проще тоже до старта.
3. Текущий `HttpProvider.server` стартует uvicorn **внутри** dishka-фабрики
   (`await srv.start()`), т.е. до того, как bootstrap получит `app` → окна нет.

**Решение (минимальный invasive-фикс, PR §3a):** дать `Server`/`HttpProvider`
**отложенный старт** — `Server.start()` НЕ внутри фабрики, а явным шагом bootstrap
после `setup_dishka`+mount. Конкретно: `HttpProvider` отдаёт `Server` **без**
`srv.start()` (или флаг `autostart=False`), а bootstrap зовёт `await server.start()`
сам, последним. Альтернатива без правки фабрики: собрать `Server` напрямую
(`Server(cfg, log, probes=..., autostart=False)`) минуя dishka-фабрику — но это
дублирует проводку и теряет lifecycle контейнера. Поэтому autostart-флаг — в PR.

### 2.4 Двойной REQUEST-scope (FastAPI HTTP-scope vs aiogram Update-scope)

[ПРОВЕРЕНО+ВЕБ] При webhook на ОДИН POST потенциально открываются **два** дочерних
REQUEST-скоупа от общего APP-контейнера:

- **FastAPI ContainerMiddleware** (если вызван `setup_dishka(container, app)`) —
  открывает HTTP-REQUEST-scope на каждый POST.
- **aiogram dishka-middleware** (от `setup_dishka(container, router=dp)`) —
  открывает Update-scope внутри `dp.feed_update`.

Риск: per-update сервис, объявленный `Scope.REQUEST`, при «двойной» проводке может
создаться **дважды** на один логический апдейт (раз в HTTP-scope, раз в
Update-scope) — лишние коннекты/аллокации, потенциально несогласованное состояние.

**Решение (чёткое правило):**
- **Webhook-роут держим ТОНКИМ**: только сверка secret-token + `feed_update`.
  В нём **НЕ** инжектим `FromDishka` бизнес-сервисов. Bot/Dispatcher берём из
  APP-контейнера один раз при сборке app (closure/`app.state`), а не per-request.
- Тогда **FastAPI-`setup_dishka` для вебхука НЕ нужен** — HTTP-REQUEST-scope не
  открывается вовсе, двойного скоупа нет by construction. Вся бизнес-логика и весь
  per-update DI идут **только** через aiogram-Update-scope внутри `feed_update`.
- `setup_dishka(container, app)` подключаем, **только** если у бота есть *другие*
  HTTP-роуты (backend webhook-in, admin-API), которым реально нужен `FromDishka`.
  Эти роуты — отдельные от Telegram-вебхука, там HTTP-REQUEST-scope уместен.

> Вывод: для Telegram-вебхука «двойной scope» — это **не баг, который надо
> чинить рантаймом, а решение проводки**: тонкий роут + DI только через aiogram.

---

## 3. Граница pylibinfra ↔ бот (что куда)

### 3.1 Таблица «что куда»

| Артефакт | Где | Обоснование |
|---|---|---|
| FastAPI app + middleware-цепочка (RED, RequestID, Recovery, SecurityHeaders) | **pylibinfra/httpkit** (есть) | generic HTTP-инфра, framework-agnostic |
| `/health`, `/ready` + Probe | **pylibinfra/httpkit** (есть) | generic |
| uvicorn lifecycle (`Server.start/stop`, graceful) | **pylibinfra/httpkit** (есть) | generic |
| Error-модель Problem+JSON, OTel-instrument | **pylibinfra/httpkit** (есть) | generic |
| `build_app(lifespan=...)` приём lifespan | **pylibinfra/httpkit** (PR §3a) | generic — любой dishka-app хочет закрыть контейнер |
| dishka-lifespan helper (`dishka_lifespan(container)`) | **pylibinfra/httpkit** (PR §3a) | generic — закрытие контейнера не специфично боту |
| **shared-secret header guard** (config + FastAPI-dependency) | **pylibinfra/httpkit** (PR §3b) | generic — любой входящий вебхук (Telegram, GitHub, Stripe, backend) сверяет shared-secret в заголовке. **aiogram-agnostic** |
| `Server` deferred-start (`autostart=False`) | **pylibinfra/httpkit** (PR §3a) | generic — нужно любому, кто mount'ит роуты/setup_dishka после build |
| Telegram webhook-роут (`@app.post`, `Update.model_validate`, `feed_update`) | **бот** `platform/webhook/` | aiogram-специфика — фронтенд-framework, в pylibinfra нельзя (инвариант «никакой продуктовой специфики; aiogram не тащим») |
| `set_webhook` single-flight, `allowed_updates`, `drop_pending_updates` | **бот** `platform/webhook/` | Telegram-Bot-API специфика |
| `Bot`/`Dispatcher`/`AiogramProvider` проводка | **бот** `app/di/` | aiogram-специфика |
| Сборка контейнера, выбор режима polling/webhook | **бот** `app/bootstrap/` | продуктовая композиция |

**Принцип границы:** в pylibinfra идёт **только то, что не знает про aiogram и про
Telegram-Bot-API**. Shared-secret guard сверяет «значение заголовка X == секрет» —
это справедливо для любого provider'а вебхуков, поэтому generic. Парсинг
`Update`/`feed_update`/`set_webhook` — это aiogram, остаётся в боте.

### 3.2 Что остаётся в боте — тонкий `platform/webhook/`

```python
# app/platform/webhook/route.py — ОСТАЁТСЯ В БОТЕ (aiogram-специфика)
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import Depends, FastAPI, Request, Response

from pylibinfra.httpkit import shared_secret_guard, SharedSecretConfig  # ← из PR §3b

def mount_telegram_webhook(
    app: FastAPI, *, bot: Bot, dp: Dispatcher, webhook_cfg
) -> None:
    # generic guard из httpkit: сверяет X-Telegram-Bot-Api-Secret-Token == secret
    guard = shared_secret_guard(
        SharedSecretConfig(
            header="X-Telegram-Bot-Api-Secret-Token",
            secret=webhook_cfg.secret,           # из Vault (12 §1.3)
        )
    )

    @app.post(webhook_cfg.path, dependencies=[Depends(guard)])
    async def telegram_webhook(request: Request) -> Response:
        # тонко: guard уже отбил неверный secret (403). Тут только парс+feed.
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)        # тут отрабатывает aiogram Update-scope DI
        return Response(status_code=200)
```

Этот файл — **единственное**, что бот пишет для приёма вебхуков (≈25–40 строк
вместе с `set_webhook_single_flight`). Всё остальное — из httpkit.

---

## 4. INFRA-HANDOFF: поверхность httpkit-PR (для pylibinfra)

> Это handoff в репозиторий `pylibinfra`. Две независимые фичи в `httpkit`. Обе —
> generic-инфра без продуктовой/aiogram специфики (инвариант соблюдён).

### 4a. dishka-lifespan интеграция в `build_app()`

**Файлы:** `httpkit/server.py`, `httpkit/module.py`.

```python
# server.py — НОВЫЙ параметр lifespan (back-compat: default None → как сейчас)
from contextlib import AbstractAsyncContextManager
from collections.abc import Callable

def build_app(
    cfg: Config,
    log: Logger,
    *,
    instruments: HTTPInstruments | None = None,
    store: IdempotencyStore | None = None,
    auth: AuthExtractor | None = None,
    probes: tuple[Probe, ...] = (),
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,  # ← НОВОЕ
) -> FastAPI:
    app = FastAPI(title=cfg.api_title, version=cfg.api_version, lifespan=lifespan)  # ← проброс
    ...  # остальное без изменений


# server.py — Server получает deferred-start (для окна setup_dishka+mount routes)
class Server:
    def __init__(self, cfg, log=None, *, ..., lifespan=None, autostart=True) -> None:  # ← НОВОЕ
        self.app = build_app(cfg, self._log, ..., lifespan=lifespan)
        ...
        self._autostart = autostart
    # start()/stop() без изменений; если autostart=False — фабрика НЕ зовёт start()
```

```python
# module.py — generic helper + проводка lifespan через DI
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

def dishka_lifespan(container: "AsyncContainer"):
    """Generic FastAPI-lifespan, закрывающий dishka-контейнер после yield
    (telemetry flush, aclose пулов). Не знает ни про aiogram, ни про продукт."""
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await container.close()
    return _lifespan

# HttpProvider.server: отдавать Server с autostart=False, чтобы bootstrap успел
# навесить setup_dishka + routes; либо отдельный provide для deferred-варианта.
```

**Точная поверхность 4a:**
- `build_app(..., lifespan=None)` — новый kw-only параметр.
- `Server(..., lifespan=None, autostart=True)` — два новых kw-only параметра.
- `httpkit.dishka_lifespan(container) -> Callable[[FastAPI], AsyncCM[None]]` — новый
  экспорт. Не импортирует aiogram. Опционально импортирует тип `AsyncContainer`
  лениво/через `TYPE_CHECKING` (dishka уже зависимость httpkit — `module.py`
  импортирует `dishka.integrations.fastapi.setup_dishka`).

**Обоснование generic:** закрытие dishka-контейнера в lifespan — это паттерн из
самих dishka-доков [ВЕБ], нужен **любому** httpkit-сервису на dishka (не только
боту). Никакой aiogram/Telegram-специфики.

### 4b. Generic shared-secret header guard

**Файл:** новый `httpkit/webhook_secret.py` (или дополнить `auth.py`).

```python
# httpkit/webhook_secret.py
import hmac
from collections.abc import Callable
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi import Request
from .error import forbidden  # APIError 403, Problem+JSON

class SharedSecretConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)
    header: str = Field(default="X-Webhook-Secret", validation_alias="HTTP_WEBHOOK_SECRET_HEADER")
    secret: str = Field(default="", validation_alias="HTTP_WEBHOOK_SECRET")

def shared_secret_guard(cfg: SharedSecretConfig) -> Callable[[Request], None]:
    """FastAPI-dependency: сверяет cfg.header в запросе с cfg.secret
    (constant-time). Несовпадение → 403 (APIError Problem+JSON). Пустой secret →
    fail-closed (403), чтобы не открыть вебхук случайно. aiogram-agnostic:
    подходит любому входящему вебхуку (Telegram, GitHub, Stripe, backend-in)."""
    expected = cfg.secret
    header = cfg.header
    async def _guard(request: Request) -> None:
        got = request.headers.get(header, "")
        if not expected or not hmac.compare_digest(got, expected):
            raise forbidden("WEBHOOK_FORBIDDEN", "invalid webhook secret")
    return _guard
```

**Точная поверхность 4b:**
- `httpkit.SharedSecretConfig` — `BaseSettings` (header, secret), env-alias по
  конвенции httpkit (`HTTP_*`). Public API.
- `httpkit.shared_secret_guard(cfg: SharedSecretConfig) -> Callable[[Request], Awaitable[None]]`
  — фабрика FastAPI-dependency. Constant-time (`hmac.compare_digest`), fail-closed.

**Обоснование generic:** «в заголовке X лежит shared-secret, сверить с ожидаемым» —
это **не** Telegram и **не** aiogram. Это паттерн любого webhook-приёмника. Имя
заголовка (`X-Telegram-Bot-Api-Secret-Token`) бот передаёт в конфиге — httpkit его
не знает. Это закрывает aiogram issue #1024 (`07 §2.3`: при ручном пути secret сам
по себе НЕ валидируется) generic-средствами. Существующий `AuthMiddleware`
(`auth.py`) не подходит: он глобальный (на весь app) и про identity→401, а нам
нужен **per-route** 403-guard.

### 4c. Что НЕ выносим (остаётся в боте)

`Update.model_validate`, `dp.feed_update`, `bot.set_webhook`,
`dp.resolve_used_update_types()`, single-flight по `get_webhook_info` — **всё это
aiogram/Telegram-Bot-API**. По инварианту pylibinfra («никакой продуктовой
специфики; aiogram — framework фронтенда») в httpkit **нельзя**. Остаётся в
`app/platform/webhook/`.

---

## 5. Вердикт по сложности: НЕ геморрой

**Объём PR в pylibinfra/httpkit:** ~120–180 строк прод-кода + ~150 строк тестов.

| Шаг | Файл | Строк | Сложность |
|---|---|---|---|
| `build_app(lifespan=)` проброс | `server.py` | ~5 | тривиально |
| `Server(lifespan=, autostart=)` | `server.py` | ~10 | тривиально |
| `dishka_lifespan(container)` helper | `module.py` | ~12 | тривиально |
| `SharedSecretConfig` + `shared_secret_guard` | `webhook_secret.py` (новый) | ~40 | низкая |
| экспорты в `__init__.py` | `__init__.py` | ~6 | тривиально |
| тесты (lifespan close-вызван; guard 200/403/empty-secret) | `tests/` | ~150 | низкая |

Всё **аддитивно** и back-compat (`lifespan=None`, `autostart=True` сохраняют
текущее поведение). Архитектурно чисто ложится на инварианты httpkit (config —
`BaseSettings` с env-alias; guard рендерит Problem+JSON через `forbidden`; provider —
dishka). aiogram в pylibinfra **не** просачивается. → **«не геморрой»**, делаем.

> Можно отгрузить **поэтапно**: бот стартует уже сейчас, навесив `setup_dishka`,
> webhook-роут и закрытие контейнера **снаружи** на `server.app` (вариант B из
> §2.2 + собственный guard в боте). httpkit-PR — рефактор-улучшение, переносящий
> generic-плумбинг в инфру; не блокирует первую версию бота.

### Риски (4 ключевых)

1. **Rate-limit per-IP для пула Telegram-IP.** `RateLimitMiddleware` лимитит по
   client-IP; Telegram шлёт с пула → 429 на легитимных апдейтах. **Митигация:**
   `HTTP_RATE_LIMIT_RPS=0` в webhook-режиме (инвариант, `12 §6.2`). [ПРОВЕРЕНО по
   коду: `rps<=0` отключает лимитер]. Риск **снят** конфигом.
2. **Idempotency reuse / dedupe апдейтов.** httpkit-Idempotency ключуется по
   `Idempotency-Key` — у Telegram его нет, middleware просто пропускает (reuse-риска
   на стороне httpkit нет). НО Telegram **переотправляет** апдейт, если не получил
   200 за таймаут → возможна повторная обработка. **Митигация:** dedupe по
   `update_id` на стороне бота (FSM/Redis), отдавать 200 быстро. Это **бот**, не
   httpkit. [ТРЕБУЕТ ПРОВЕРКИ: нужна ли явная dedupe-логика, или хватает
   быстрого 200 + идемпотентных хендлеров — зависит от сценариев `08`].
3. **Single-flight `set_webhook` при ≥2 инстансах.** `set_webhook` — глобальный
   side-effect на токене; гонка при N репликах. **Митигация (бот, `12 §6.3`):**
   идемпотентность по `get_webhook_info` (звать `set_webhook` только если
   url/secret/allowed_updates отличаются) + опц. Redis-lock. В lifespan-startup
   (§1.3). Риск управляем, код в боте.
4. **`allowed_updates` рассинхрон.** Если `set_webhook(allowed_updates=...)` не
   совпадает с реально зарегистрированными хендлерами (вкл. типы aiogram_dialog) —
   часть апдейтов не придёт. **Митигация:** всегда
   `allowed_updates=dp.resolve_used_update_types()` (`07 §2`, не хардкодить, не из
   env). При rotation secret — перепрописать webhook тем же путём (`12 §2.5`).

Доп. мелкие: (5) **порядок add_middleware vs старт uvicorn** — решается
deferred-start (§2.3); без него `setup_dishka`/mount после старта → RuntimeError
[ВЕБ]. (6) **`MaxBody 1 MiB`** — норм для update, поднимать только при крупных
inline-payload.

---

## 6. Graceful shutdown (webhook-режим)

Порядок (от приёма новых апдейтов к освобождению ресурсов):

```
SIGTERM
  │
  ├─1. uvicorn stop: Server.stop() → should_exit=True
  │     (перестаёт принимать новые соединения; timeout_graceful_shutdown
  │      = HTTP_SHUTDOWN_TIMEOUT, server.py:108,118–124)
  │
  ├─2. drain: uvicorn доигрывает in-flight HTTP-POST'ы (активные feed_update
  │     дорабатывают; их aiogram Update-scope'ы закрываются middleware'ом сами)
  │
  ├─3. (опц.) bot.delete_webhook — обычно НЕ нужно: при rolling deploy следующий
  │     инстанс перепропишет webhook (single-flight). Снимать webhook на каждый
  │     SIGTERM = простой приёма апдейтов. Пропускаем.
  │
  ├─4. container.close(): закрывает APP-ресурсы в обратном порядке —
  │     telemetry.shutdown() (flush OTLP: иначе теряются последние метрики/спаны/
  │     логи, 06 §5), aclose http-клиента, пулы pg/nats, timerkit.stop()
  │
  └─5. bot.session.close(): закрыть aiohttp-сессию Telegram (после container.close,
        т.к. в шаге 4 могли уйти финальные Telegram-вызовы из cleanup'ов)
```

**Почему именно так:**
- **stop→drain→container→session** = «сначала перестать принимать, дать доработать,
  потом гасить ресурсы» (`06 §5` рекомендация). REQUEST-скоупы (HTTP и Update) к
  шагу 4 уже закрыты своими middleware'ами — `container.close()` гасит только
  APP-scope.
- В **варианте A** (lifespan, §2.2) шаги 1–2 делает uvicorn, а `container.close()`
  (шаг 4) — код **после `yield`** в lifespan; `bot.session.close()` тоже в lifespan
  после container.close, либо в bootstrap-finally. В **варианте B** всё явно в
  `try/finally` bootstrap'а после `server.stop()`.
- [ТРЕБУЕТ ПРОВЕРКИ — `06 §5`] относительный порядок `bot.session.close()` vs
  `container.close()`, **если** `Bot`/его сессия резолвятся ИЗ контейнера
  (тогда сессию закроет сам yield-cleanup провайдера `Bot`, и явный
  `bot.session.close()` не нужен / станет двойным). Если `Bot` создаётся вне DI —
  закрывать явно после container.close, как в шаге 5.

---

## Открытые вопросы / проверить на целевых версиях

1. **[ТРЕБУЕТ ПРОВЕРКИ]** Нужен ли явный dedupe по `update_id` (риск 2), или хватает
   быстрого 200 + идемпотентных хендлеров — зависит от сценариев (`08`).
2. **[ТРЕБУЕТ ПРОВЕРКИ]** Порядок `bot.session.close()` vs `container.close()`, если
   `Bot` резолвится из контейнера (§6, `06 §5`).
3. **[ТРЕБУЕТ ПРОВЕРКИ]** Поведение `Server` при `autostart=False` в связке с
   `HttpProvider`-фабрикой (async-generator yield) — что lifecycle контейнера не
   ломается, если `start()` зовётся снаружи.
4. **[ВЕБ, перепроверить на 1.10.1 при имплементации]** `setup_dishka(container, app)`
   только добавляет ContainerMiddleware + `app.state.dishka_container`, lifespan НЕ
   регистрирует (подтверждено по develop-исходнику; зафиксировать на pinned-версии).

---

## Источники

- httpkit (локально): `pylibinfra/src/pylibinfra/httpkit/` — `server.py`, `module.py`,
  `health.py`, `auth.py`, `ratelimit.py`, `idempotency.py`, `security.py`, `error.py`,
  `config.py`, `context.py`, `middleware/*` (прочитаны целиком).
- dishka FastAPI integration — https://dishka.readthedocs.io/en/stable/integrations/fastapi.html
- dishka fastapi.py (develop) — https://github.com/reagento/dishka/blob/develop/src/dishka/integrations/fastapi.py
- FastAPI «Cannot add middleware after application started» — https://github.com/fastapi/fastapi/discussions/11798
- aiogram webhook / secret issue #1024 — https://github.com/aiogram/aiogram/issues/1024
- Локальные research: `04 §8` (httpkit), `06 §4.2/§5` (dishka↔aiogram/fastapi GAP),
  `07 §2` (webhook API), `12 §1.3/§6` (deploy/webhook-топологии, single-flight).
