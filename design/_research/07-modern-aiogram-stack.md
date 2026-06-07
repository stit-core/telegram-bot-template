# 07 — Современный стек и тулинг aiogram-бота (зона G)

> Исследование на ~июнь 2026. Версии проверены по PyPI/официальным докам/GitHub.
> Всё, что НЕ удалось подтвердить веб-поиском, помечено «требует проверки».
> Baseline для согласования: `pylibinfra/pyproject.toml`
> (`/root/git/sftbmb/sftbmb-core/pylibinfra/pyproject.toml`).
> Референс aiogram_dialog: `telegram-bot-template/aiogram-dialog-docs/` (зафиксировано `aiogram>=3.14.0`).

---

## 1. Зависимости: версия → роль → согласовано ли с pylibinfra

Питон: pylibinfra требует `>=3.12`; в окружении стоит 3.13. aiogram 3.28 поддерживает
`>=3.10,<3.15`. Берём общий таргет **py312** (как ruff/mypy в pylibinfra).

| Зависимость | Актуальная версия (июнь 2026) | Рекомендуемый пин | Роль | Согласовано с pylibinfra | Источник |
|---|---|---|---|---|---|
| **aiogram** | **3.28.2** (2026-05-10) | `aiogram>=3.28,<4` | Ядро: Bot API, Dispatcher, FSM, middleware, webhook | новая (нет в pylibinfra) — спец. для бота | [PyPI](https://pypi.org/project/aiogram/) |
| **aiogram-dialog** | **2.6.0** (2026-03-22) | `aiogram-dialog>=2.6,<3` | UI-фреймворк диалогов/окон поверх aiogram | новая; требует `aiogram` v3.x (ниж. граница из docs — `>=3.14`, см. референс) | [PyPI](https://pypi.org/project/aiogram_dialog/) |
| **dishka** | **1.10.1** (2026-04-25) | как в pylibinfra: `dishka>=1.10,<2` | DI + lifecycle (есть интеграция `dishka.integrations.aiogram`) | **да** (`dishka>=1.10,<2`) | [PyPI](https://pypi.org/project/dishka/) |
| **pydantic** | **2.x** (релиз 2026-05-06) | `pydantic>=2.13,<3` | Модели/валидация (aiogram сам на pydantic v2) | **да** | [PyPI](https://pypi.org/project/pydantic/) |
| **pydantic-settings** | **2.14.1** (2026-05-08) | `pydantic-settings>=2.14,<3` | Конфиг бота из env/секретов | **да** | [PyPI](https://pypi.org/project/pydantic-settings/) |
| **redis** (redis-py) | **8.x** (релиз 2026-05-28) | `redis>=8,<9` | FSM RedisStorage + изоляция (через `redis.asyncio`) | **да** (`redis>=8,<9`) | [PyPI](https://pypi.org/project/redis/) |
| **httpx** | **0.28.1** (2024-12-06; 1.0 в dev) | `httpx>=0.28,<1` | Внешние HTTP-вызовы (не для Telegram — там AiohttpSession) | **да** | [PyPI](https://pypi.org/project/httpx/) |
| **structlog** | **26.1.0** (2026-06-06) | `structlog>=26.1,<27` | Структурное логирование (+ otel bridge) | **да** | [PyPI](https://pypi.org/project/structlog/) |
| **opentelemetry-\*** (api/sdk/exporter) | **1.42.x** (instrumentation `0.63bX`) | как pylibinfra `>=1.42,<2` | Трейсинг/метрики | **да** (наследуем через pylibinfra) | (через pylibinfra) |
| **fastapi** | **0.136.1** | `fastapi>=0.136,<1` | Web-слой (опц.: webhook-эндпоинт, healthcheck) | **да** | [PyPI](https://pypi.org/project/fastapi/) |
| **uvicorn** | **0.49.x** | `uvicorn[standard]>=0.49,<1` | ASGI-сервер (если webhook через FastAPI) | **да** | (через pylibinfra) |
| **uv** | **0.11.19** (2026-06-03) | tool, не пин в deps | Пакетmenеджер/lockfile | tooling (как pylibinfra) | [PyPI](https://pypi.org/project/uv/) |
| **ruff** | **0.15.16** (2026-06-04) | `ruff>=0.15` (dev-group) | Lint + format | **да** | [PyPI](https://pypi.org/project/ruff/) |
| **mypy** | **2.1.0** (2026-05-11) | `mypy>=2.1,<3` (dev-group) | Строгая типизация | **да** | [PyPI](https://pypi.org/project/mypy/) |
| **pytest** | **9.x** | `pytest>=9,<10` (dev/testkit) | Тесты | **да** | (через pylibinfra) |
| **pytest-asyncio** | **1.4.0** (2026-05-26) | `pytest-asyncio>=1.4,<2` | Async-тесты (`asyncio_mode="auto"`) | **да** | [PyPI](https://pypi.org/project/pytest-asyncio/) |

**Вывод по согласованию:** весь инфра-слой (dishka, pydantic(-settings), redis, httpx,
structlog, otel, fastapi/uvicorn, ruff/mypy/pytest) уже пинится pylibinfra — берём
его как транзитивную зависимость и **не дублируем версии**. Бот добавляет только два
новых пина: `aiogram` и `aiogram-dialog`.

> Примечание: aiogram тащит свой `aiohttp` (для Telegram-сессии). Это нормально и не
> конфликтует с fastapi/uvicorn. `redis>=8` совместим — aiogram использует
> `redis.asyncio` из redis-py (4.2+), что покрывается линией 8.x (см. §3, «требует
> прогона интеграционного теста на redis 8»).

---

## 2. Polling vs Webhook (актуальные API, рекомендация)

### 2.1. Long-polling (dev / простой прод)
```python
await dp.start_polling(
    bot,
    allowed_updates=dp.resolve_used_update_types(),  # авто-вывод по зарег. хендлерам
    # drop_pending_updates=True,  # сбросить накопленный backlog при старте
)
```
- `resolve_used_update_types()` — берёт только реально используемые типы апдейтов
  (включая то, что нужно aiogram_dialog).
- `GetUpdates`-rate-limit и сетевые сбои aiogram ретраит сам, логируя.
- graceful shutdown polling'а по сигналам (Linux/Mac) встроен с aiogram 3.x
  (PR «Reworked graceful shutdown»).

### 2.2. Webhook через aiohttp (рекомендуемый путь для прод)
aiogram-нативный путь, секрет-токен проверяется автоматически:
```python
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

app = web.Application()
SimpleRequestHandler(
    dispatcher=dp,
    bot=bot,
    secret_token=WEBHOOK_SECRET,  # сверяется с X-Telegram-Bot-Api-Secret-Token
).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)  # вешает startup/shutdown хуки

# при старте:
await bot.set_webhook(
    url=f"{BASE_URL}{WEBHOOK_PATH}",
    secret_token=WEBHOOK_SECRET,
    allowed_updates=dp.resolve_used_update_types(),
    drop_pending_updates=True,
)
```
`secret_token`: 1–256 символов, только `A-Z a-z 0-9 _ -`.

### 2.3. Webhook через FastAPI (если нужен единый ASGI/uvicorn с pylibinfra)
Ручной эндпоинт + `feed_webhook_update`/`feed_update`. **Важно:** при ручном пути
проверку секрета делаем сами (issue #1024 — `secret_token` в `set_webhook` сам по
себе НЕ валидирует входящий заголовок на стороне приложения):
```python
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_webhook_update(bot, update)  # или feed_update(bot, update)
    return Response(status_code=200)
```

### 2.4. Рекомендация
- **Прод → webhook.** Если бот — самостоятельный сервис: **aiohttp + SimpleRequestHandler**
  (меньше кода, секрет проверяется фреймворком, lifecycle через `setup_application`).
- **FastAPI-вариант** — только если боту реально нужен общий ASGI с pylibinfra
  (health/metrics эндпоинты, единый uvicorn). Тогда не забыть ручную проверку секрета.
- **Dev/локально → polling** (`drop_pending_updates=True`).
- Всегда передавать `allowed_updates=dp.resolve_used_update_types()` — экономит трафик
  и совместимо с aiogram_dialog (он регистрирует свои типы апдейтов).

Источники: [Webhook docs](https://docs.aiogram.dev/en/latest/dispatcher/webhook.html),
[set_webhook](https://docs.aiogram.dev/en/latest/api/methods/set_webhook.html),
[issue #1024 (secret не валидируется автоматически в ручном пути)](https://github.com/aiogram/aiogram/issues/1024).

---

## 3. FSM: RedisStorage + key builder + изоляция событий

> Терминология. Поиск иногда выдаёт устаревшее `RedisStorage2` — это артефакт
> 3.0-бет; в **актуальном aiogram 3.28** класс называется просто `RedisStorage`
> (`aiogram.fsm.storage.redis`) и работает поверх `redis.asyncio`. Старого
> `aioredis` нет.

```python
from redis.asyncio import Redis
from aiogram.fsm.storage.redis import RedisStorage, RedisEventIsolation
from aiogram.fsm.storage.base import DefaultKeyBuilder

redis = Redis(host="localhost", port=6379, db=0)

key_builder = DefaultKeyBuilder(
    prefix="fsm",
    with_bot_id=True,    # изоляция между разными ботами в общем Redis
    with_destiny=True,   # ОБЯЗАТЕЛЬНО для aiogram_dialog (он пишет в свой destiny)
)

storage = RedisStorage(
    redis=redis,
    key_builder=key_builder,
    # state_ttl=..., data_ttl=...,  # опц. TTL, чтобы Redis не пух
)

dp = Dispatcher(
    storage=storage,
    events_isolation=storage.create_isolation(),  # → RedisEventIsolation
)
```

Ключевые моменты:
- **`DefaultKeyBuilder`** параметры: `prefix='fsm'`, `separator=':'`, `with_bot_id`,
  `with_business_connection_id`, `with_destiny` (все три флага по умолчанию `False`).
  Формат ключа: `<prefix>:<bot_id?>:<bus_conn?>:<chat_id>:<user_id>:<destiny?>:<field?>`.
- **`with_destiny=True` критично для aiogram_dialog** — он использует отдельный
  `destiny` для своего стека/контекста. Без этого флага ключи диалога и FSM
  могут пересекаться. (Сверить с референсом aiogram_dialog в `aiogram-dialog-docs/`,
  раздел setup-registration — **требует точечной проверки на конкретном пине 2.6.0**.)
- **Изоляция событий:** `RedisEventIsolation` создаётся через
  `storage.create_isolation()` и передаётся в `Dispatcher(events_isolation=...)`.
  Это per-user lock в Redis (в отличие от `SimpleEventIsolation` с одним глобальным
  asyncio-локом). Дефолтный `lock_kwargs={"timeout": 60}` (фикс в 3.19.0).
  Для распределённого/многоинстансного бота нужен именно Redis-isolation.
- **redis-py 8 совместимость:** aiogram RedisStorage завязан на `redis.asyncio`
  (redis-py ≥4.2), линия 8.x совместима по API. **Требует проверки** прогоном
  интеграционного теста на реальном redis 8 (через testcontainers из pylibinfra[testkit]).

Источники:
[Storages](https://docs.aiogram.dev/en/latest/dispatcher/finite_state_machine/storages.html),
[redis.py исходник](https://docs.aiogram.dev/en/latest/_modules/aiogram/fsm/storage/redis.html),
[Event isolation discussion #1486](https://github.com/aiogram/aiogram/discussions/1486),
[lock_kwargs fix #838/3.19.0](https://github.com/aiogram/aiogram/issues/838).

---

## 4. Graceful shutdown, flood-control, session / bot properties

### 4.1. Bot session и default properties
```python
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

bot = Bot(
    token=TOKEN,
    session=AiohttpSession(),  # создаётся автоматически, если не передать
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,         # дефолтный parse_mode на все вызовы
        link_preview_is_disabled=True,     # опц.
    ),
)
```
- `parse_mode` теперь живёт **в `DefaultBotProperties`** (не аргумент `Bot(parse_mode=...)`
  — это удалено в 3.7+).
- `AiohttpSession` можно настроить (прокси, таймауты). Для Telegram используется
  именно aiohttp-сессия aiogram, **не httpx** (httpx — для прочих внешних API).

### 4.2. Graceful shutdown
- aiogram 3.x останавливает polling по сигналам штатно (Linux/Mac).
- Хуки: `dp.startup.register(...)` / `dp.shutdown.register(...)`.
- Закрытие DI-контейнера на остановке: `dp.shutdown.register(container.close)`.
- В webhook-режиме lifecycle вешает `setup_application(...)` (aiohttp) либо
  lifespan FastAPI (закрыть бот-сессию: `await bot.session.close()`, снять webhook
  при необходимости).

### 4.3. Flood-control / throttling
- В aiogram 3 **встроенного throttling больше нет** — реализуется middleware.
- **Исходящие лимиты (TelegramRetryAfter):** рекомендуемый паттерн — **outer/session
  middleware**, которое ловит `TelegramRetryAfter` и ретраит через `e.retry_after`
  секунд (через `tenacity` из pylibinfra — единый ретрай-стек). Это покрывает все
  вызовы без правок хендлеров.
- **Входящий антифлуд (rate-limit пользователей):** кастомный `ThrottlingMiddleware`
  (часто на `cachetools.TTLCache` или Redis-счётчике). Готовый официальный модуль в
  ядро не входит; community-`ThrottlingMiddleware` — **требует выбора/проверки
  конкретной реализации** (в ядре aiogram её нет, issue #1413 — только пример в доках).
- `GetUpdates` rate-limit и сетевые сбои aiogram ретраит сам.

Источники:
[Bot/defaults](https://docs.aiogram.dev/en/latest/api/defaults.html),
[graceful shutdown PR #1124](https://github.com/aiogram/aiogram/pull/1124),
[TelegramRetryAfter strategy #1489](https://github.com/aiogram/aiogram/discussions/1489),
[throttling example issue #1413](https://github.com/aiogram/aiogram/issues/1413).

---

## 5. Тулинг проекта (uv / ruff / mypy / pytest) + layout

Полностью наследуем конвенции pylibinfra (`pyproject.toml`), чтобы бот был
единообразен с остальной экосистемой.

- **Layout:** `src/`-layout (`src/<bot_pkg>/`), `tests/`, единый `pyproject.toml`,
  build-backend **hatchling** (`[tool.hatch.build.targets.wheel] packages=["src/<pkg>"]`).
- **uv** (0.11.19): менеджер зависимостей + lockfile (`uv.lock`), запуск
  `uv run`. Группы: основные deps + `[dependency-groups] dev` + опц.
  `[project.optional-dependencies] testkit` (как у pylibinfra).
- **ruff** (0.15.16): format + lint. Берём профиль pylibinfra:
  `line-length=100`, `target-version="py312"`, набор правил
  `E,W,F,I,UP,B,SIM,C4,PIE,PT,N,ASYNC,S,TID,RUF`; `ignore=S101,RUF001/2/3`
  (кириллица в комментариях). `per-file-ignores` для `tests/**`.
- **mypy** (2.1.0): `strict=true`, `python_version="3.12"`,
  `plugins=["pydantic.mypy"]`, `warn_unused_ignores`, `no_implicit_optional`.
  Для aiogram/aiogram_dialog проверить наличие стабов / `py.typed` — оба пакета
  типизированы (`py.typed` есть), доп. `types-*` обычно не нужны. **Требует
  проверки** на конкретных пинах.
- **pytest** (9.x) + **pytest-asyncio** (1.4.0): `asyncio_mode="auto"`,
  `--strict-markers --import-mode=importlib`, маркер `integration` для тестов с
  testcontainers (redis для FSM). coverage с `branch=true`.

Источник конвенций: `/root/git/sftbmb/sftbmb-core/pylibinfra/pyproject.toml`.
Версии тулинга: [uv](https://pypi.org/project/uv/), [ruff](https://pypi.org/project/ruff/),
[mypy](https://pypi.org/project/mypy/), [pytest-asyncio](https://pypi.org/project/pytest-asyncio/).

---

## Приложение: dishka × aiogram (DI)

Интеграция `dishka.integrations.aiogram` есть в dishka 1.10:
```python
from dishka import make_async_container
from dishka.integrations.aiogram import (
    AiogramProvider, FromDishka, setup_dishka,  # inject — если без auto_inject
)

container = make_async_container(YourProvider(), AiogramProvider())
setup_dishka(container=container, router=dp, auto_inject=True)
dp.shutdown.register(container.close)  # закрыть контейнер при остановке

# в хендлере:
async def start(message: Message, svc: FromDishka[Service]) -> None: ...
```
- `AiogramProvider()` нужен, если в провайдерах используешь `TelegramObject` /
  `AiogramMiddlewareData` (REQUEST-scope).
- `auto_inject=True` снимает необходимость декорировать каждый хендлер `@inject`.
- aiogram_dialog получает зависимости через тот же DI-проброс (контейнер кладётся в
  middleware data) — **совместимость с `setup_dialogs` требует проверки** на пине
  aiogram-dialog 2.6.0.

Источник: [dishka aiogram integration](https://dishka.readthedocs.io/en/stable/integrations/aiogram.html),
[пример](https://github.com/reagento/dishka/blob/develop/examples/integrations/aiogram_bot.py).

---

### Что осталось «требует проверки» (свести при имплементации)
1. Точная нижняя граница `aiogram` у `aiogram-dialog` 2.6.0 (docs говорят v3.x; референс — `>=3.14`).
2. `with_destiny`/ключи RedisStorage в связке с aiogram_dialog 2.6.0 (поведение destiny).
3. redis-py 8 + aiogram RedisStorage — интеграционный прогон на реальном redis 8.
4. Выбор конкретной community-`ThrottlingMiddleware` (в ядре aiogram её нет).
5. mypy-strict чистота на aiogram/aiogram_dialog (стабы/py.typed) на конкретных пинах.
6. httpx 0.28 vs приближающийся 1.0 (dev) — следить, но 0.28 — стабильный пин pylibinfra.
