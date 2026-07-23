# Ecosystem

Место шаблона в экосистеме stit: **6 форкаемых шаблонов** `stit-core/` (`corp-infra-template`,
`project-infra-template-compose`, `go-backend-template`, `spa-frontend-template`,
`business-strategy-template`, `telegram-bot-template`) + общая инфра-библиотека `stit-core/pylibinfra`
(kit'ы). Корп control-plane — репо `corp-infra-template` (managed = инстанс на `*.stit.tech`;
self-hosted = форк `<org>/infra`). Этот шаблон — **фронтенд-сервис**: чистая бизнес-логика на
`aiogram_dialog` поверх `pylibinfra[tgbotkit]`.

## Роль

Шаблон Telegram-бота. Форкается в `<org>/<bot>`; разработчик собирает + пушит образ
`git.${DOMAIN}/<org>/bot:<vX.Y.Z>`. Деплоем **не занимается** — handoff в `<org>/infra`.

```
   <org>/strategy (← business-strategy-template)  — design-time SoT: дизайн диалогов бота
        │ side-input: telegram-bot-flow/<surface>/ читают /dialog-deep-dive + /scaffold (рантайм не зависит)
        ▼
   ЭТОТ РЕПО ◄──контракт (registry образов)── corp-infra-template (corp control plane)
        │ ──build+push image──► git.${DOMAIN}/<org>/bot
        │                                   │
   pylibinfra (kit'ы)                       ▼
        │                     <org>/infra (← project-infra-template-compose) ──deploy──► VPS
        ▼
   бэкенды продукта (HTTP API + события NATS) — источник всей бизнес-логики
```

Бот — это фронтенд: бизнес-данные/логика живут на бэкендах (HTTP API через `pkg/http_client` +
события NATS через notifications). Бот владеет только своим state в Redis (FSM/диалоги/dedup/
identity-link).

## Зависит от / используется

- **Зависит от:** `stit-core/pylibinfra` — единственная рантайм-зависимость (extra `[tgbotkit]`:
  tgbotkit + aiogram + aiogram_dialog + fluent.runtime; остальная инфра — dishka/redis/httpx/otel/
  fastapi/nats — транзитивом). Ноль прямых инфра-пинов. Пинится по git-ref (`[tool.uv.sources]`),
  как go-сервис на `go.mod`-версию.
- **Зависит от:** `corp-infra-template` (контракт registry образов);
  `git.${DOMAIN}` (push images); продуктовые бэкенды (`HTTPCLIENT_*`, NATS-stream).
- **Используется:** `<org>/infra` (форк `project-infra-template-compose`) — пуллит образ, пиня тег
  (`bot_tag=<tag>`) в конфиге деплой-репо + `make ship` на проектной VPS.
- **Зависит (design-time) от:** `<org>/strategy` (форк `business-strategy-template`) — слой
  `telegram-bot-flow/<surface>/`. `/dialog-deep-dive` и `/scaffold` читают его при разработке;
  рантайм-образ от стратегии не зависит (это source-of-truth проектирования, не deploy-звено).

## Хендофф из стратегии (design-time)

Когда у продукта есть стратегия-репо, дизайн диалогов проектируется **там** аналитиком (скиллы
`telegram-bot-flow-deep-dive`/`-audit`) и читается этим репо read-only, односторонне:

| стратегия отдаёт | этот репо читает чем | разворачивает во |
|---|---|---|
| `telegram-bot-flow/<surface>/` (фичи `dialog/window/use-case` + сквозные `command/notification`, `stable`) | `/dialog-deep-dive` (транслятор) → карта `docs/stack/dialogs.md` | `StatesGroup`, окна, виджеты, use-case'ы-оркестраторы, getter'ы, обработчики |
| `interface/<surface>/` (зеркало UX) | контекст синтеза | соответствие виджетов атомам |
| `domains/<ctx>/{use-cases,events}/` | рефы `use-case:<ctx>.<Operation>`/`event:` (в `Dependencies` bot UC / `notification`) | порт фичи → pkg-клиент, NATS-subject |

Маппинг полей артефакта в файлы фичи — [dialog-mapping.md](dialog-mapping.md). Поверхности
изолированы: бот читает слой одной bot-поверхности (`type: bot` из реестра `surface.md` стратегии).

## Зависимость от pylibinfra: вся инфра там

Директива «framework ≠ продукт»: `tgbotkit` знает про aiogram (transport), но не про конкретные
диалоги/команды/флоу. Bootstrap бота, Dispatcher, RedisStorage, middleware-цепочка, webhook/polling
runner, dishka-setup, error-handlers, graceful shutdown, observability апдейтов, generic-механика
i18n/notifications/payments/webapp — **в kit'е, не в шаблоне**. Шаблон подключает бизнес через точки
расширения `app.py` (`RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/`LocaleResolver`),
не трогая инфру.

## INFRA-HANDOFF (новая инфра-механика = PR в pylibinfra)

Если бизнес-задаче нужна **новая инфра-механика** (новый middleware, новый вид рантайма, новая
generic-обёртка над BgManager, новый error-handler-тип) — это **не правка шаблона, а PR в
`pylibinfra/tgbotkit`** (rule `tgbotkit-boundary`, skill `infra-handoff`). Шаблон несёт только
бизнес-логику и регистрацию в точки расширения.

## Self-hosted путь

Эндпоинты (`git.${DOMAIN}` registry, адреса бэкендов/Redis/NATS) на managed-пути указывают на
хостинг stit (`*.stit.tech`); на self-hosted — на вашу инфру. Всё задаётся через env (registry-host,
`HTTPCLIENT_*`, `REDIS_URL`, `NATS_URL`) — архитектура кода не меняется, меняется только хост.
Вендор-лока нет.

## Границы ответственности

Этот репо STOP'ает на image-in-registry. Деплой-команды чужих репо (`make ship`, `ssh`)
отсюда **не запускаются**. Инфра-поверхность (env/секрет/webhook/cross-service
NATS-subject/runtime-dep) фиксируется INFRA-HANDOFF-блоком — см. `.claude/rules/infra-impact.md` и
skill `infra-handoff`. Деплой — [release.md](release.md) → handoff в `<org>/infra`.
