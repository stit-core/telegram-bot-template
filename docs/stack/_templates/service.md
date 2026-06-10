---
id: stack.service
kind: service
name: service
status: draft
---

# Service — идентичность бота

## Identity
<Имя проекта (`[project] name` в `pyproject.toml`), package path (`src/bot` — внутренний namespace;
многие форки оставляют `bot`), одно-строчное описание роли бота.>
<`project-slug` + `surface`: slug продукта и bot-поверхность в соседнем стратегии-репо —
`/dialog-deep-dive`/`/scaffold` читают дизайн из
`<strategy-path>/docs/projects/<project-slug>/telegram-bot-flow/<surface>/`. `strategy-path`: путь к
форку `<org>/strategy` (дефолт `../strategy` — sibling-чекаут). На каноническом шаблоне не задан.>

## Versioning
<Схема версий (semver `vX.Y.Z`). Как версия и commit попадают в образ (`VERSION`/`GIT_SHA`
build-arg → resource-attrs telemetry). Что логируется на старте (`"starting" service/version/commit`).>

## Image
<Один образ `<host>/<org>/bot:<vX.Y.Z>` (бот stateless, migrate-образа нет; notifications/jobs — в
том же процессе). Что пушится, куда (registry из ecosystem).>

## Generates
<Что de-template родит из этого артефакта:
- `[project] name`/`description` в `pyproject.toml`
- README-шапка
- `VERSION`/`GIT_SHA` в build/release
- лог `"starting" service/version/commit`>
<NB: `project-slug`/`surface`/`strategy-path` из § Identity — не код-вывод de-template, а указатель,
по которому `/dialog-deep-dive` и `/scaffold` находят дизайн диалогов в соседнем стратегии-репо.>
