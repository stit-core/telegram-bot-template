---
title: "telegram-bot-template — .claude-система (skills/rules/agents)"
description: "План агентной системы шаблона бота: скиллы, правила, агенты, CLAUDE.md-роутер и cockpit — зеркало go-backend-template, адаптированное под aiogram_dialog."
status: design
lang: ru
based_on: design/_research/02
---

# .claude-система шаблона бота

Зеркалит систему `go-backend-template` (`_research/02`): **CLAUDE.md как ядро+роутер**, скиллы
(процедуры), path-scoped rules (контекстные инварианты), агенты, единый `plans/roadmap.md`
(planning-first, forward-only). Каркас стек-агностичен и переносится почти без изменений; меняется
наполнение под aiogram_dialog.

> **Учитывает директиву «вся инфра в pylibinfra/`tgbotkit`».** Шаблон — чистая бизнес-логика, поэтому
> скиллы `scaffold` генерят блоки, которые **регистрируются в точки расширения tgbotkit**
> (`RouterBundle`/`CommandBundle`/`NotifierBundle`), а не проводят инфру. Любая нужда в новой
> инфра-механике (новый middleware, новый вид рантайма) — это **не правка шаблона, а PR в `tgbotkit`**
> → идёт через `infra-handoff` (см. [ARCHITECTURE.md §16](ARCHITECTURE.md)). Добавляется rule
> `tgbotkit-boundary`.

---

## 1. Скиллы

### 1.1. Переносятся ~1:1 из go-template

| Скилл | Роль | Отличие у бота |
|---|---|---|
| `smartdev` | Always-on cockpit: грузит план из roadmap, гонит `make status`, сам переключает в нужный режим (plan/triage/scaffold/infra-handoff) | то же; `make status` детектит drift по своим гейтам |
| `plan` | Planning-first: задача → атомы → секция в `plans/roadmap.md` | без изменений |
| `triage-failure` | RED-first разбор падения (тест/lint/типы/startup-smoke). Багфикс идёт сюда, не в `plan` | добавить разбор `dp.emit_startup()`-падений и preview-graph |
| `init-service` | Оркестратор онбординга: форк → проектирование стека → de-template → scaffold фич | чейнит бот-скиллы |
| `de-template` | Развернуть форк в самостоятельный проект: rewrite import-path, prune reference-фич (`start`/`profile`), wiring composition root по stable stack-докам | prune фич вместо go-доменов |
| `stack-deep-dive` | Проектирование платформы через раунды `AskUserQuestion`, фиксация в `state/` | бот-набор kinds (§2 ниже) |
| `infra-handoff` | Оформить INFRA-HANDOFF-блок при изменении инфра-поверхности (env/секрет/webhook/cross-service NATS-subject/runtime-dep) | то же |
| `release` | Запушить образ в registry + агрегированный handoff | **один образ** (без api+migrate lockstep) |
| `query-logs` | Чтение прод-логов через корп-Loki (`SFTBMB_LOKI_ADDR`, токен из `.env.local`) | почти буквально |

### 1.2. `scaffold` — переосмыслен под строительные блоки aiogram_dialog

Роутер + `references/<variant>.md`. Варианты:

| Вариант | Что генерит | ⟂ go-scaffold |
|---|---|---|
| `feature` | Новый вертикальный срез `features/<name>/` (полный набор файлов §анатомия) + Provider + регистрация в registry + StatesGroup в `platform/dialogs/states.py` | `domain` |
| `dialog` | Новый `Dialog`/набор `Window` внутри существующей фичи + getters/handlers | (нет прямого) |
| `window` | Окно в существующий диалог (state + getter + handler) | `endpoint` |
| `backend-port` | Новый порт `BackendGateway`-метод + адаптер в `gateway.py` + DTO | `port` |
| `middleware` | Outer/inner-middleware (throttle/auth/i18n) с навешиванием на dp **и** `DIALOG_EVENT_NAME` | (нет) |
| `job` | Периодическая джоба через `timerkit` (напоминание/cleanup) | (часть `event`) |
| `notification` | NATS-подписчик (`natskit`) + отправка/обновление диалога через `BgManager` | `event` (subscriber) |

### 1.3. Новые скиллы — под уникальные боли aiogram_dialog

| Скилл | Зачем (риск, который закрывает) |
|---|---|
| `dialog-deep-dive` | Проектирование флоу диалога как source-of-truth **до** кода (окна, переходы, getter-данные, состояния виджетов) — аналог `domain-deep-dive`, но для UI-сценария |
| `state-migration` | Безопасная эволюция `StatesGroup`/`State`: иначе деплой ломает живые кнопки → `UnknownIntent`/`State`. Чек-лист: deprecation вместо удаления, версионирование, error-handler как сеть, smoke-тест |
| `preview-flow` | Сгенерировать граф переходов (`render_transitions`) и HTML-preview окон (`render_preview`) как CI-gate/ревью-артефакт; проверка `preview_data` |

---

## 2. stack-deep-dive — бот-набор артефактов (`docs/stack/`)

8+ артефактов (frontmatter + H2 + секция **Generates**), как у go-template, но под бота:

| Артефакт | Содержание |
|---|---|
| `service` | имя сервиса, назначение, владелец, SLO |
| `runtime` | **polling vs webhook**, инстансы, graceful shutdown |
| `storage` | Redis (НЕ Memory!), key-builder `with_destiny`, TTL, `RedisEventIsolation`, JSON-сериализуемость |
| `dialogs` | карта диалогов/флоу, корневой `LaunchMode.ROOT`, `/start`=`RESET_STACK`, error-handlers |
| `backends` | список бэкендов, base_url, таймауты, breaker, auth, идемпотентность |
| `messaging` | NATS-subjects (push-уведомления), JetStream vs core |
| `auth` | identity-link tg↔backend, admin-allowlist, initData-валидация |
| `observability` | метрики `tg_*`/`biz_tg_*`, трейс апдейта, health |
| `config` | env/Vault-поверхность, secret-карта |
| `dependencies` | внешние зависимости и их деградация |
| `i18n` (опц.) | локали, движок, middleware |

`storage` и `dialogs` — **критичные**: без них прод падает на первом деплое (`_research/02`).

---

## 3. Rules (path-scoped, грузятся на matching-файлах)

| Rule | Paths | Инварианты |
|---|---|---|
| `feature-architecture` | `src/bot/features/**` | слои фичи; ports/adapters; cross-feature только через `adapters.py`; I/O в usecase, чистое в policy/state; getter=данные, handler=реакции |
| `dialog-architecture` | `**/dialogs.py`, `**/getters.py`, `**/handlers.py` | `getter(**kwargs)`+дефолты+no-reserved-keys; `id` ASCII/короткие/уникальные; один media/markup/input на окно; корневой `LaunchMode.ROOT` |
| `storage-serialization` | `**/state.py`, `**/*state*.py` | только JSON-примитивы в dialog_data/widget_data/start_data; `datetime`→ISO; pydantic `model_dump(mode="json")` |
| `state-lifecycle` | `platform/dialogs/states.py` | все StatesGroup тут; deprecation вместо удаления; error-handlers обязательны; smoke `emit_startup` |
| `background-updates` | `**/notification*.py`, `**/jobs*.py` | фоновые `aiogd_update` не проходят обычные middleware — дублировать на `DIALOG_EVENT_NAME`; `BgManager` подводные камни |
| `tests-pipeline` | `tests/**` | RED-first; маркеры unit/dialog/integration/e2e; локаторы по callback_data; мокать порт, не транспорт |
| `infra-impact` | `config.py`, `.env*`, `Dockerfile`, `**/notification*.py` | INFRA-HANDOFF при изменении env/секрета/webhook/NATS-subject/runtime-dep |
| `tgbotkit-boundary` | `src/bot/app.py`, `src/bot/platform/**` | инфра не пишется в шаблоне — только бизнес и регистрация в точки расширения tgbotkit; новая инфра-механика → PR в `pylibinfra/tgbotkit` через `infra-handoff` |
| `comments` | `**/*.py` | комментарии — только WHY |
| `forward-only` | `**/*.md` | текст описывает только текущее состояние |
| `env-local` | `.env.local` | где токены для query-logs/Loki |

---

## 4. CLAUDE.md (ядро+роутер) и cockpit

- **CLAUDE.md ≤ ~200 строк:** краткое описание стека (aiogram + aiogram_dialog + dishka +
  pylibinfra), точка входа (`/smartdev`), planning-first, карта «где что» (docs/skills/rules),
  стиль (ruff/mypy/import-linter; только `logkit.Logger`; переиспользуемое → pylibinfra), git
  workflow (Conventional Commits, `make check` gate), границы (делать/спросить/никогда), forward-only.
- **Cockpit `smartdev`:** на `make status`-детекте (drift/красное/инфра-touch) сам чейнит в нужный
  скилл, ведя RED→GREEN по дефолту.
- **Двухуровневая защита:** git-хуки (commit-msg/pre-commit/pre-push) + `permissions.deny` в
  `settings.json` (`--no-verify`, коммит `.env`/`*.key`). Claude-hooks **не** заводим (как в
  go-template).

---

## 5. Agents

| Agent | Роль |
|---|---|
| `explorer` | Read-only разведка по репо (где что, как связано) — для онбординга/ориентации |
| `reviewer` | Ревью диффа на инварианты (слои, ports/adapters, сериализация state, error-handlers, тесты) |

---

## Сухой остаток

Каркас go-template переносится целиком: 9 скиллов ~1:1, `scaffold` переосмыслен под блоки
aiogram_dialog (feature/dialog/window/backend-port/middleware/job/notification), +3 новых скилла
(`dialog-deep-dive`/`state-migration`/`preview-flow`) под боли диалогов, bot-rules под `.py`-пути.
Критичный акцент в `stack-deep-dive`: артефакты `storage` и `dialogs` — без них прод ломается.
