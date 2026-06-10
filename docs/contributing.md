# Contributing — работа с шаблоном через Claude Code

**[META]** Для контрибьютора *самого шаблона*: как устроена `.claude`-система, что enforce'ится
детерминированно, как вмешаться. (Потребителю шаблона — `getting-started.md`.)

## Что где лежит и когда грузится

| Слой | Где | Когда грузится | Сила |
|---|---|---|---|
| Ядро + роутер | `.claude/CLAUDE.md` | всегда, каждый запуск | advisory |
| Path-scoped правила | `.claude/rules/*.md` с `paths:` | когда matching-файл в контексте | advisory |
| Skills (процедуры) | `.claude/skills/<name>/SKILL.md` | по `description` или `/<name>` | procedural |
| Settings / permissions | `.claude/settings.json` | старт сессии | детерминированно (deny) |

Progressive disclosure: на холодном старте — только имена+описания; тела skills/rules и
`references/` грузятся по необходимости.

**Важно про `paths:`** — нативный ключ path-scoping в Claude Code именно `paths:` (не `globs:`).
Правило без `paths:` грузится всегда. Проверь, что новое правило path-scoped.

## Цикл одной задачи

```
prompt → /smartdev (cockpit: make status, читает roadmap, чейнит режим)
       → plan (planning-first: изменение идёт через план — секция в .claude/plans/roadmap.md)
       → act (RED→GREEN→REFACTOR; инфра-поверхность задета → infra-handoff)
       → verify (make test/lint; claim «готово» → make check)
       → commit (Conventional Commits)
```

Планирование — **дефолт** (skill `plan`). Прямая правка — только truly-atomic и багфиксы (→
`triage-failure`, RED-first). Планы живут в едином `.claude/plans/roadmap.md` inline-секциями; done
→ секция удаляется (история в git, forward-only).

## Кто что enforce'ит

| Механизм | Где | Сила |
|---|---|---|
| git-хуки | `scripts/git-hooks/` (ставит `make setup`): commit-msg (Conventional Commits), pre-push (`make check`) | **детерминированно** |
| permissions.deny | `.claude/settings.json` | **детерминированно** (блок `--no-verify`, force-push, правка `.env*`/`*.key`, запись в авто-память) |
| Path-scoped rules | `.claude/rules/*.md` | контекстная подсказка |
| CLAUDE.md | `.claude/CLAUDE.md` | always-on advisory |

Критичные инварианты держат git-хуки + `permissions.deny`; soft-guidance — CLAUDE.md и rules. Push в
`main` через pre-push → `make check`.

## Канонический gate

`make check` = `ruff format --check` + `ruff check` + `lint-imports` (import-linter) + `mypy` +
`pytest -m "not integration"`. Плюс startup-smoke (`pytest -k collision`): `setup_dialogs` без
коллизий `StatesGroup` — кривой State-граф не падает на CI юнитов, но уронит бот на старте.

## Course correction

| Хочется | Как |
|---|---|
| Прервать работу | `Esc` |
| План на одно сообщение | `/plan` |
| Заблокировать путь | `.claude/settings.local.json` → `permissions.deny` |
| После 2 неудачных попыток | `/clear` + переписать запрос |
| Разовый контекст | `@path/to/file` |
| Откатить | `git restore` |

## Что осознанно не делаем

Обоснования (trade-offs) — `docs/reference/architecture.md § Non-goals`: инфра-проводка только в
`tgbotkit`, не плодить полукалеки в шаблоне, без не-JSON в storage, удаление State только через
deprecation.

## Troubleshooting

| Симптом | Куда смотреть |
|---|---|
| Skill не активируется | `description` в frontmatter — переписать конкретнее, «pushy» |
| Path-scoped rule не грузится | frontmatter `paths:` (не `globs:`!) — проверить glob |
| CLAUDE.md игнорируется | длина / конфликт инструкций между секциями |
| Коммит reject'нут | `scripts/git-hooks/commit-msg` — type ∈ {feat,fix,refactor,docs,test,chore,meta} |
| `setup_dialogs` падает на старте | коллизия/удаление живого `State` — `state-migration`, startup-smoke |
| `validate-stack-docs` падает | структура артефакта — `docs/stack/README.md` / `stack-deep-dive` |
| import-linter красный | нарушение слоёв фичи / чистого ядра — `importlinter.toml`, rule `feature-architecture` |
