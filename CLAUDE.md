# telegram-bot-template — гайд для агентов

Тонкий шаблон Telegram-бота stit: **чистая бизнес-логика** на `aiogram` 3.31 + `aiogram_dialog`
2.6 + `dishka` поверх `pylibinfra[tgbotkit]`. Вся инфра бота (Bot/Dispatcher/RedisStorage,
middleware, webhook/polling runner, dishka-setup, error-UX, структурные логи, generic-механика
i18n/notifications/payments/webapp) — **в `pylibinfra/tgbotkit`**, не здесь. В шаблоне — фичи
(диалоги/usecase/ports/policy/state + `infra/`-реализации портов), клиенты API
(`pkg/http_client`), контент (`.ftl`), регистрация в точки расширения kit'а.

Этот файл — **ядро (always-on) + роутер**. Детали — в `docs/`, контекстные инварианты — в
`.claude/rules/` (path-scoped, грузятся на matching-файлах), процедуры — в `.claude/skills/`.
Карта документации — `docs/README.md`.

## Точка входа

- **Как сюда попадают.** Обычно — из корня проекта `~/git/<org>/` сессией корня или её фоновым
  агентом: задачу или фазу программы из плана хаба `<org>/infra` ты выполняешь здесь обвязкой
  этого репо (этот файл, скиллы, гейт `make check`) и возвращаешь в хаб тег образа и
  INFRA-HANDOFF. Прямой заход в репо — тоже нормальный режим с той же обвязкой; всё, что требует
  действия соседей, оформляется блоком `/infra-handoff`.
- **`/smartdev`** — cockpit сессии: сводка `make status` (ветка, рабочее дерево, критичное —
  syntax / draft-стек / infra-touch, активный план) и переход в нужный режим. Запускай в начале
  сессии и после `/clear`.
- **Потребителю шаблона** — `docs/getting-started.md`: форк → `/init-service` → проектирование
  флоу и стека → `/de-template` (prune reference-фич) → `/scaffold` → свой бот.
- **Planning-first.** Любое содержательное изменение идёт через план — файл в `.claude/plans/`
  (skill `/plan`): план переживает `/clear` и виден команде; фаза программы хаба — `parent: infra:<slug>`.
  Прямая правка — для truly-atomic и багфиксов (`/triage-failure`, RED-first).

## Место в экосистеме

Форк `<org>/<bot>` — Telegram-бот, папка `<bot>/` в корне проекта `~/git/<org>/` среди сиблингов
`../strategy`, `../infra`, `../backend` и др.
**Берёт:** дизайн диалогов из `../strategy` (read-only), платформу из `pylibinfra[tgbotkit]`,
данные и события — у продуктовых бэкендов (HTTP API + NATS). **Отдаёт:** образ
`<registry>/<org>/bot:vX.Y.Z` (`/release`) и INFRA-HANDOFF; на этом зона репо заканчивается —
выкатка тега делается только в хабе (`make bump SVC=bot TAG=<v>` в `<org>/infra`). Роль, соседи и
стыки — `docs/reference/ecosystem.md`.

## Проектирование первично, код вторичен

Флоу диалога проектируется **до** кода (`/dialog-deep-dive`: окна, переходы, getter-данные,
состояния виджетов) — это source of truth, код пишется по нему. Если у проекта есть
стратегия-репо `<org>/strategy` (форк `business-strategy-template`, sibling-checkout `../strategy`),
дизайн диалогов приходит **оттуда**: слой `docs/projects/<project-slug>/telegram-bot-flow/<surface>/`,
features-ориентированный — фича `features/<feature>/{dialog.md, window.md, use-case.md}` (диалог + окна
+ use-case'ы бота) плюс сквозные `command.md`/`notification.md` на корне поверхности. Те же понятия, что
в коде: StatesGroup, state, виджеты, getter-контракт, переходы, **use-case бота** (оркестратор поверх
портов — ложится на слой `usecase` фичи), рефы `use-case:<ctx>.<Operation>`/`event:` на домены.
`/dialog-deep-dive` принимает его stable-артефакты как вход (read-only, в strategy не пишем), интервью
— только по дырам.

Платформа/стек — `docs/stack/` (`/stack-deep-dive`). `start`/`profile`/`payments`/`lang`/`booking`/
`notifications` — reference-фичи (изучить, потом prune под свой проект через `/de-template`).

## Команды

Единый интерфейс `make <verb>`; `make help` — полный список. Канонический gate перед claim
«готово»/push — **`make check`** = `ruff format --check` + `ruff check` + `lint-imports` +
`mypy src tests` + `uv lock --check` + `pytest` с полом покрытия (`COVER_FLOOR`, Makefile).
`make run` — локальный polling-бот. `make test-integration`
— тесты с Docker (testcontainers redis/nats). Зависимости — `uv` (`make lock`/`make sync`).

## Карта: где что

| Тема | Где |
|---|---|
| Архитектура, слои, гексагон фичи, composition root, жизненный цикл апдейта | `docs/reference/architecture.md` + rule `feature-architecture` |
| Диалоги: окна/getter/handler, навигация, `LaunchMode.ROOT`, `RESET_STACK` | rule `dialog-architecture` + `aiogram-dialog-docs/` |
| Маппинг флоу диалога → файлы фичи | `docs/reference/dialog-mapping.md` |
| Вход дизайна из стратегии (`<org>/strategy`): слой `telegram-bot-flow` (фичи: dialog/window/use-case + сквозные command/notification) → карта флоу | skill `/dialog-deep-dive` (транслятор) + `docs/reference/dialog-mapping.md` + `ecosystem.md` |
| State/Redis: JSON-сериализуемость, `with_destiny`, TTL, эволюция StatesGroup | rules `storage-serialization`, `state-lifecycle` + skill `/state-migration` |
| Фоновые апдейты (notifications/jobs), `BgManager`-грабли | rule `background-updates` |
| Observability (структурные логи, trace-correlation, health) | `docs/reference/observability.md` |
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
- **import-linter** (`importlinter.toml`, 7 контрактов): слоистость внутри фичи (DIP);
  независимость фич (cross-feature только через `adapters.py`/`provider.py`); чистое ядро
  (`usecase`/`policy`/`state`/`dto`/`ports`/`errors`/`views`/`adapters`) не импортит
  `httpx`/`aiogram`/`redis`/свой `infra/` напрямую; `handlers`/`getters` не зовут `policy`
  (доменные решения — в usecase); `pkg` не знает про features/platform/aiogram; `httpx` — только
  в `pkg`; presentation не ходит в `pkg`. **Одна дверь к бэкенду:** клиенты/ошибки/wire — через
  `bot.pkg.http_client`; `pylibinfra.httpclient` вне pkg запрещён ruff banned-api (TID251).
- Комментарии — только WHY (rule `comments`). `dialog_data`/`start_data` — только JSON-примитивы.
- **Не городить велосипеды**: любой переиспользуемый/инфра-примитив (middleware, runner, новый
  вид рантайма, generic-механика) → **PR в `pylibinfra/tgbotkit`** через `/infra-handoff`, не
  локальная полукалека. Шаблон несёт только бизнес-логику и регистрацию в точки расширения.

## Git workflow

- **Conventional Commits** (`scripts/git-hooks/commit-msg`): типы
  `feat|fix|refactor|docs|test|chore|meta|perf|build|ci|style`, заголовок ≤72. Линейная история,
  push в `main` через pre-push → `make check`. Хуки ставит `make setup`.
- Коммит и пуш — только по явной просьбе пользователя: история репо — его решение.

## Границы

- **Делать:** фичи (гексагон), pkg-клиенты, контент (`.ftl`), регистрация в `app.py`
  (`ExtensionProvider`), тесты, доки.
- **Спросить:** новые env/секреты/NATS-subject/webhook (INFRA-HANDOFF — это действие хаба);
  новая инфра-механика (это PR в tgbotkit, не правка шаблона); удаление/переименование живого
  `State` (state-migration).
- **Не делать:** инфра-проводку в шаблоне (она живёт в kit'е); `--no-verify` (обходит гейт
  pre-push); коммит `.env`/`*.key` (секреты); логи через `print`/`logging` (теряются
  trace-correlation и redact); несериализуемое в `dialog_data` (падает на записи в Redis); удаление
  живого `State` без deprecation (ломает открытые диалоги пользователей в проде).

## Forward-only

Доки/планы описывают **только текущее состояние** (rule `forward-only`): без «было→стало»,
changelog'ов в прозе, ссылок на прошлые задачи. История — в git.
