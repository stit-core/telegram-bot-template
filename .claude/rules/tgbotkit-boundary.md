---
name: tgbotkit-boundary
description: Инфра не пишется в шаблоне — только бизнес и регистрация в точки расширения tgbotkit; новая инфра-механика → PR в pylibinfra/tgbotkit через infra-handoff. Terse; «как и почему» — docs/reference/architecture.md § Граница с pylibinfra. Грузится при правке app.py/platform/.
paths:
  - "src/bot/app.py"
  - "src/bot/platform/**"
---

# Граница tgbotkit ↔ шаблон

Директива: **вся инфра бота — в `pylibinfra[tgbotkit]`**, шаблон — чистая бизнес-логика +
тонкая регистрация. `Bot`/`Dispatcher`/`RedisStorage`/middleware-цепочка/webhook|polling-runner/
`setup_dishka`/`setup_dialogs`/error-handlers/observability/graceful-shutdown — **в kit'е, не тут**.
Принцип «framework ≠ продукт»: kit знает aiogram, не знает твои диалоги/команды/флоу.

## Что шаблон делает здесь (и только это)

- **`app.py`** — единый composition root: `ExtensionProvider` + `build_container` + `run()`
  (`make_async_container` → `BotRunner.run()`). Никакой проводки рантайма. Порядок провайдеров
  значим: `BotProvider` даёт **дефолты** (Logger=nop, bundles, `ErrorUX`, `Optional*`), поэтому
  `LogkitProvider` и `ExtensionProvider` идут **после** него (last-wins). `AiogramProvider`
  обязателен (REQUEST-контекст для identity).
- **`ExtensionProvider`** (в `app.py`) — наполняет точки расширения kit'а бизнесом:
  `RouterBundle` (диалоги), `CommandBundle` (`CommandSpec` команд/`pre_checkout`/`successful_payment`),
  `NotifierBundle`, `ErrorUX`, `OptionalLocaleResolver`, `OptionalStreamBus`. **Декларируешь, что
  подключить — не как это работает.**
- **`platform/`** — общее **бизнес-проектное**: `identity/` (Update→`BotIdentity`), `dialogs/`
  (`states.py`, `common.py`, `errors.py:ErrorUX`), `webapp/` (валидатор initData), `links.py`.
  Это бизнес-glue, **не** инфра-проводка. Клиенты API — не сюда: `pkg/http_client/`
  (rule `feature-architecture`).

## Запрещено

- ❌ Собирать в шаблоне `Dispatcher`/`Bot`/`RedisStorage`/middleware/webhook-app/`setup_dialogs`/
  `setup_dishka`/error-handler-регистрацию — это поверхность kit'а.
- ❌ Прямые инфра-пины в `pyproject` (aiogram/redis/httpx/otel) — всё транзитом `pylibinfra[tgbotkit]`.
- ❌ Дублировать/обходить дефолты kit'а вместо override через провайдер после `BotProvider`.
- ❌ Тащить инфра-механику в `platform/` под видом «общего» (нет incoming-Update — это фон/kit).

## Новая инфра-механика → PR в pylibinfra

Нужен новый middleware / новый вид рантайма / новая generic-подсистема / новая точка расширения —
это **не правка шаблона, а PR в `pylibinfra/tgbotkit`**, оформляется через skill `infra-handoff`
(контракт границы — `docs/reference/architecture.md § Граница с pylibinfra`; механика kit'а аддитивна/back-compat).
Шаблон может временно нести инфру локально только как переходный шаг — с обязательным выносом PR'ом.

## Чек

- Правка под этими `paths:` меняет регистрацию/значение конфига, а не механику? Да — ок. Механику —
  стоп, в `infra-handoff`.
- Тронул env/секрет/webhook/runtime-dep попутно → rule `infra-impact` (INFRA-HANDOFF-блок).
- `make check` зелёный; composition-smoke (контейнер собирается, `emit_startup`) не падает.
