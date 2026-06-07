# 06 — dishka ↔ aiogram DI (зона F)

> Артефакт зоны F: как dishka интегрируется с aiogram и как скомпоновать
> pylibinfra-провайдеры в Telegram-боте.
>
> Дата исследования: 2026-06-07. Актуальная версия dishka на эту дату — **1.10.1**
> (2026-04-25; предыдущие: 1.10.0 — 18.04, 1.9.1 — 08.03, 1.9.0 — 07.03,
> 1.8.0 — 11.02). Источник: [PyPI dishka](https://pypi.org/project/dishka/).
>
> Метки: **[ПРОВЕРЕНО]** — из офиц. доков/исходников dishka либо локального кода
> pylibinfra; **[ТРЕБУЕТ ПРОВЕРКИ]** — вывод по аналогии/знаниям, надо проверить
> на целевых версиях aiogram 3.x / aiogram_dialog / dishka 1.10.x.

---

## 1. dishka 101 (scopes / Provider / container / lifespan)

**[ПРОВЕРЕНО]** dishka — DI-фреймворк со скоупами и явной декларацией зависимостей.
Базовые элементы (используются в pylibinfra ровно так):

- **`Provider`** — класс-группа фабрик. Поле `scope = Scope.APP` задаёт скоуп по
  умолчанию для всех методов; метод-фабрика помечается `@provide` (или
  `@provide(scope=Scope.REQUEST)` для override). Возвращаемый тип метода = ключ,
  по которому зависимость потом резолвится. Пример из pylibinfra
  (`telemetry/module.py`, `httpclient/module.py`): провайдер со `scope = Scope.APP`
  и методами `@provide async def ...`.
- **Фабрики-генераторы для cleanup.** Если фабрика — `async def ... -> AsyncIterator[T]`
  с `yield`, то код после `yield` выполняется при закрытии скоупа. Так
  pylibinfra освобождает ресурсы: `HttpClientProvider.client` делает
  `yield c; await c.aclose()`; `TelemetryProvider.providers` — `yield p; p.shutdown()`.
- **Scopes (иерархия).** Стандартная цепочка: `Scope.APP` ⊃ `Scope.REQUEST`
  (есть ещё `SESSION`, `ACTION`, `STEP`, но в вебе/боте используются первые два).
  - `APP` — синглтоны на весь процесс (пулы БД, http-клиент, telemetry,
    конфиги). Живут в корневом контейнере.
  - `REQUEST` — per-операция (per-HTTP-request, per-Update в боте). Открывается
    интеграцией автоматически, закрывается по завершении обработки.
  - `REQUEST`-фабрика может зависеть от `APP`-зависимостей, но не наоборот.
- **`make_async_container(*providers, context=...)`** — собирает корневой
  (APP-scope) `AsyncContainer`. `context=` позволяет прокинуть готовые объекты
  как «зависимости из контекста».
- **`from_context`** — декларация, что зависимость придёт извне (из `context=`
  при создании контейнера или из родительского скоупа интеграцией). Интеграции
  с фреймворками кладут в REQUEST-контекст объекты события (для aiogram — Update,
  для FastAPI — Request).
- **Lifespan.** Контейнер — async-ресурс: APP-скоуп открывается при
  `make_async_container`, ресурсы APP-фабрик инициализируются лениво при первом
  резолве, освобождаются при `await container.close()`. **Закрытие контейнера
  обязательно** — иначе не отработают `yield`-cleanup'ы (не закроется http-сессия,
  пул pg, не сделается telemetry flush).

**Asymmetry note (pylibinfra) [ПРОВЕРЕНО].** Каждый kit-Provider **НЕ** provide'ит
свой `*Config` — это сознательная асимметрия (см. комментарии в
`config/module.py`, `httpclient/module.py`, `telemetry/module.py`):

```python
# Provider не provide'ит Config (asymmetry note) — caller регистрирует Config сам.
```

Config'и регистрирует прикладной код в отдельном **AppConfigProvider** (в README
он называется `AppConfigProvider` / в шапке `AppProvider`). Каждый kit даёт
дешёвый конструктор дефолта (`new_config()`, `new_breaker_config()`,
`new_vault_client_config()`), которым удобно наполнять этот провайдер. Пример
сборки из README pylibinfra (§ Minimum viable observability):

```python
from dishka import make_async_container
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpkit import HttpProvider
from pylibinfra.pgkit import PgProvider
from pylibinfra.natskit import NatsProvider

container = make_async_container(
    TelemetryProvider(),   # OTLP exporter + runtime метрики
    LogkitProvider(),      # structlog с trace_id
    HttpProvider(),        # http_requests_total, ...
    PgProvider(),          # db_pool_* + pg traces
    NatsProvider(),        # nats_messages_*
    AppConfigProvider(),   # сюда caller кладёт ВСЕ *Config (asymmetry note)
)
```

> Вывод для бота: ровно тот же список pylibinfra-провайдеров плюс
> `AppConfigProvider` со всеми Config'ами плюс провайдер(ы) бизнес-сервисов бота
> плюс `AiogramProvider()` от интеграции (см. §2).

---

## 2. Интеграция dishka ↔ aiogram (полная проводка бота)

**[ПРОВЕРЕНО]** Модуль `dishka.integrations.aiogram` экспортирует:
`setup_dishka`, `FromDishka`, `inject`, `AiogramProvider`, `AiogramMiddlewareData`.

Как это работает:

- **`setup_dishka(container, router=dp, auto_inject=...)`** навешивает на
  Dispatcher middleware, который на **каждый Update** открывает дочерний
  **REQUEST-скоуп** из APP-контейнера, кладёт его в `middleware_data`
  (ключ контейнера) и закрывает скоуп по завершении обработки апдейта.
- **`AiogramProvider()`** добавляется в контейнер, чтобы REQUEST-фабрики могли
  получать как зависимости: `aiogram.types.TelegramObject` (само событие) и
  `AiogramMiddlewareData` (dict с данными middleware: `event_chat`,
  `event_from_user`, FSM `state`, и т.п.).
- **`auto_inject=True`** — middleware сам оборачивает хендлеры, тогда `@inject`
  на хендлерах не нужен. Если `auto_inject` не задан (по умолчанию `False`) —
  **каждый** хендлер с `FromDishka`-параметрами надо вручную декорировать
  `@inject` **до** регистрации в роутере. **[ТРЕБУЕТ ПРОВЕРКИ]**: точное
  поведение дефолта `auto_inject` стоит сверить на dishka 1.10.x — в офиц. примере
  используют явный `@inject`, что переносимо при любом дефолте.

Полный пример проводки (склейка офиц. примера dishka + pylibinfra-провайдеров):

```python
import asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from dishka import make_async_container
from dishka.integrations.aiogram import (
    AiogramProvider, FromDishka, inject, setup_dishka,
)

# pylibinfra
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpkit import HttpProvider      # для webhook-режима (FastAPI)
from pylibinfra.pgkit import PgProvider
from pylibinfra.natskit import NatsProvider
# прикладные провайдеры
from app.di import AppConfigProvider, BotServicesProvider
from app.services import GreetingService

router = Router()

@router.message()
@inject   # не нужен, если setup_dishka(..., auto_inject=True)
async def start(message: Message, svc: FromDishka[GreetingService]) -> None:
    await message.answer(await svc.greet(message.from_user.full_name))

async def main() -> None:
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    container = make_async_container(
        TelemetryProvider(), LogkitProvider(), HttpProvider(),
        PgProvider(), NatsProvider(),
        AppConfigProvider(),        # все *Config (asymmetry note)
        BotServicesProvider(),      # бизнес-сервисы (REQUEST или APP scope)
        AiogramProvider(),          # доступ к TelegramObject / middleware_data
    )
    setup_dishka(container=container, router=dp)   # REQUEST-scope на каждый Update

    try:
        await dp.start_polling(bot)
    finally:
        await container.close()     # отрабатывают все yield-cleanup'ы
        await bot.session.close()
```

REQUEST-scoped фабрика, читающая контекст апдейта **[ПРОВЕРЕНО, офиц. пример]**:

```python
from aiogram.types import Chat, TelegramObject, User
from dishka import Provider, Scope, provide
from dishka.integrations.aiogram import AiogramMiddlewareData

class BotServicesProvider(Provider):
    @provide(scope=Scope.REQUEST)
    async def current_user(self, obj: TelegramObject) -> User:
        return obj.from_user

    @provide(scope=Scope.REQUEST)
    async def current_chat(self, md: AiogramMiddlewareData) -> Chat | None:
        return md.get("event_chat")
```

> Где регистрировать сервисы. Сервис без per-update состояния → `Scope.APP`
> (создаётся один раз). Сервис, которому нужен текущий user/chat/FSM-state или
> per-update http-reqid → `Scope.REQUEST`.

---

## 3. Инъекция в хендлеры aiogram и в aiogram_dialog

### 3.1 Обычные хендлеры aiogram — **[ПРОВЕРЕНО]**

```python
@router.message(Command("buy"))
@inject
async def buy(message: Message, billing: FromDishka[BillingService]) -> None:
    ...
```

`FromDishka[T]`-параметры резолвятся из REQUEST-контейнера апдейта; `message` и
прочие штатные параметры aiogram прокидывает сам. Поддерживаются только async-хендлеры.

### 3.2 aiogram_dialog (getter / on_click) — **[ПРОВЕРЕНО для механизма, версии — ТРЕБУЕТ ПРОВЕРКИ]**

Ключевой нюанс: в aiogram_dialog **getter** и **on_click** — это не event-хендлеры
диспетчера, на них не навешивается aiogram-middleware напрямую. dishka решает это
**отдельным интеграционным модулем** `dishka.integrations.aiogram_dialog`, который
экспортирует свои `inject` и `FromDishka`:

```python
from dishka.integrations.aiogram_dialog import FromDishka, inject

@inject
async def getter(a: FromDishka[ProfileRepo], **kwargs) -> dict:
    # getter обязан вернуть dict для виджетов
    return {"profile": await a.load(...)}

@inject
async def on_buy_click(
    event, widget, manager,           # штатные параметры aiogram_dialog
    billing: FromDishka[BillingService],
) -> None:
    await billing.charge(...)
```

Условие: **сначала** настроена обычная aiogram-интеграция (`setup_dishka(dp)`),
т.к. aiogram_dialog-инъекция берёт REQUEST-контейнер из того же `middleware_data`
апдейта.

**Fallback без dishka-обёртки [ПРОВЕРЕНО как механизм aiogram_dialog].** Если по
какой-то причине `dishka.integrations.aiogram_dialog` недоступен/несовместим,
зависимости достаются вручную из `manager.middleware_data` — туда aiogram-middleware
dishka кладёт REQUEST-контейнер; можно `await container.get(BillingService)`:

```python
async def on_click(callback, button, manager: DialogManager) -> None:
    container = manager.middleware_data["dishka_container"]  # ключ — ТРЕБУЕТ ПРОВЕРКИ
    billing = await container.get(BillingService)
```

> **[ТРЕБУЕТ ПРОВЕРКИ]** точное имя ключа контейнера в `middleware_data` на
> dishka 1.10.x и доступность `manager.middleware_data` во всех точках жизненного
> цикла диалога (getter вызывается и при рендере — контекст апдейта должен быть
> активен). Предпочтительный путь — модуль `dishka.integrations.aiogram_dialog`,
> ручной fallback держать только на крайний случай.

---

## 4. Polling vs Webhook (FastAPI + httpkit)

### 4.1 Polling — **[ПРОВЕРЕНО]**

См. §2. Один процесс: `dp.start_polling(bot)`; контейнер закрывается в `finally`.
REQUEST-скоуп открывает **aiogram**-middleware на каждый Update. FastAPI не нужен.

### 4.2 Webhook (FastAPI принимает вебхуки) — **[частично ТРЕБУЕТ ПРОВЕРКИ]**

В webhook-режиме Telegram шлёт апдейты HTTP-POST'ом на эндпоинт. Принимающий
сервер — FastAPI (в sftbmb поднимается через `httpkit`: `pylibinfra/httpkit/server.py`,
`build_app()` собирает FastAPI с OTel-инструментовкой и middleware-цепочкой;
`Server.start/stop` держат uvicorn с graceful shutdown по `shutdown_timeout`).

Канонический способ принять вебхук в aiogram 3.x —
`aiogram.webhook.aiohttp_server.SimpleRequestHandler` (aiohttp). Но т.к. sftbmb
стандартизирован на **FastAPI/httpkit**, апдейты принимаем своим FastAPI-роутом и
скармливаем в Dispatcher:

```python
# webhook endpoint поверх httpkit-FastAPI
@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request) -> Response:
    if secret != cfg.webhook_secret:
        return Response(status_code=403)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)   # тут отрабатывает aiogram-middleware dishka
    return Response(status_code=200)
```

Ключевой момент про **двойную интеграцию dishka [ТРЕБУЕТ ПРОВЕРКИ для нюансов]**:

- `setup_dishka(container, app=app)` (`dishka.integrations.fastapi`, добавить
  `FastapiProvider()`) даёт REQUEST-скоуп **на каждый HTTP-запрос** и инъекцию
  `FromDishka` в FastAPI-роуты.
- `setup_dishka(container=container, router=dp)`
  (`dishka.integrations.aiogram`) даёт REQUEST-скоуп **на каждый Update**.
- **Оба вешаются на ОДИН и тот же `container` (APP-scope общий).** Тогда при
  webhook на один POST открывается HTTP-REQUEST-скоуп (FastAPI), а внутри
  `dp.feed_update` — отдельный aiogram-REQUEST-скоуп для обработки Update. Это
  два разных дочерних скоупа от общего APP. Для инъекции в **бот-хендлеры**
  работает aiogram-интеграция; FastAPI-интеграция нужна, только если в самом
  webhook-роуте нужны DI-зависимости. **Нюанс [ТРЕБУЕТ ПРОВЕРКИ]:** не дублировать
  per-update сервисы между двумя REQUEST-скоупами (получится два экземпляра на
  один логический апдейт) — лучше webhook-роут держать «тонким» (валидация секрета
  + `feed_update`), а вся бизнес-логика идёт через aiogram-скоуп.

FastAPI-lifespan для закрытия контейнера **[ПРОВЕРЕНО, офиц. пример]**:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # старт: set webhook, и т.п.
    yield
    await app.state.dishka_container.close()
```

> **[ТРЕБУЕТ ПРОВЕРКИ]** httpkit'овский `build_app()` (server.py) сейчас сам
> создаёт `FastAPI(...)` без lifespan-параметра и не интегрирует dishka. Чтобы
> поднять webhook-бота на httpkit, надо либо: (а) дать build_app возможность
> принять `lifespan`/после-сборки навесить `setup_dishka(container, app)` на
> возвращённый `app`; либо (б) собирать FastAPI отдельно для бота, переиспользуя
> middleware из httpkit. Это интеграционный gap, требующий решения на уровне
> шаблона бота. uvicorn в httpkit и так гасится gracefully (`Server.stop`), но
> закрытие dishka-контейнера надо подвесить явно (lifespan или после остановки
> сервера).

---

## 5. Graceful shutdown контейнера

**[ПРОВЕРЕНО]** Универсальное правило: **`await container.close()` обязателен**,
иначе не отработают `yield`-cleanup'ы pylibinfra (http `aclose`, telemetry
`shutdown`/flush, пулы pg/nats).

- **Polling:** `try/finally` вокруг `dp.start_polling`: в `finally` —
  `await container.close()`, затем `await bot.session.close()` (офиц. паттерн).
  Альтернатива — зарегистрировать на dispatcher: `dp.shutdown.register(container.close)`
  (упомянуто в офиц. доках aiogram-интеграции) — тогда закрытие привязано к
  жизненному циклу диспетчера. **[ТРЕБУЕТ ПРОВЕРКИ]** порядок: `bot.session.close`
  vs `container.close`, если http-клиент/сессия резолвятся из контейнера.
- **Webhook/FastAPI:** закрытие в `lifespan` после `yield`
  (`await app.state.dishka_container.close()`). С httpkit — см. gap в §4.2:
  навесить lifespan на app или закрывать контейнер после `Server.stop()`.
- **Порядок при graceful shutdown бота (рекомендация):** (1) перестать принимать
  новые апдейты (остановить polling / снять webhook / `Server.stop`), (2) дать
  доработать активным апдейтам, (3) `container.close()` — закрывает APP-ресурсы;
  REQUEST-скоупы к этому моменту уже должны быть закрыты middleware'ами.
- **Telemetry-нюанс [ПРОВЕРЕНО по коду]:** `TelemetryProvider.providers` делает
  `p.shutdown()` на закрытии скоупа → принудительный flush OTLP. Если контейнер
  не закрыть, последние метрики/спаны/логи потеряются. Это ещё один довод за
  обязательный `container.close()`.

---

## Открытые вопросы / что проверить на целевых версиях

1. **[ТРЕБУЕТ ПРОВЕРКИ]** Дефолт и семантика `auto_inject` в `setup_dishka` для
   aiogram на dishka 1.10.x (в примере — явный `@inject`).
2. **[ТРЕБУЕТ ПРОВЕРКИ]** Точное имя ключа REQUEST-контейнера в
   `manager.middleware_data` (для ручного fallback в aiogram_dialog) и наличие
   модуля `dishka.integrations.aiogram_dialog` в установленной версии.
3. **[ТРЕБУЕТ ПРОВЕРКИ]** Интеграционный gap httpkit `build_app()` ↔ dishka
   FastAPI-lifespan / `setup_dishka(container, app)` для webhook-режима.
4. **[ТРЕБУЕТ ПРОВЕРКИ]** Совместимость версий: aiogram 3.x + aiogram_dialog +
   dishka 1.10.x (typing dialog-интеграции чинили в недавних релизах dishka).
5. **[ТРЕБУЕТ ПРОВЕРКИ]** Двойной REQUEST-скоуп в webhook (FastAPI HTTP-scope +
   aiogram Update-scope) — не плодить дублирующиеся per-request сервисы.

---

## Источники

- dishka aiogram integration — https://dishka.readthedocs.io/en/stable/integrations/aiogram.html
- dishka aiogram_dialog integration — https://dishka.readthedocs.io/en/stable/integrations/aiogram_dialog.html
- dishka FastAPI integration — https://dishka.readthedocs.io/en/stable/integrations/fastapi.html
- Офиц. пример бота — https://github.com/reagento/dishka/blob/develop/examples/integrations/aiogram_bot.py
- dishka на PyPI (версии/даты) — https://pypi.org/project/dishka/
- aiogram_dialog passing data (getter/on_click/middleware_data) — https://aiogram-dialog.readthedocs.io/en/stable/widgets/passing_data/index.html
- aiogram DI — https://docs.aiogram.dev/en/latest/dispatcher/dependency_injection.html
- Локально: pylibinfra README (§ Minimum viable observability); `telemetry/module.py`,
  `httpclient/module.py`, `config/module.py` (asymmetry note); `httpkit/server.py`.
