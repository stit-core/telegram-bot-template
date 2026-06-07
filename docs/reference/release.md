# Release

**Зона ответственности этого репо: код → image в registry. На этом — STOP.** Деплой,
vault-patch, проверка на проде — другие репо (см. [ecosystem.md](ecosystem.md)). Skill — `/release`.

## Один образ

Бот **stateless** (FSM/диалоги в Redis) → migrate-образа нет, init-контейнера нет. Один образ
`telegram-bot:<tag>` крутит и polling, и webhook (режим — `BOT_MODE`). Это упрощает релиз
относительно go-эталона (там api+migrate lockstep).

Образ — multi-stage uv (`Dockerfile`): builder ставит `uv sync --frozen --no-dev`, runtime —
slim-Python под непривилегированным юзером, `ENTRYPOINT ["python", "-m", "bot"]`. Приватная
`pylibinfra` (git+https) тянется на этапе sync с build-secret `git_token` (через `git insteadOf`)
— секрет не остаётся в слоях. `ARG SERVICE_VERSION`/`GIT_COMMIT` → resource-attrs telemetry.

## Одна команда

На чистом `main` после зелёного `make check`:

```
make release VERSION=vX.Y.Z
```

`scripts/release.sh` одним проходом: confirm → annotated tag → preflight (ветка/clean/semver/
`docker login`) → `docker buildx build --push` **одного** образа
`<host>/<org>/telegram-bot:vX.Y.Z` → агрегированный INFRA-HANDOFF → STOP.

`<host>`/`<org>` берутся из `git remote get-url origin` — image-path следует за местом репо в
Gitea, без правок при форке. Build локальный (не gitea-runner). CI собирает образ только на
`main`/тегах для проверки (`telegram-bot:<sha>`), но **не пушит** — push делает `make release`.

## INFRA-HANDOFF

`make release` печатает агрегированный блок (накопленные `## Infra impact` из плана + vault/ship-
подсказки) — кому что передать инфра-админу out-of-band. Сам репо `vault kv patch` / `make ship` /
`ssh` **не выполняет**. Инфра-поверхность, требующая handoff: новый/изменённый env или секрет
(`BOT_*`/`REDIS_URL`/`NATS_*`/`HTTPCLIENT_*`/`OTEL_*`), webhook-URL/secret, новый cross-service
NATS-subject (notifications), смена runtime-режима (polling↔webhook → меняется число инстансов).

## Топологии (handoff в infra)

| Режим | Инстансы | Особенности |
|---|---|---|
| `BOT_MODE=polling` | **1** инстанс | long-polling, HTTP-сервера нет |
| `BOT_MODE=webhook` | **≥2** инстанса | поверх httpkit (ingress/TLS), `RedisEventIsolation` (мультиинстанс), single-flight `set_webhook`; health `/health`+`/ready` |

На проде секреты (`BOT_TOKEN`, `BOT_WEBHOOK_SECRET`) рендерит vault-agent в env. Сам деплой —
в `<org>/infra` (форк project-infra-template-compose): `make ship` → ssh-deploy → force-recreate.

## Откат

Образ уже в registry — пересборка не нужна. Полностью в infra-репо: корп-патч на предыдущий тег +
`make ship`. Граждан shutdown в kit'е (drain in-flight → `container.close()` → `bot.session.close()`)
делает rolling-replace безопасным.

## Versioning

Semver `vX.Y.Z`. Версия/commit зашиваются в образ через `ARG SERVICE_VERSION`/`GIT_COMMIT` →
`OTEL_SERVICE_VERSION`/`GIT_COMMIT` env → resource-attrs telemetry. На старте `emit_startup`
логирует версию/commit — на проде сразу виден крутящийся коммит. Conventional Commits, forward-only.
