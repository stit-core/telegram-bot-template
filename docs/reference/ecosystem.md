# Ecosystem

Шаблоны `stit-core/*` форкаются в репо клиентской орги `<org>/*`; форки одной орги лежат рядом
sibling-checkout'ами (`../<name>`). Этот шаблон — `telegram-bot-template` → форк `<org>/<bot>`:
Telegram-бот на `aiogram` + `aiogram_dialog` поверх `pylibinfra[tgbotkit]`. Бот — тонкий клиент
продуктовых бэкендов: бизнес-данные и логика живут там (HTTP API + события NATS), сам бот владеет
только своим state в Redis (FSM/диалоги/dedup/identity-link).

Канон карты и операционного флоу — `docs/reference/ecosystem.md` инфра-репо (`<org>/infra`, форк
`project-infra-template-compose`). Здесь — роль этого репо и его стыки с соседями.

## Соседи

| Шаблон → форк | Роль |
|---|---|
| `business-strategy-template` → `<org>/strategy` | design-time source of truth: бизнес, AJTBD, SWOT, карта гипотез, продукты (в т.ч. слой `telegram-bot-flow` — дизайн диалогов бота), ИТ-периметр |
| `project-infra-template-compose` → `<org>/infra` | runtime проекта (docker-compose на VPS) и операционный хаб: общий план, рассылка агентов по сиблингам, выкатка тегов (`make bump`) |
| `go-backend-template` → `<org>/backend` | Go-сервис — обычно продуктовый бэкенд бота |
| `spa-frontend-template` → `<org>/frontend` | React SPA (кабинет, всё за логином) |
| `ssr-frontend-template` → `<org>/site` | Astro SSR-сайт (индексируемый контент) |
| `telegram-bot-template` → `<org>/<bot>` | **этот репо** — Telegram-бот (Python, aiogram) |
| `mobile-template` → `<org>/mobile` | KMP-приложение Android + iOS; релиз — в магазины |

Библиотеки: `pylibinfra` — Python-киты, рантайм этого бота (`tgbotkit` и соседние киты);
`golibinfra` — Go-киты Go-сервисов.

## Как сюда приходят агенты

- **Из хаба `<org>/infra`** — обычный путь. Задача входит в хаб и ведётся в его общем плане; фазу
  бота агент выполняет в `../<bot>` **обвязкой этого репо**: `CLAUDE.md`, `/smartdev`, свой план фазы
  в `.claude/plans/` (`/plan`, `parent: infra:<slug>`), гейт `make check`, финал — `/release`. В хаб возвращаются
  тег образа и INFRA-HANDOFF-блок.
- **Прямой заход** (открыт только этот репо) — нормальный режим, обвязка та же. Всё, что требует
  действия соседей, оформляется блоком `/infra-handoff`: для хаба — env, секреты, webhook,
  NATS-subject, runtime-deps; для мейнтейнера `pylibinfra` — новая инфра-механика.

## Что берёт

- **Дизайн диалогов — `../strategy`**, слой `docs/projects/<project-slug>/telegram-bot-flow/<surface>/`,
  только `status: stable`. Читает `/dialog-deep-dive` (транслятор в карту `docs/stack/dialogs.md`),
  по карте код разворачивает `/scaffold`. Стратегия отсюда не правится: дыры в дизайне закрывает
  аналитик в `../strategy` его скиллами (`/telegram-bot-flow-deep-dive`). Рантайм-образ от стратегии
  не зависит. Что именно читается — § Хендофф из стратегии.
- **Платформа — `pylibinfra[tgbotkit]`**, единственная рантайм-зависимость, пин git-тегом в
  `[tool.uv.sources]` (`pyproject.toml`). Bootstrap, Dispatcher, RedisStorage, middleware-цепочка,
  runner (polling/webhook), error-handlers, graceful shutdown, generic-механика
  i18n/notifications/payments/webapp — в kit'е; шаблон регистрирует бизнес в точки расширения
  `app.py` (`RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/`LocaleResolver`). Новая
  инфра-механика — PR в `pylibinfra/tgbotkit`, а не правка шаблона (rule `tgbotkit-boundary`, skill
  `/infra-handoff`).
- **Продуктовые бэкенды** (обычно `<org>/backend`): HTTP API через `pkg/http_client`
  (`HTTPCLIENT_*`) и события NATS через notifications. Stream/subject/durable событий —
  cross-service контракт; его изменение идёт в INFRA-HANDOFF.

## Что отдаёт

- **Образ в registry.** `make release VERSION=vX.Y.Z` (skill `/release`) пушит один образ
  `<registry>/<org>/bot:vX.Y.Z`: registry и орга выводятся из `git remote origin` (Gitea
  `git.stit.tech`), registry переопределяется env `REGISTRY`; имя образа `bot` не зависит от имени
  репо `<bot>`. После пуша — **STOP**: деплой этот репо не делает.
- **INFRA-HANDOFF для хаба.** `make release` печатает `BOT_TAG → vX.Y.Z` и накопленные
  разделы `## Handoff` активных планов. Выкатка — в `<org>/infra`: `make bump SVC=bot TAG=vX.Y.Z`
  (правит `BOT_TAG` в `.env` на VPS + force-recreate), откат — тот же `bump` на предыдущий тег.
  Сервис `bot` в стек хаба добавляется там (`/add-service`). `make bump`/`make ship`/`ssh` отсюда не
  запускаются. Процедура — [release.md](release.md).

## Хендофф из стратегии (design-time)

Дизайн диалогов проектируется в `<org>/strategy` аналитиком (скиллы `telegram-bot-flow-deep-dive`/
`-audit`) и читается этим репо read-only, односторонне:

| стратегия отдаёт | этот репо читает чем | разворачивает во |
|---|---|---|
| `telegram-bot-flow/<surface>/` (фичи `dialog/window/use-case` + сквозные `command/notification`, `stable`) | `/dialog-deep-dive` (транслятор) → карта `docs/stack/dialogs.md` | `StatesGroup`, окна, виджеты, use-case'ы-оркестраторы, getter'ы, обработчики |
| `interface/<surface>/` (зеркало UX) | контекст синтеза | соответствие виджетов атомам |
| `services/<svc>/domains/<ctx>/` (use-case'ы, события) | рефы `use-case:<ctx>.<Operation>`/`event:` (в `Dependencies` bot UC / `notification`) | порт фичи → pkg-клиент, NATS-subject |

Маппинг полей артефакта в файлы фичи — [dialog-mapping.md](dialog-mapping.md). Поверхности
изолированы: бот читает слой одной bot-поверхности (`type: bot` из реестра `surface.md` стратегии).
