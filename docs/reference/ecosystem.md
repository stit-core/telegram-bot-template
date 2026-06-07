# Ecosystem

Место шаблона в экосистеме sftbmb: форкаемые шаблоны `sftbmb-core/*` + общая инфра-библиотека
`sftbmb-core/pylibinfra`. Канон контрактов (tenant/OTLP/registry) — `corp-infra-template/docs/
ecosystem.md`. Этот шаблон — **фронтенд-сервис**: чистая бизнес-логика на `aiogram_dialog` поверх
`pylibinfra[tgbotkit]`.

## Роль

Шаблон Telegram-бота. Форкается в `<org>/<bot>`; разработчик собирает + пушит образ
`git.${DOMAIN}/<org>/telegram-bot:<vX.Y.Z>`. Деплоем **не занимается** — handoff в `<org>/infra`.

```
   pylibinfra (kit'ы: tgbotkit/httpclient/cachekit/natskit/telemetry/logkit/httpkit/…)
        │ depends (extra [tgbotkit] @ git-ref)
        ▼
   ЭТОТ РЕПО ◄──контракт (OTLP, registry, secrets)── corp-infra-template (control plane)
        │ ──build+push image──► git.${DOMAIN}/<org>/telegram-bot
        │                                   │
        │                                   ▼
        │                   <org>/infra (← project-infra-template-compose) ──deploy──► VPS
        ▼
   бэкенды продукта (HTTP API + события NATS) — источник всей бизнес-логики
```

Бот — это фронтенд: бизнес-данные/логика живут на бэкендах (HTTP API через `httpclient` +
события NATS через notifications). Бот владеет только своим state в Redis.

## Зависит от / используется

- **Зависит от:** `sftbmb-core/pylibinfra` — единственная рантайм-зависимость (extra
  `[tgbotkit]`: tgbotkit + aiogram + aiogram_dialog + fluent.runtime; остальная инфра —
  dishka/redis/httpx/otel/fastapi/structlog/nats — транзитивом). **Ноль прямых инфра-пинов**
  в `pyproject.toml`. Пинится по git-ref (`[tool.uv.sources]`) — как go-сервис на `go.mod`-версию.
  Сейчас pin на коммит `3eebcba` (единственная ревизия с `tgbotkit`); финально — релиз-тег.
- **Зависит от:** `corp-infra-template` (контракт OTLP-endpoint, registry, secrets-класс);
  `git.${DOMAIN}` (push images); продуктовые бэкенды (`HTTPCLIENT_BASE_URL`, NATS-stream `orders`).
- **Используется:** `<org>/infra` (форк project-infra-template-compose) — пуллит образ через
  `vault kv patch …/meta bot_tag=<tag>` + `make ship` на проектной VPS.

## Зависимость от pylibinfra: вся инфра там

Директива «framework ≠ продукт»: `tgbotkit` знает про aiogram (transport), но не про конкретные
диалоги/команды/флоу — ровно как `httpkit` знает FastAPI. Bootstrap бота, Dispatcher,
RedisStorage, middleware-цепочка, webhook/polling runner, dishka-setup, error-handlers, graceful
shutdown, observability апдейтов, generic-механика i18n/notifications/payments/webapp — **в kit'е,
не в шаблоне**. Шаблон подключает бизнес-логику через точки расширения
(`RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/`LocaleResolver`), не трогая инфру.

## INFRA-HANDOFF (2 PR при новой инфра-механике)

Если бизнес-задаче нужна **новая инфра-механика** (новый middleware, новый вид рантайма, новая
generic-обёртка над BgManager, новый error-handler-тип) — это **не правка шаблона, а PR в
`pylibinfra`** (rule `tgbotkit-boundary`, skill `infra-handoff`). При первичной реализации шаблона
это были два PR в `pylibinfra` (оба аддитивные, back-compat):

- **PR-A — kit `tgbotkit`**: `BotProvider`+`Config`, middleware-цепочка, runner (polling/webhook),
  error-handlers, observability, точки расширения, подсистемы (i18n/notifications/payments/webapp),
  testkit-сабпакет; новая extra `pylibinfra[tgbotkit]` (aiogram/aiogram_dialog/fluent.runtime —
  новые deps, согласованы как «framework не продукт»).
- **PR-B — доработка `httpkit`**: `build_app(lifespan=)`, `Server(autostart=)` +
  `dishka_lifespan`, `shared_secret_guard()` (generic 403-guard для входящих вебхуков) —
  консьюмится `tgbotkit.runner.webhook`.

Текущий статус и открытые вопросы (имя kit'а, согласование deps, последовательность PR) —
`design/ROADMAP.md`.

## Границы ответственности

Этот репо STOP'ает на image-in-registry. Деплой-команды чужих репо (`make ship`, `ssh`, `vault kv
patch`) отсюда **не запускаются**. Инфра-поверхность (env/секрет/webhook/cross-service NATS-subject/
runtime-режим) фиксируется INFRA-HANDOFF-блоком — см. `.claude/rules/infra-impact.md` и skill
`infra-handoff`. Деплой — [release.md](release.md) → handoff в `<org>/infra`.
