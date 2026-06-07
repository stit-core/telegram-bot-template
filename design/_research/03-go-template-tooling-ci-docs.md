# 03 · Тулинг, dev-loop, CI, Docker, доки и ecosystem-контракт (зона C)

Исследование `go-backend-template` (Go-эталон тулинга/CI/доки) + `pylibinfra`
(уже реализованный Python-аналог dev-loop) + `project-infra-template-compose`
(deploy-звено). Цель — спроектировать симметричный слой для `telegram-bot-template`
(aiogram + aiogram_dialog, поверх `pylibinfra`).

Источники (все пути абсолютные от `/root/git/sftbmb/sftbmb-core/`):
- `go-backend-template/{Makefile,Dockerfile,Dockerfile.migrate,.dockerignore,.golangci.yml,sqlc.yaml,.mockery.yml,README.md,CONTRIBUTING.md,SECURITY.md,.gitignore,.env.example,.env.local.example}`
- `go-backend-template/scripts/{tools/*,git-hooks/*,release*.sh,install-tools.sh,local-deps.sh,new-domain.sh}`
- `go-backend-template/docs/**` (getting-started, contributing, README, reference/{architecture,ecosystem,release,observability,domain-mapping}, stack/{README,_templates/*})
- `pylibinfra/{pyproject.toml,.python-version,uv.lock,.gitea/workflows/ci.yml,CONTRIBUTING.md,README.md,CLAUDE.md,.gitignore}`
- `project-infra-template-compose/{Makefile,compose/backend.yml,scripts/ship.sh}`

Принципиальная развилка зоны C: **go-эталон зеркалим по смыслу (verbs/гейты/таксономия
доки/ecosystem-контракт), но реализацию берём Python-первой — как уже сделано в
`pylibinfra`** (uv + ruff + mypy + pytest + Gitea Actions). Бот — это **сервис** (как
backend), а не библиотека (как pylibinfra), поэтому к pylibinfra-петле добавляем
Docker-образ, релиз-в-registry и handoff в infra (как у go-backend).

---

## 1. Makefile-verbs и гейты → Python-аналог (uv/ruff/mypy/pytest)

### 1.1 Go-эталон: один словарь `make <verb>` для агента

`go-backend-template/Makefile` — единый интерфейс для smartdev-агента, сгруппирован
секциями `##@ LOOP/GEN/DB/E2E/SCAFFOLD/INTEL/RELEASE/SETUP/META/DEV/EXTRA`.
Concise-by-default: `test`/`lint`/`build` идут через обёртки `scripts/tools/*.sh`,
которые печатают одну строку на зелёном и сжатый разбор на красном; `FORMAT=detailed`
/ `VERBOSE=1` — расширенный/сырой вывод. Passthrough-аргументы унифицированы:
`PKG=`, `A=`, `Q=/P=`, `NAME=`, `VERSION=`.

Канонический гейт — **`make check`** (`Makefile:46`): `fmt → go vet → lint → test →
build → gen-check`. Он же висит на `pre-push` (`scripts/git-hooks/pre-push:19` →
`exec make check`). Состояние репо для агента — `make status` (`scripts/tools/status.sh`,
always-on cockpit, секции `== Name ==`, финальная строка `OK`/`ATTENTION: <что>`);
fail-fast preflight — `make doctor` (`scripts/tools/doctor.sh`, классы FAIL/WARN,
`OK:`/`FAIL: N blocking`). `make gen` = `sqlc generate` + `mockery`; `gen-check` —
проверка дрейфа сгенерированного (`git diff --exit-code`).

Сжатые обёртки парсят машинный вывод инструмента: `test.sh` — `go test -json` (по
умолчанию только изменённые пакеты из `git diff`, `-race` гейтится по `CGO_ENABLED`);
`lint.sh` — `golangci-lint --output.json.path` + `jq`. Это паттерн «инструмент → JSON →
человекочитаемая выжимка», который надо повторить на Python.

### 1.2 Python-аналог: `pylibinfra` уже задал петлю

`pylibinfra` использует **uv** (`uv.lock` есть, `.python-version` = `3.13`, но
`requires-python = ">=3.12"` и `target-version="py312"` в ruff/mypy) и команды
(`pylibinfra/CLAUDE.md`, `CONTRIBUTING.md`, `README.md § Локальная разработка`):

| Go-гейт | Python-аналог (pylibinfra) | Назначение |
|---|---|---|
| `gofumpt -w .` / `gofumpt -l .` | `uv run ruff format` / `ruff format --check .` | формат |
| `golangci-lint run` | `uv run ruff check .` | lint |
| `go vet ./...` | покрывается `ruff` + `mypy` | статанализ |
| (типобезопасность Go) | `uv run mypy src` (`strict=true`) | типы |
| `go test -short` | `uv run pytest -m "not integration"` | быстрые тесты |
| `go test` (+integration tags) | `uv run pytest` (маркер `integration` = testcontainers) | полные |
| `go build` | `uv build` (для lib) / docker build (для сервиса) | сборка |
| `sqlc + mockery` (`make gen`) | — (у бота кодогена нет; см. §1.4) | gen |

ruff-конфиг pylibinfra (`pyproject.toml:95-128`): `line-length=100`, select-набор
`E,W,F,I,UP,B,SIM,C4,PIE,PT,N,ASYNC,S,TID,RUF` — где `S`(bandit)≈gosec, `I`(isort)
встроен (один инструмент вместо gofumpt+goimports+gosec+staticcheck). mypy `strict=true`
+ `plugins=["pydantic.mypy"]`. pytest: `asyncio_mode="auto"`, маркер `integration`,
`--strict-markers --import-mode=importlib`.

### 1.3 Рекомендация для бота: `Makefile` поверх uv, тот же словарь verbs

Бот — **сервис**, поэтому петля = pylibinfra-проверки **плюс** сервисные verbs
go-backend (build/release/e2e/migrate/local-deps/status/doctor). Заводим `Makefile`
(агенту привычнее `make <verb>`, чем помнить uv-команды; go-эталон, infra-compose и
pylibinfra-CLAUDE все говорят на `make`/`uv run`):

```
##@ LOOP
fmt      → uv run ruff format .
lint     → uv run ruff check .        (VERBOSE=1 — сырой; concise-обёртка опц.)
typecheck→ uv run mypy src tests
test     → uv run pytest -m "not integration" -q   (PKG=/-k passthrough)
check    → fmt(--check) + lint + typecheck + test  (канонический gate, pre-push)
##@ DB
migrate-up/down → uv run python -m bot.migrate up/down  (yoyo-migrations из pylibinfra/pgkit)
##@ E2E
e2e / e2e-smoke → docker-стек + pytest (telegram-mock / aiogram-tester)
##@ INTEL
status   → scripts/tools/status.sh   (git/roadmap/build/drift — порт go-варианта)
doctor   → scripts/tools/doctor.sh   (docker-auth/env/migration-pairs)
##@ RELEASE
release VERSION=vX.Y.Z → confirm → tag → preflight → docker buildx push → handoff → STOP
##@ DEV
local-deps-up/down → postgres/nats/redis контейнеры (порт local-deps.sh)
##@ SETUP
setup    → uv sync + git-хуки
```

`make check` — единственный канонический гейт; зелёный = claim «готово» (как
`pylibinfra/CLAUDE.md § Команды`). На `pre-push` вешаем `make check`.

### 1.4 Чего у бота НЕТ из go-петли (важно для не-gold-plating)

- **`sqlc` / `make gen` / `gen-check`** — go-специфика (typed SQL codegen). У Python
  на asyncpg кодогена нет: SQL пишется в репозиториях руками (как kit'ы pylibinfra).
  Если бот вообще без своей БД (FSM-storage в Redis) — `migrate-*`/`persistence`
  опускаем целиком.
- **`mockery`** — Python мокает через `unittest.mock`/`pytest` фикстуры; отдельного
  gen-шага нет → секцию GEN не заводим.
- **`go vet`** — растворяется в ruff+mypy.
- **concise JSON-обёртки `tools/*.sh`** — у pytest/ruff человекочитаемый вывод из
  коробки. Обёртки опциональны; для агента полезен только `status.sh`/`doctor.sh`
  (cockpit/preflight) — их портируем, остальное — нет.

---

## 2. Dockerfile/контейнеризация → Python multi-stage uv

### 2.1 Go-эталон

`go-backend-template/Dockerfile` — multi-stage с агрессивным кешем:
- stage `build` (`golang:1.26-alpine`), параметризован `ARG TARGET=api`
  (один Dockerfile собирает `cmd/api` и через `Dockerfile.migrate` — `cmd/migrate`),
  `ARG VERSION/GIT_SHA` зашиваются `-ldflags="-X main.version -X main.commit"`;
- кеши через `--mount=type=cache` (apk, go-mod, go-build), приватные deps через
  `--mount=type=ssh` + `--mount=type=secret,id=netrc` + `ENV GOPRIVATE=git.sftbmb.ru/*`;
- runtime stage — `alpine:3.21` + `ca-certificates`, `COPY --from=build /app`,
  `EXPOSE 8080`, `ENTRYPOINT ["/app"]`. CGO_ENABLED=0, статический бинарь.
- `Dockerfile.migrate` — почти копия, но `ENTRYPOINT` = migrate-бинарь и `COPY
  migrations /migrations` (init-контейнер). Два образа `backend` + `backend-migrate`
  пушатся **lockstep** одним тегом (`scripts/release.sh:52-61`).
- `.dockerignore` исключает `.git/.gitea/.claude/docs/bin/*.md/*_test.go/testdata/.env*`.

### 2.2 Python multi-stage uv (рекомендация для бота)

Симметричная структура, но uv вместо go toolchain. Канонический паттерн:

```dockerfile
# --- build stage ---
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# слой deps отдельно от кода (кеш переживает правки бота):
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=ssh \
    uv sync --frozen --no-install-project --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=ssh \
    uv sync --frozen --no-dev
# --- runtime stage ---
FROM python:3.13-slim
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
# webhook-режим (FastAPI/uvicorn): EXPOSE 8080; polling: порт не нужен
ENTRYPOINT ["python", "-m", "bot"]
```

Ключевые соответствия Go→Python:
- `--mount=type=cache` go-mod/go-build → **uv cache** (`/root/.cache/uv`); deps-слой
  bind-mount'ит только `uv.lock`+`pyproject.toml` → кеш переживает правки кода.
- `GOPRIVATE` + ssh/netrc → **`--mount=type=ssh`** для `pylibinfra @ git+ssh://…`
  (приватная Gitea, `pylibinfra/README.md § Доступ к репозиторию`). `uv sync --frozen`
  ставит ровно из `uv.lock`.
- `-ldflags version/commit` → версию/commit прокидываем `ARG VERSION/GIT_SHA` →
  env-переменные образа, читаются в `telemetry.Config` (`service.version`); на старте
  лог `"starting" service=bot version=… commit=…` (паттерн `release.md § Versioning`).
- **migrate-образ**: если у бота есть Postgres — отдельный `Dockerfile.migrate`
  с yoyo-runner (pylibinfra/pgkit migrate) + `COPY migrations`, lockstep с основным.
  Если бот stateless/Redis-FSM — миграционный образ не нужен (не gold-plate).
- `.dockerignore` — портировать go-список, заменив go-специфику на Python:
  `.venv/ __pycache__/ .pytest_cache/ .ruff_cache/ .mypy_cache/ *.egg-info/`.

**Подводный камень**: `python:3.13-slim` без build-toolchain не соберёт пакеты с
C-расширениями (`asyncpg`, `argon2-cffi`, `psycopg2-binary` — все в deps pylibinfra).
uv ставит wheel'ы (бинарные) — обычно ок; если какой-то deps без wheel под целевую
платформу, добавить `apt-get install build-essential` **только в build-stage**.

---

## 3. CI (Gitea Actions)

### 3.1 pylibinfra уже задал шаблон (`.gitea/workflows/ci.yml`)

3 job'а (`lint` / `test` / `build`), trigger `push: ["**"]` + `pull_request: [main]`.
Каждый job: `actions/checkout@v4` → `astral-sh/setup-uv@v5` (`enable-cache: true`) →
`uv sync --frozen` → команды:
- **lint**: `ruff format --check .` → `ruff check .` → `mypy src`
- **test**: `pytest -m "not integration" -q` (быстрая полоса) → `pytest -q` (полная,
  testcontainers на `ubuntu-latest` с Docker)
- **build**: `uv build`

Это прямой аналог go-`make check`, но разложенный на параллельные CI-job'ы.

### 3.2 Рекомендация для бота

Базируемся на pylibinfra-workflow, но т.к. бот — **сервис**, заменяем `build: uv build`
на **docker build образа** и добавляем релизный job по тегу:

1. **`ci.yml`** (push/PR): `lint` (ruff format --check + ruff check + mypy src tests) +
   `test` (pytest "not integration" → pytest full). Идентично pylibinfra.
2. **`release.yml`** (trigger `push: tags: ["v*"]`): `docker buildx build --push`
   образа бота (`+ migrate`, если есть БД) lockstep-тегом. Но go-эталон делает
   **release локально** (`docs/reference/release.md`: «Build локальный, без
   gitea-runner'ов»; `scripts/release.sh`) — решение по боту: можно так же оставить
   `make release` локальным и CI-релиз не заводить (меньше секретов в runner'е).
3. **Кеш**: `setup-uv@v5 enable-cache: true` (как pylibinfra) — обязательно, иначе
   каждый job заново резолвит ~100 deps из `uv.lock` (466 KB).
4. **Приватный pylibinfra в CI**: `uv sync --frozen` тянет `pylibinfra @ git+…` —
   нужен deploy-token/ssh-key Gitea в secrets job'а (либо Gitea PyPI-registry,
   `pylibinfra/README.md` упоминает оба пути).

**Решения по CI (для резюме): (а)** копируем pylibinfra `ci.yml` 1:1 для lint/test;
**(б)** `build` → docker buildx (сервис, не lib); **(в)** релиз держим локальным
(`make release`), как go-эталон, CI-publish опционален; **(г)** uv-cache + Gitea-token
для приватного pylibinfra обязательны.

---

## 4. git-hooks + conventional commits

### 4.1 Go-эталон (`scripts/git-hooks/`, ставятся `make setup`)

- **`commit-msg`**: regex `^(feat|fix|refactor|docs|test|chore|meta)(\(scope\))?(!)?: .{1,72}$`.
  SSOT по типам — комментарий явно требует менять regex и CLAUDE.md одним коммитом.
- **`pre-commit`**: `gofumpt -l` (формат) → `go vet` → `golangci-lint run` → условные
  валидаторы (`validate-stack-doc.sh` если тронуты `docs/stack/*.md`; `validate-plan.sh`
  если тронут roadmap).
- **`pre-push`**: гонит весь `make check`. `--no-verify` запрещён политикой (+ блок в
  `permissions.deny`); аварийный обход — только `SKIP_PREPUSH=1`.

Сила (`docs/contributing.md § Кто что enforce'ит`): git-хуки + `permissions.deny` —
**детерминированно**; CLAUDE.md/rules — advisory. Claude-Code-хуков (PreToolUse и т.п.)
в шаблоне нет — критичные инварианты держат git-хуки.

### 4.2 pylibinfra и Python-аналог

pylibinfra (`CONTRIBUTING.md § Перед PR`) использует те же Conventional Commits, но
**типы без `meta`**: `feat,fix,refactor,docs,test,chore`. go-backend добавляет `meta`
(для правок самих rules/шаблона). Для бота-сервиса — взять go-набор (с `meta`), т.к.
бот тоже шаблон с `.claude`-мета-слоем.

Рекомендуемые хуки бота (порт go-варианта на Python):
- **`commit-msg`**: тот же regex, типы `feat|fix|refactor|docs|test|chore|meta`.
- **`pre-commit`**: `uv run ruff format --check .` → `uv run ruff check .` →
  `uv run mypy src` (+ условный `validate-stack-doc.sh`, если заводим docs/stack — см. §5).
- **`pre-push`**: `make check`.
- `make setup` копирует хуки в `.git/hooks/` + `chmod +x` + `uv sync` (порт
  `Makefile:113-119` + `install-tools.sh`, но вместо go-install pinned-tools — `uv sync`,
  т.к. uv пинит всё через `uv.lock`; отдельный install-tools.sh почти не нужен).

---

## 5. Документная таксономия (docs/stack, docs/reference) → что заводим у бота

### 5.1 Go-эталон: три аудитории + design-SoT (`docs/README.md`)

- **Потребителю**: `getting-started.md` ([META], удаляется при де-темплейтизации) —
  путь форк → `/init-service` → стек → `/de-template` → scaffold доменов.
- **Контрибьютору**: `contributing.md` ([META]) — устройство `.claude`-системы,
  что enforce'ится, troubleshooting.
- **Reference** (переезжает в проект): `architecture.md`, `domain-mapping.md`,
  `observability.md`, `release.md`, `ecosystem.md`.
- **Design SoT**: домены — в **соседнем** docs-репо (`project-docs-template`);
  `docs/stack/` — платформа сервиса, остаётся в репо.

### 5.2 `docs/stack/` — 8 singleton-артефактов + валидатор

`docs/stack/README.md`: 8 kinds (по одному файлу), вход для skill `/de-template`:

| kind | что описывает | релевантность для бота |
|---|---|---|
| `service` | имя, module path, версионирование, бинари | да (имя bot, версия, образ) |
| `runtime` | что крутится в `cmd/api` (HTTP/outbox/NATS/jobs) | да — **polling vs webhook**, dispatcher, timerkit-jobs |
| `config` | required/optional env, секреты (Vault-класс) | да — `BOT_TOKEN`, webhook-secret, PG/Redis DSN |
| `persistence` | Postgres: driver, миграции, пул | опц. — только если у бота своя БД/FSM-в-PG |
| `messaging` | NATS/outbox subjects | опц. — если бот publish/consume события |
| `auth` | authn/authz, роли, brute-force | переосмыслить — Telegram-admin allowlist/RBAC по user_id |
| `observability` | telemetry-режим, resource attrs, biz-метрики | да — `biz_bot_*`, update-handler spans |
| `dependencies` | pylibinfra kits, внешние deps, ёмкость | да — какие kit'ы + aiogram/aiogram_dialog |

Каждый артефакт обязан иметь секцию **`Generates`** (что из него родится в коде —
контракт для `/de-template`). Frontmatter: `id: stack.<name>`, `kind`, `name`(==basename),
`status: draft|stable`. Gate: `/de-template` не стартует пока не все `stable` +
`make validate-stack-docs` зелёный. `_templates/<kind>.md` — болванки.

Валидатор `scripts/tools/validate-stack-doc.sh` (bash+awk, без зависимостей): проверяет
frontmatter, `basename==name`, `id=="stack.<name>"`, наличие обязательных H2-секций
для kind, и при `status: stable` — что секции непусты. **Портируется без изменений**
(чистый bash, не go-специфика) — только список обязательных H2 на kind адаптировать
под бота (напр. для `runtime` бота: `Polling/Webhook`, `Dispatcher`, `Jobs`, `Generates`).

### 5.3 Рекомендация для бота

Заводим **ту же таксономию**, адаптируя kinds под Telegram-специфику:
- `docs/README.md` (роутер) + `getting-started.md` [META] + `contributing.md` [META];
- `docs/reference/`: **`architecture.md`** (слои бота: handlers/dialogs/services/repo,
  middlewares, FSM, граница с pylibinfra), **`observability.md`** (порт go-варианта,
  `biz_bot_*`), **`release.md`** (порт — образ → registry → handoff), **`ecosystem.md`**
  (место бота в sftbmb), и **новый** `dialogs.md` или `aiogram-mapping.md` (как
  DDD-артефакт/UX-сценарий ложится в aiogram_dialog windows/states — аналог
  go-`domain-mapping.md`);
- `docs/stack/` — 8 kinds, но **persistence/messaging опускаем, если бот их не
  использует** (не gold-plate); `runtime` переосмыслить (polling/webhook вместо
  HTTP-сервера), `auth` → Telegram-admin/allowlist. Валидатор и `_templates/`
  портируем.
- skill-имена адаптировать: `/de-template`, `/scaffold` (вариант dialog/handler
  вместо domain), `/stack-deep-dive` — аналогично go.

---

## 6. Ecosystem / release-контракт

### 6.1 Место в экосистеме (`docs/reference/ecosystem.md`)

5 форкаемых шаблонов `sftbmb-core/` + 2 lib (`golibinfra`/`pylibinfra` + `ui-lib`).
Корп control-plane = `corp-infra-template` (managed `*.sftbmb.ru` / self-hosted форк
`<org>/infra`). go-backend форкается в `<org>/backend`; **telegram-bot форкнется в
`<org>/bot`** (по аналогии). Каждый сервисный шаблон:
- **зависит от** lib (`pylibinfra` для бота) + корп-контракта (tenant, OTLP, registry);
- **build+push** образ `git.${DOMAIN}/<org>/bot:<vX.Y.Z>`;
- **STOP на image-in-registry** — деплоем не занимается, handoff в `<org>/infra`.

### 6.2 Контракт с корп-инфрой (одинаков для backend и bot)

- **registry** `git.${DOMAIN}` — push образа (build локальный).
- **Vault** `vault.${DOMAIN}`, AppRole `projects-<p>-<env>` — секреты (`BOT_TOKEN`,
  PG_DSN, webhook-secret) рендерит vault-agent в `.runtime/secrets/*.env` на VPS.
- **OTLP** `otel.${DOMAIN}` — Bearer=`OTEL_TOKEN`; **инвариант `service_namespace ==
  tenant`**: приложение ставит только `service.name`/`service.version`/
  `deployment.environment.name`, а `tenant`/`service.namespace` force-сетит корп
  otel-collector из `X-Scope-OrgID` (`reference/observability.md`,
  `pylibinfra/README.md § Обязательные resource attrs`). Бот этот инвариант **наследует
  бесплатно через pylibinfra/telemetry** — корп-дашборды Apps/* работают без правок.
- **Self-hosted без вендор-лока**: `OTEL_EXPORTER_OTLP_ENDPOINT`/`VAULT_ADDR`/
  `REGISTRY_HOST` в `.env` (`.env.example`) — меняется только хост.

### 6.3 Release-флоу (`scripts/release.sh` + `docs/reference/release.md`)

`make release VERSION=vX.Y.Z` одним проходом: confirm-промпт (неинтерактивно →
отмена; `RELEASE_YES=1` для CI) → annotated tag (rich changelog) → `release-preflight`
(ветка=main / clean / annotated semver / buildx + `make doctor`) → `docker buildx
--push` lockstep (api+migrate, для бота — bot[+migrate]) → **агрегированный
INFRA-HANDOFF** → STOP. Image-path выводится из `git remote get-url origin` (форк
работает без правок). semver `vX.Y.Z` обязателен; `:latest`/`:edge`/lightweight-теги
отвергаются (анти-паттерн повторён в `pylibinfra/README.md § Anti-patterns`).

### 6.4 Handoff в infra (`project-infra-template-compose`)

`compose/backend.yml`: образ `${REGISTRY_HOST}/${PROJECT_NAME}/backend:${BACKEND_TAG}`,
`profiles:[backend]`, env из vault-agent-rendered `.runtime/secrets/*.env`, traefik-
роутинг, healthcheck `/health`. Для бота — аналогичный `compose/bot.yml` (webhook →
traefik-роут + healthcheck; polling → без traefik, healthcheck на внутренний `/health`
от httpkit или liveness-проба процесса). Handoff-цепочка (`release.md § Handoff`):
- **корп**: `vault kv patch kv/projects/<p>/<env>/meta bot_tag=vX.Y.Z`
- **проект** (`<org>/infra`): `make ship` (`scripts/ship.sh`) → ssh-deploy → vault-agent
  рендерит `BOT_TAG` → force-recreate.
Бот-репо `vault kv patch`/`make ship`/`ssh` **сам не выполняет** — только печатает
агрегированный handoff-блок (порт `release.sh` awk-агрегации `**Infra impact.**` из
roadmap).

### 6.5 Что портировать дословно vs переосмыслить

| Портировать ~1:1 | Переосмыслить под бота |
|---|---|
| ecosystem-контракт (tenant/OTLP/Vault/registry) | `runtime` kind (polling/webhook вместо HTTP) |
| release-флоу (`release.sh`, preflight, handoff, semver-gate) | `auth` (Telegram admin/allowlist вместо JWT/session) |
| INFRA-HANDOFF агрегация из roadmap | migrate-образ (только если есть БД) |
| `status.sh`/`doctor.sh` cockpit/preflight | `domain-mapping.md` → `dialog-mapping.md` |
| Conventional Commits + git-хуки + gates | sqlc/mockery/gen — **выкинуть** (нет в Python) |
| docs-таксономия + stack-валидатор | concise JSON tool-обёртки — опционально |

---

## Приложение: env-разделение (`.env` vs `.env.local`)

go-эталон чётко разделяет (портировать для бота):
- **`.env`** (`.env.example`) — runtime app env для локального запуска (`go run ./cmd/api`
  → для бота `python -m bot`): минимум чтобы процесс поднялся (`BOT_TOKEN`,
  `PG_DSN`/`REDIS_URL`, `OTEL_SERVICE_NAME=bot`, `APP_ENV=dev`, `OTEL_STDOUT_ONLY=true`).
  Остальное — code-defaults pylibinfra. На VPS — Vault+vault-agent.
- **`.env.local`** (`.env.local.example`) — dev-tooling креды (НЕ runtime): токены для
  e2e-стека и чтения прод-логов (`SFTBMB_OBS_TOKEN`, `OTEL_TENANT`). Парсится grep'ом,
  не sourcing'ом; секреты не эхо-ятся в чат.
- `.gitignore`/`.dockerignore`: `.env`/`.env.local`/`*.pem`/`*.key` + `permissions.deny`
  на их правку (`SECURITY.md`).
