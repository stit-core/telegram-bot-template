# Contributing — работа с шаблоном через Claude Code

**[META]** Для контрибьютора *самого шаблона*: как устроена `.claude`-система, что
enforce'ится детерминированно, как добавить фичу/диалог. (Потребителю шаблона —
[getting-started.md](getting-started.md).)

## Что где лежит и когда грузится

| Слой | Где | Когда грузится | Сила |
|---|---|---|---|
| Ядро + роутер | `CLAUDE.md` (реальный файл) | всегда, каждый запуск | advisory |
| Path-scoped правила | `.claude/rules/*.md` с `paths:` | когда matching-файл в контексте | advisory |
| Skills (процедуры) | `.claude/skills/<name>/SKILL.md` | по `description` или `/<name>` | procedural |
| Subagent'ы | `.claude/agents/*.md` | когда основной агент делегирует | role-specific |
| Settings / permissions | `.claude/settings.json` | старт сессии | детерминированно (deny) |

Progressive disclosure: на холодном старте — только имена+описания; тела skills/rules и
`references/` грузятся по необходимости.

**Важно про `paths:`** — нативный ключ path-scoping в Claude Code именно `paths:` (не
`globs:`). Правило без `paths:` грузится всегда. У шаблона правила scoped по `.py`-путям
(`src/bot/features/**`, `**/dialogs.py`, `**/state.py`, `platform/dialogs/states.py` и т.д.).

## Skills (зеркало go-template + бот-специфика)

| Skill | Роль |
|---|---|
| `smartdev` | Always-on cockpit: `make status`, читает roadmap, чейнит в нужный режим |
| `plan` | Planning-first: задача → атомы → секция в `.claude/plans/roadmap.md` |
| `triage-failure` | RED-first разбор падения (тест/lint/типы/`emit_startup`-smoke) |
| `init-service` | Оркестратор онбординга форка (см. getting-started) |
| `de-template` | Развернуть форк в самостоятельный проект (rename, prune reference, wiring) |
| `stack-deep-dive` | Проектирование платформы через раунды вопросов, фиксация в `docs/stack/` |
| `scaffold` | `feature`/`dialog`/`window`/`backend-port`/`middleware`/`job`/`notification` |
| `dialog-deep-dive` | Проектирование флоу диалога (окна/переходы/getter-данные) до кода |
| `state-migration` | Безопасная эволюция `StatesGroup` (deprecation, не ломать живые кнопки) |
| `preview-flow` | Граф переходов / HTML-preview окон как ревью-артефакт |
| `infra-handoff` | Оформить INFRA-HANDOFF при изменении инфра-поверхности |
| `release` | Запушить образ + агрегированный handoff (один образ) |

## Цикл одной задачи

```
prompt → /smartdev (cockpit: make status, читает roadmap, чейнит режим)
       → plan (planning-first: изменение идёт через план — секция в .claude/plans/roadmap.md)
       → act (RED→GREEN→REFACTOR; инфра-поверхность задета → infra-handoff)
       → verify (make test/lint/typecheck; claim «готово» → make check)
       → review (опц. subagent reviewer)
       → commit (Conventional Commits)
```

Планирование — **дефолт**. Прямая правка — только truly-atomic и багфиксы (→ `triage-failure`).
Планы живут в едином `.claude/plans/roadmap.md` inline-секциями; done → секция удаляется
(история в git).

## Кто что enforce'ит

| Механизм | Где | Сила |
|---|---|---|
| git-хуки | `scripts/git-hooks/` (ставит `make setup`): commit-msg (Conventional Commits), pre-commit, pre-push (`make check`) | **детерминированно** |
| permissions.deny | `.claude/settings.json` | **детерминированно** (блок `--no-verify`, коммит `.env`/`*.key`) |
| import-linter | `importlinter.toml` (3 контракта: слои фичи / независимость фич / чистое ядро) | **детерминированно** (в `make check`) |
| mypy strict | `pyproject.toml` (Protocol-порты проверяются структурно) | **детерминированно** (в `make check`) |
| Path-scoped rules | `.claude/rules/*.md` | контекстная подсказка |
| CLAUDE.md | repo root | always-on advisory |

Claude Code хуков (PreToolUse/PostToolUse/Stop) в шаблоне **нет** — критичные инварианты держат
git-хуки + `permissions.deny` + `make check`; soft-guidance — CLAUDE.md и rules. Push в `main`
разрешён (прямой или PR); gate — `pre-push → make check`. История линейная, forward-only.

## Git workflow

- **Conventional Commits** (`scripts/git-hooks/commit-msg`): типы `feat|fix|refactor|docs|test|
  chore|meta`, формат `<type>(<scope>)?: <subject>`, subject ≤72.
- **Forward-only:** текст (доки/комментарии) описывает только текущее состояние, не историю
  (история — в git). Комментарии в коде — только WHY.
- Перед push — `make check` зелёный (ruff format + ruff check + import-linter + mypy + pytest
  без integration).

## Как добавить фичу

Фича = вертикальный гексагон `src/bot/features/<name>/` (зеркало go-домена). Эталон полного
гексагона — `profile/`; сокращённые (`start`/`lang`) опускают `gateway/ports/dto/views`.

1. `/scaffold feature <name>` — разворачивает файлы + `Provider` + регистрацию.
2. **StatesGroup** добавляется в `platform/dialogs/states.py` (единый каталог — разрыв циклов
   импорта). Эволюция — через deprecation (skill `state-migration`).
3. **Регистрация** в `src/bot/extensions.py`: диалог → `RouterBundle`, команда → `CommandBundle`
   (`CommandSpec`), NATS-подписчик → `NotifierBundle`.
4. **import-linter:** добавь фичу в `containers`/`modules` контрактов (`importlinter.toml`).
5. **Тексты:** `locales/<lang>/<feature>.ftl` + ресурс в `config.py` (`_I18N_RESOURCES`).
6. **Тесты:** unit (policy/views), `dialog`-flow (BotClient), backend (mock gateway).
7. `make check` зелёный.

Инварианты слоёв — `.claude/rules/feature-architecture.md`; скелеты файлов —
`design/FEATURE-BLUEPRINT.md`. Слой инъекции: `getter`/dialog-`handler` → `@inject` из
`dishka.integrations.aiogram_dialog`; dispatcher-level (`/start`, `pre_checkout`) → `@inject`
из `dishka.integrations.aiogram`.

## Как добавить окно/диалог

- **Окно в существующий диалог:** новый `State` в `StatesGroup` + `Window(...)` в `dialogs.py`
  (+ getter, если есть динамика; + handler, если есть реакции). `/scaffold window`.
- **Новый диалог в фиче:** `Dialog(Window…)` + новая `StatesGroup`. Корневой диалог —
  `LaunchMode.ROOT`; `/start` всегда `StartMode.RESET_STACK` (иначе стек копится до 100 →
  `DialogStackOverflow`). `/scaffold dialog`.
- Маппинг «флоу → файлы» — [reference/dialog-mapping.md](reference/dialog-mapping.md).

## Граница tgbotkit — что НЕ делать в шаблоне

Новая инфра-механика (middleware, новый вид рантайма, error-handler-механика, generic-обёртка
над `BgManager`) — **не правка шаблона, а PR в `pylibinfra/tgbotkit`** через `infra-handoff`
(rule `tgbotkit-boundary`). В шаблоне — только бизнес и регистрация в точки расширения kit'а.
См. [reference/ecosystem.md](reference/ecosystem.md) § INFRA-HANDOFF.

## Troubleshooting

| Симптом | Куда смотреть |
|---|---|
| Skill не активируется | `description` в frontmatter — переписать конкретнее, «pushy» |
| Path-scoped rule не грузится | frontmatter `paths:` (не `globs:`!) — проверить glob |
| `import-linter` падает | импорт нарушает слой/независимость — см. `importlinter.toml` и rule `feature-architecture` |
| `mypy` ругается на Protocol | адаптер не удовлетворяет порту структурно — сверь сигнатуры методов |
| Коммит reject'нут | `commit-msg` — type ∈ {feat,fix,refactor,docs,test,chore,meta} |
| Несериализуемое в Redis | `dialog_data`/`start_data` — только JSON-примитивы (rule `storage-serialization`) |
| Кнопка → `UnknownIntent`/`State` | устаревший стек после рестарта/TTL; обрабатывает `AppErrorUX` → reset |
