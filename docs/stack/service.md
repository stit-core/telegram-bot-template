---
id: stack.service
kind: service
name: service
status: draft
---

# Service — идентичность бота

## Identity
<Имя бота, Python-пакет (`src/<pkg>`, по умолчанию `bot`), одно-строчное описание роли.
Пример: `myorg-shop-bot` — витрина магазина в Telegram (каталог, оплата Stars, уведомления
о заказах). Владелец, SLO (целевая доступность / время отклика на апдейт).>

## Versioning
<Схема версий (semver `vX.Y.Z`). Как версия/commit попадают в образ: `ARG SERVICE_VERSION`/
`GIT_COMMIT` → `OTEL_SERVICE_VERSION`/`GIT_COMMIT` env → resource-attrs telemetry. Что логирует
`emit_startup` на старте (версия/commit).>

## Image
<Один образ `<host>/<org>/telegram-bot:vX.Y.Z` (бот stateless, migrate-образа нет). Build —
multi-stage uv (`Dockerfile`), `ENTRYPOINT python -m <pkg>`. См. docs/reference/release.md.>

## Generates
<Что de-template родит:
- import-path: rename пакета `bot` → `<pkg>` (в `src/`, `pyproject.toml [tool.hatch...]`,
  `Dockerfile` ENTRYPOINT, импорты)
- README-шапка
- `OTEL_SERVICE_NAME`/`OTEL_SERVICE_VERSION` дефолты в `config.py`/`.env.example`
- лог `emit_startup` (service/version/commit на старте)>
