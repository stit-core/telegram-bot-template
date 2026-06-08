# telegram-bot-template — гайд для агентов

Тонкий шаблон Telegram-бота stit: **чистая бизнес-логика** на `aiogram` 3.28 + `aiogram_dialog`
2.6 + `dishka` поверх `pylibinfra[tgbotkit]`. Вся инфра бота (Bot/Dispatcher/RedisStorage,
middleware, webhook/polling runner, dishka-setup, error-UX, метрики, generic-механика
i18n/notifications/payments/webapp) — **в `pylibinfra/tgbotkit`**, не здесь. В шаблоне — фичи
(диалоги/usecase/gateway/policy/state), контент (`.ftl`), регистрация в точки расширения kit'а.

Этот файл — **ядро (always-on) + роутер**. Детали — в `docs/`, контекстные инварианты — в
`.claude/rules/` (path-scoped, грузятся на matching-файлах), процедуры — в `.claude/skills/`.
Карта документации — `docs/README.md`.

## Точка входа

- **`/smartdev`** — cockpit сессии: сводка (`make status`: ветка, drift, активный план, гейт) +
  переключение в нужный режим. Запускай в начале / после `/clear`.
- **Потребителю шаблона** — `docs/getting-started.md`: форк → `/init-service` → проектирование
  стека (`docs/stack/`) → `/de-template` (prune reference-фич) → `/scaffold` → свой бот.
- **Planning-first.** Любое содержательное изменение идёт через план — секцию в едином
  `.claude/plans/roadmap.md` (skill `/plan`). Прямая правка — только truly-atomic и багфиксы
  (`/triage-failure`, RED-first). План переживает `/clear`.

## Проектирование первично, код вторичен

Флоу диалога проектируется **до** кода (`/dialog-deep-dive`: окна, переходы, getter-данные,
состояния виджетов) — это source of truth, код пишется по нему. Платформа/стек — `docs/stack/`
(`/stack-deep-dive`). `start`/`profile`/`payments`/`lang`/`notifications` — reference-фичи
(изучить, потом prune под свой проект через `/de-template`). Роль репо в экосистеме — `docs/reference/ecosystem.md`.

## Команды

Единый интерфейс `make <verb>`; `make help` — полный список. Канонический gate перед claim
«готово»/push — **`make check`** = `ruff format --check` + `ruff check` + `lint-imports` +
`mypy` + `pytest -m "not integration"`. `make run` — локальный polling-бот. `make test-integration`
— тесты с Docker (testcontainers redis/nats). Зависимости — `uv` (`make lock`/`make sync`).

## Карта: где что

| Тема | Где |
|---|---|
| Архитектура, слои, гексагон фичи, composition root, жизненный цикл апдейта | `docs/reference/architecture.md` + rule `feature-architecture` |
| Диалоги: окна/getter/handler, навигация, `LaunchMode.ROOT`, `RESET_STACK` | rule `dialog-architecture` + `aiogram-dialog-docs/` |
| Маппинг флоу диалога → файлы фичи | `docs/reference/dialog-mapping.md` |
| State/Redis: JSON-сериализуемость, `with_destiny`, TTL, эволюция StatesGroup | rules `storage-serialization`, `state-lifecycle` + skill `/state-migration` |
| Фоновые апдейты (notifications/jobs), `BgManager`-грабли | rule `background-updates` |
| Observability (`tg_*`/`biz_tg_*`, трейс, health) | `docs/reference/observability.md` + skill `/query-logs` + rule `env-local` |
| Release (образ, handoff, откат) | `docs/reference/release.md` + skill `/release` |
| Экосистема, граница tgbotkit↔шаблон, INFRA-HANDOFF | `docs/reference/ecosystem.md` + rule `tgbotkit-boundary` + skill `/infra-handoff` |
| Тесты (BotClient, фейки, маркеры) | rule `tests-pipeline` |
| Stack-артефакты (вход de-template) | `docs/stack/README.md` + skill `/stack-deep-dive` |
| Устройство `.claude`-системы | `docs/contributing.md` |

## Стиль кода (инварианты)

- **ruff format** обязателен (`make fmt`). **ruff check** (`pyproject.toml`): `S` (bandit),
  `ASYNC`, `TID`, `T20` (запрет `print`), banned-api на `logging` — логи **только** через
  `pylibinfra.logkit.Logger`.
- **mypy strict** + pydantic-плагин: полная типизация; Protocol-порты проверяются структурно.
- **import-linter** (`importlinter.toml`, 3 контракта): слоистость внутри фичи (DIP);
  независимость фич (cross-feature только через `adapters.py`/`provider.py`); чистое ядро
  (`usecase`/`policy`/`state`/`dto`) не импортит `httpx`/`aiogram`/`redis`/`gateway` напрямую.
- Комментарии — только WHY (rule `comments`). `dialog_data`/`start_data` — только JSON-примитивы.
- **Не городить велосипеды**: любой переиспользуемый/инфра-примитив (middleware, runner, новый
  вид рантайма, generic-механика) → **PR в `pylibinfra/tgbotkit`** через `/infra-handoff`, не
  локальная полукалека. Шаблон несёт **только** бизнес-логику и регистрацию в точки расширения.

## Git workflow

- **Conventional Commits** (`scripts/git-hooks/commit-msg`): `feat|fix|refactor|docs|test|chore|meta`,
  subject ≤72. Линейная история, push в `main` через pre-push → `make check`. Хуки ставит `make setup`.
- Коммит/пуш — **только по явной просьбе пользователя**.

## Границы

- **Делать:** фичи (гексагон), контент (`.ftl`), регистрация в `extensions.py`, тесты, доки.
- **Спросить:** новые env/секреты/NATS-subject/webhook (INFRA-HANDOFF); новая инфра-механика
  (это PR в tgbotkit, не правка шаблона); удаление/переименование живого `State` (state-migration).
- **Никогда:** инфра-проводка в шаблоне; `--no-verify`; коммит `.env`/`*.key`; логи через
  `print`/`logging`; несериализуемое в `dialog_data`; удаление живого `State` без deprecation.

## Forward-only

Доки/планы описывают **только текущее состояние** (rule `forward-only`): без «было→стало»,
changelog'ов в прозе, ссылок на прошлые задачи. История — в git.
