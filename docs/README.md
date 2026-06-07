# Документация

Роутер по docs. Три аудитории + design source-of-truth.

## Потребителю шаблона
- [getting-started.md](getting-started.md) — пошаговый путь: форк → проектирование стека (`docs/stack`) → `/de-template` (prune reference-фич) → scaffold своих фич → свой бот. **[META]** — удаляется при де-темплейтизации.

## Контрибьютору шаблона
- [contributing.md](contributing.md) — как устроена `.claude`-система (CLAUDE.md ядро+роутер, skills/rules/agents), git workflow (Conventional Commits, `make check` gate, forward-only), как добавить фичу/диалог. **[META]**.

## Reference (переезжает в проект)
- [reference/architecture.md](reference/architecture.md) — слои, гексагон фичи, composition root, жизненный цикл апдейта, state/Redis, граница tgbotkit↔шаблон.
- [reference/dialog-mapping.md](reference/dialog-mapping.md) — как флоу диалога (окно/переход/getter-данные/состояние) ложится в файлы фичи (`state.py`/`getters.py`/`handlers.py`/`dialogs.py`). Пример на `profile`. Потребляет `scaffold`.
- [reference/observability.md](reference/observability.md) — метрики `tg_*`/`biz_tg_*`, трейс апдейта, корреляция `X-Request-ID`, health, логи.
- [reference/release.md](reference/release.md) — один образ, buildx, handoff в `<org>/infra`, откат.
- [reference/ecosystem.md](reference/ecosystem.md) — роль репо в экосистеме sftbmb, зависимость от `pylibinfra`, INFRA-HANDOFF (2 PR при новой инфра-механике).

## Design source-of-truth
- `design/` — авторитетный архитектурный дизайн (`ARCHITECTURE.md`, `FEATURE-BLUEPRINT.md`, `STACK-AND-TOOLING.md`, `CLAUDE-SYSTEM.md`, `ROADMAP.md`). `docs/` — его сжатая выжимка под текущий код; при расхождении смотри `design/`.
- `aiogram-dialog-docs/` — исчерпывающий референс самой библиотеки `aiogram_dialog`.
- [stack/README.md](stack/README.md) — артефакты платформы/стека (11 kinds, вход для `/de-template`). Остаётся в этом репо.

Точка входа агента в репо — `CLAUDE.md` (ядро + роутер). Дневной флоу — skill `/smartdev`.
