# Contributing — работа с шаблоном через Claude Code

**[META]** Для контрибьютора *самого шаблона*: как устроена `.claude`-система, что enforce'ится
детерминированно, как вмешаться. (Потребителю шаблона — `getting-started.md`.)

## Что где лежит и когда грузится

| Слой | Где | Когда грузится | Сила |
|---|---|---|---|
| Ядро + роутер | `CLAUDE.md` (корень репо) | всегда, каждый запуск | advisory |
| Path-scoped правила | `.claude/rules/*.md` с `paths:` | когда matching-файл в контексте | advisory |
| Skills (процедуры) | `.claude/skills/<name>/SKILL.md` | по `description` или `/<name>` | procedural |
| Сабагенты | `.claude/agents/<name>.md` (`explorer`, `reviewer`) | по делегированию (`description`) | read-only |
| Settings / permissions | `.claude/settings.json` | старт сессии | детерминированно (deny) |

Progressive disclosure: на холодном старте — только имена+описания; тела skills/rules и
`references/` грузятся по необходимости.

**Форматы Claude Code.** Path-scoping правила — только ключ `paths:` (не `globs:`); правило без
`paths:` грузится всегда. У сабагента обязателен `name` (= имя файла): без него файл не
загружается как агент. `description` + `when_to_use` скилла в листинге обрезаются на 1536 символах
— ключевой сценарий первым; SKILL.md — до 500 строк, детали — в `references/`. CLAUDE.md держим
короче 200 строк: всё, что не нужно в каждой сессии, — в rules, docs или references.

## Цикл одной задачи

```
prompt → /smartdev (cockpit: make status, читает активные планы, чейнит режим)
       → plan (planning-first: изменение идёт через план — файл в .claude/plans/)
       → act (RED→GREEN→REFACTOR; инфра-поверхность задета → infra-handoff)
       → verify (make test/lint; claim «готово» → make check)
       → commit (Conventional Commits)
```

Планирование — **дефолт** (skill `plan`). Прямая правка — только truly-atomic и багфиксы (→
`triage-failure`, RED-first). Планы — файлы `.claude/plans/<slug>.md`, бэклог —
`.claude/plans/backlog.md`; закрытый план удаляется (история в git, forward-only).

## Кто что enforce'ит

| Механизм | Где | Сила |
|---|---|---|
| git-хуки | `scripts/git-hooks/` (ставит `make setup`): commit-msg (Conventional Commits), pre-commit (ruff format/check), pre-push (`make check`) | **детерминированно** |
| permissions.deny | `.claude/settings.json` | **детерминированно** (блок `--no-verify`, force-push, `reset --hard`/`clean -f`/`rm -rf`, чтение и правка `.env`/`.env.local`/`*.key`/`*.pem`, правка `uv.lock` и авто-памяти; сама авто-память выключена `autoMemoryEnabled: false`) |
| Path-scoped rules | `.claude/rules/*.md` | контекстная подсказка |
| CLAUDE.md | `CLAUDE.md` (корень репо) | always-on advisory |

Критичные инварианты держат git-хуки + `permissions.deny`; soft-guidance — CLAUDE.md и rules. Push в
`main` через pre-push → `make check`.

## Канонический gate

`make check` = `ruff format --check` + `ruff check` + `lint-imports` (import-linter) +
`mypy src tests` + `uv lock --check` + `pytest -m "not integration and not e2e"` с полом покрытия
(`COVER_FLOOR`). Startup-smoke (`pytest -k collision`: `setup_dialogs` без коллизий `StatesGroup`)
входит в этот прогон и гоняется точечно после правок состояний: кривой State-граф не виден юнитам,
но роняет бот на старте.

## Course correction

| Хочется | Как |
|---|---|
| Прервать работу | `Esc` |
| Сначала план, потом правки | `/plan` (план в `.claude/plans/`) |
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
| Skill не активируется | `description` в frontmatter — ключевой сценарий первым, категории намерений конкретнее |
| Path-scoped rule не грузится | frontmatter `paths:` (не `globs:`) — проверить glob |
| Сабагент не виден | нет `name` во frontmatter `.claude/agents/<name>.md` |
| CLAUDE.md игнорируется | длина (цель — меньше 200 строк) / конфликт инструкций между секциями |
| Коммит reject'нут | `scripts/git-hooks/commit-msg` — type ∈ {feat,fix,refactor,docs,test,chore,meta,perf,build,ci,style}, заголовок ≤72 |
| `setup_dialogs` падает на старте | коллизия/удаление живого `State` — `state-migration`, startup-smoke |
| `validate-stack-docs` падает | структура артефакта — `docs/stack/README.md` / `stack-deep-dive` |
| import-linter красный | нарушение слоёв фичи / чистого ядра — `importlinter.toml`, rule `feature-architecture` |
