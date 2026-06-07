# 12 · Конфиг, секреты и деплой бота (зона L)

Поверхность конфигурации Telegram-бота (pydantic-settings поверх `pylibinfra`),
Vault-раскладка и flow секретов, `.env`/`.env.local`, Dockerfile, локальный compose
и топологии деплоя (polling vs webhook) + release/handoff.

Источники (абсолютные пути от `/root/git/sftbmb/sftbmb-core/`):
- `telegram-bot-template/design/_research/04-pylibinfra-core-kits.md` — config-кит
  (env+Vault Source-композиция), telemetry/logkit/httpkit Config-поля и их env-alias'ы.
- `telegram-bot-template/design/_research/03-go-template-tooling-ci-docs.md` §2,§6,
  приложение — Dockerfile-паттерн, release/handoff, `.env` vs `.env.local`.
- `telegram-bot-template/design/_research/07-modern-aiogram-stack.md` §2,§3 —
  polling/webhook API, `secret_token`, RedisStorage/RedisEventIsolation.
- `corp-infra-template/docs/ecosystem.md` — Tenant identity, Vault layout, AppRole,
  resource-attrs, Image registry.
- `corp-infra-template/docs/project-secrets.md` — flow секретов, `seed-project-secrets.sh`,
  `/request-secret`, rotation, observability read API.
- `project-infra-template-compose/` — `compose/backend.yml`, `compose/vault-agent.yml`,
  `compose/otel-agent.yml`, `configs/vault-agent/templates/*.tpl`, `.env*.example`.
- `go-backend-template/{Dockerfile,.dockerignore,.env.example,.env.local.example,scripts/release.sh}`.

Главный инвариант зоны L (зеркалит go-backend): **бот = фронтенд-сервис**. В local-dev
секреты берутся из ENV (`vault_client=None`); на VPS — **единственный источник правды —
Vault**, vault-agent рендерит `.runtime/secrets/bot.env`, репо бота **деплоем не
занимается** — STOP на image-in-registry + handoff в `<org>/infra`
(`ecosystem.md § Image registry`, `03 §6.1`).

---

## 1. Поверхность конфига бота (env / Vault таблица)

Стратегия как в pylibinfra/go-backend: **подавляющее большинство — code-defaults
китов pylibinfra**, в env-файлах объявляем только обязательное + local-dev-удобства;
**секреты (`BOT_TOKEN`, `WEBHOOK_SECRET`) — только Vault** (в local-dev допустимы в `.env`).

Pydantic-классы бота наследуют конвенции китов (`04 §invariants`): `BaseSettings`,
`extra="ignore"`, `populate_by_name=True`, env через `validation_alias` (= public API,
менять = breaking), таймауты в **секундах (float)**.

Колонка «Источник»: **env** = всегда из окружения (на VPS — `.runtime/env/compose.env`
или inline в `compose/bot.yml`); **Vault** = `kv/projects/<p>/<env>/...`, vault-agent
рендерит в `.runtime/secrets/bot.env`; **kit-default** = поле кита pylibinfra с дефолтом,
переопределяем только при необходимости. «Режим»: P=polling, W=webhook, both.

### 1.1 Идентичность / телеметрия (наследуется от китов, оба режима)

| ENV-имя | Источник | Класс/кит | Режим | Обяз. | Дефолт / примечание |
|---|---|---|---|---|---|
| `OTEL_SERVICE_NAME` | env | `telemetry.Config.service_name` | both | **да** | `bot` (нет kit-дефолта — обязателен) |
| `OTEL_SERVICE_VERSION` | env (из Docker `ARG VERSION`) | `telemetry.Config.service_version` | both | нет | `dev`; в образе прошивается релизной версией |
| `APP_ENV` | env | `telemetry.Config.environment` / `logkit.ServiceConfig` | both | нет | `dev`; на VPS `${ENV}` → `deployment.environment.name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | env | `telemetry.Config.otlp_endpoint` | both | нет | local `localhost:4318`; на VPS `otel-agent:4318` |
| `OTEL_EXPORTER_OTLP_INSECURE` | env | `telemetry.Config.otlp_insecure` | both | нет | `True`; на VPS `true` (внутр. сеть до otel-agent) |
| `OTEL_TOKEN` | **Vault** (`otel.token`) | `telemetry.Config.otlp_bearer_token` | both | да* | Bearer к OTLP edge; на VPS из `.runtime/secrets/otel.env` |
| `OTEL_TENANT` | env (vault-agent: `<p>-<env>`) | `telemetry.Config.tenant` | both | нет | force-сетит корп collector; local — `""`/из `.env.local` |
| `OTEL_STDOUT_ONLY` | env | `telemetry.Config.stdout_only` | both | нет | local-dev `true` (без OTLP-коллектора); прод `false` |
| `OTEL_TRACES_SAMPLER_ARG` | kit-default | `telemetry.Config.sample_ratio` | both | нет | `1.0`; non-secret tuning в compose при необходимости |
| `LOG_LEVEL` | env | `logkit.Config.level` | both | нет | `info` |
| `LOG_REDACT_ENABLED` / `LOG_REDACT_PATTERNS` | kit-default | `logkit.RedactConfig` | both | нет | PII-redact; вкл. для прода (`true`) |

\* `service.namespace == tenant` — корп-инвариант, ставит collector; бот наследует
бесплатно через `pylibinfra/telemetry` (`ecosystem.md § resource-attrs`, `04 §2`).

### 1.2 Telegram-ядро (специфика бота — НЕ в pylibinfra)

| ENV-имя | Источник | Режим | Обяз. | Дефолт / примечание |
|---|---|---|---|---|
| `BOT_TOKEN` | **Vault** (`bot.token`) | both | **да** | **секрет!** local-dev — `.env`; на VPS — `.runtime/secrets/bot.env` |
| `BOT_MODE` | env | both | нет | `polling` (local) / `webhook` (прод). Определяет ветку bootstrap |
| `BOT_ADMIN_IDS` | env | both | нет | CSV tg user_id (`12345,67890`); allowlist админ-команд (`03 §5.2 auth`) |
| `BOT_DEFAULT_LOCALE` | env | both | нет | `ru`; i18n fallback-локаль |
| `BOT_DROP_PENDING_UPDATES` | env | both | нет | `true` для dev/первого старта; backlog-сброс (`07 §2.1`) |
| `BOT_PARSE_MODE` | kit/code-default | both | нет | `HTML` (`DefaultBotProperties`, `07 §4.1`) |
| `BOT_ALLOWED_UPDATES` | code (не env) | both | — | **не env**: `dp.resolve_used_update_types()` авто-выводит (`07 §2`); хардкодить не нужно |

### 1.3 Webhook (только W; в polling — отсутствуют/игнорируются)

| ENV-имя | Источник | Режим | Обяз.(W) | Дефолт / примечание |
|---|---|---|---|---|
| `WEBHOOK_BASE_URL` | env | W | да | `https://bot.${DOMAIN}` — публичный URL для `set_webhook` |
| `WEBHOOK_PATH` | env | W | нет | `/webhook/<rand>`; обфусцированный путь (defense-in-depth) |
| `WEBHOOK_SECRET` | **Vault** (`bot.webhook_secret`) | W | да | **секрет!** 1–256 `[A-Za-z0-9_-]`; сверяется с `X-Telegram-Bot-Api-Secret-Token` (`07 §2.2`) |
| `HTTP_ADDR` | kit-default | W | нет | `httpkit.Config`, `:8080` (если webhook через httpkit/FastAPI, `04 §8`) |
| `HTTP_RATE_LIMIT_RPS` | env | W | нет | поднять/`0` — Telegram шлёт с пула IP, per-IP-лимит может бить 429 (`04 §8 warn4`) |

> Если webhook через **aiohttp `SimpleRequestHandler`** (рекоменд. `07 §2.4`),
> `secret_token` валидирует фреймворк; httpkit не нужен. Если через **FastAPI**
> (единый ASGI с pylibinfra) — `HTTP_*` от httpkit активны, **секрет проверяем сами**
> (issue #1024, `07 §2.3`).

### 1.4 FSM-storage / шина

| ENV-имя | Источник | Режим | Обяз. | Дефолт / примечание |
|---|---|---|---|---|
| `REDIS_URL` | **Vault** (`redis.url`) или env | both | да** | FSM RedisStorage + RedisEventIsolation (`07 §3`); local `redis://localhost:6379/0` |
| `BOT_FSM_TTL` | env | both | нет | `state_ttl`/`data_ttl` сек — чтобы Redis не пух (`07 §3`) |
| `NATS_URL` | **Vault** (`nats.url`) или env | both | опц. | только если бот publish/consume события; local `nats://localhost:4222` |

\** Redis в проекте обычно сосед в той же приватной сети (как Postgres), пароль — Vault;
URL без креда может быть env. Если Redis с паролем — весь URL рендерит vault-agent.

### 1.5 Бэкенд-клиенты (вызовы go-backend; httpx, `07 §1`)

Бот-фронтенд ходит в один/несколько бэкендов. Паттерн зеркалит go (BACKEND_*_BASE_URL +
таймаут + circuit-breaker; ретраи — `tenacity` из pylibinfra, `07 §4.3`).

| ENV-имя | Источник | Режим | Обяз. | Дефолт / примечание |
|---|---|---|---|---|
| `BACKEND_API_BASE_URL` | env | both | да*** | `http://backend:8080` (внутри проектной сети) |
| `BACKEND_API_TIMEOUT` | env | both | нет | `10.0` сек (float) |
| `BACKEND_API_BREAKER_THRESHOLD` | env | both | нет | порог открытия circuit-breaker |
| `BACKEND_API_BREAKER_RESET` | env | both | нет | `30.0` сек до half-open |
| `BACKEND_API_TOKEN` | **Vault** (`bot.backend_token`) | both | опц. | если бэкенд требует service-to-service auth |

\*** обязателен, если бот реально дёргает бэкенд; для нескольких бэкендов — префикс
на каждый (`BACKEND_ORDERS_BASE_URL`, …), как `BACKEND_<NAME>_*`.

### 1.6 Прочее (опц.)

| ENV-имя | Источник | Кит | Примечание |
|---|---|---|---|
| `FEATURE_FLAGS` | env | `flagkit.Config` | `new_onboarding=true,...` — kill-switch хэндлеров (`04 §5`) |
| `VAULT_ADDR` / `VAULT_TOKEN` / `VAULT_NAMESPACE` | env | `config.VaultClientConfig` | local-dev пусто → `vault_client=None` → секреты из ENV (`04 §1`) |

**Итог по разбивке env|Vault:** в Vault идут ровно 4 бот-специфичных секрета —
`BOT_TOKEN`, `WEBHOOK_SECRET` (W), и при необходимости `REDIS_URL`/`NATS_URL` (если с
паролем) и `BACKEND_*_TOKEN`. Плюс наследуемый `OTEL_TOKEN` из always-on `otel.env`.
Всё остальное — env-tuning поверх kit-defaults.

---

## 2. Vault-раскладка и flow секретов

### 2.1 Где лежит и кто читает

KV-объект под бот — **новый project-specific slug `bot`** в существующей раскладке
`kv/projects/<p>/<env>/` (`ecosystem.md § Vault layout`, `project-secrets.md`).
Существующие `otel`/`meta` reserved (onboard-flow), `db`/`oidc`/… — для бэкенда;
бот добавляет свой объект через `/request-secret` → `seed-project-secrets.sh`.

```
kv/projects/<p>/<env>/
  otel            # token, accountID         — onboard-flow, always-on (OTEL_TOKEN/_TENANT)
  meta            # backend_tag, bot_tag, ... — onboard-flow; bot_tag добавляет release-handoff
  bot             # token, webhook_secret, backend_token?, redis_url?  — НОВЫЙ, через /request-secret
  redis           # url/password   — опц., если выделенный объект (иначе url-поле в bot)
```

Маппинг на `project-secrets.md`: бот следует семантике «KV-объект существует ⟹ явно
засеян» (lazy seed, нет mute-stub'ов). Объект `bot` **не стартует в profile**, пока
корп-админ его не засеял — как `db`/`minio` гейтят свои profiles.

### 2.2 AppRole / policy — наследуется без изменений

Бот использует **тот же** AppRole `projects-<p>-<env>` и policy `projects-<p>-<env>-read`
(`ecosystem.md § AppRole`, `project-secrets.md`): `read+list` на
`kv/data/projects/<p>/<env>/*` + `kv/metadata/.../*`. Объект `bot` попадает под `/*` —
**отдельная политика/роль не нужна**. Multi-env hard isolation сохраняется
(dev-VPS не читает prod-`bot`).

### 2.3 Как `pylibinfra.config` грузит (Source-композиция, `04 §1`)

Модель: env читается **нативно** pydantic-settings (базовый слой), Vault накладывается
`VaultSource` как init-kwargs (приоритетнее env — **Vault перезатирает env-defaults**).

```python
from pydantic import BaseModel
from pylibinfra.config import load, VaultClientConfig, VaultSource, new_vault_client

class BotSecrets(BaseModel):
    bot_token: str
    webhook_secret: str = ""          # обязателен только в webhook-режиме

vc = new_vault_client(VaultClientConfig())   # None в local-dev (VAULT_ADDR пуст)
secrets = load(
    BotSecrets,
    VaultSource(vc, "kv/projects/<p>/<env>/bot",
                mapping={"token": "BOT_TOKEN", "webhook_secret": "WEBHOOK_SECRET"}),
)
# local-dev: vc=None → VaultSource no-op → BOT_TOKEN/WEBHOOK_SECRET из ENV (.env).
```

**Важно для боевого VPS:** в проектной экосистеме секреты на самом деле читает не сам
бот через hvac, а **vault-agent** (sidecar логинит AppRole, рендерит `bot.env`), и бот
получает их уже как **ENV** через `env_file`. Значит на VPS `config`-кит/`VaultSource`
**не обязателен** — бот может грузить голый `BaseSettings` из ENV (как go-backend читает
`PG_DSN` из rendered `backend.env`). `config.ConfigProvider`+`VaultSource` нужен только
если бот ходит в Vault **сам** (напр. local против реального dev-Vault) — `04 §1`
прямо отмечает: «`config` кит опционален».

### 2.4 vault-agent template (новый `bot.env.tpl` в `<org>/infra`)

В проектном infra-форке добавляется template (зеркалит `backend.env.tpl`) + блок в
`agent.hcl.parts/bot.hcl`, активируемый `COMPOSE_PROFILES=bot`:

```gotemplate
# configs/vault-agent/templates/bot.env.tpl  → .runtime/secrets/bot.env (perms 0400)
{{ with secret (printf "kv/data/projects/%s/%s/bot" (env "PROJECT_NAME") (env "ENV")) }}
BOT_TOKEN={{ .Data.data.token }}
WEBHOOK_SECRET={{ .Data.data.webhook_secret }}
{{- if .Data.data.backend_token }}
BACKEND_API_TOKEN={{ .Data.data.backend_token }}
{{- end }}
{{ end }}
```

`bot_tag` (image rollout) идёт в **always-on `meta.env.tpl`** рядом с `backend_tag`
(оба → `.runtime/env/compose.env` для `compose --env-file`).

### 2.5 Rotation (зеркалит `project-secrets.md § Rotation`)

| Что | Как |
|---|---|
| `BOT_TOKEN` (revoke через @BotFather) | `vault kv patch kv/projects/<p>/<env>/bot token=NEW` → `make ship` → vault-agent перерендерит → force-recreate |
| `WEBHOOK_SECRET` | `vault kv patch … webhook_secret=NEW` → `make ship`; бот на старте делает `set_webhook` с новым secret (single-flight, см. §6.3) |
| `bot_tag` (версия образа) | `vault kv patch kv/projects/<p>/<env>/meta bot_tag=vX.Y.Z` → `make ship` (как `backend_tag`) |

---

## 3. `.env.example` и `.env.local.example`

Разделение точно как go-backend (`03 приложение`): `.env` — runtime app env для
`python -m bot` (минимум, чтобы процесс поднялся; на VPS заменяется Vault+vault-agent);
`.env.local` — dev-tooling креды (НЕ runtime: query-logs/Loki), парсится grep'ом.

### 3.1 `.env.example`

```dotenv
# Local-dev .env для `python -m bot`. Минимум, чтобы процесс поднялся.
# Прод-env живёт в <org>/infra: секреты (BOT_TOKEN, WEBHOOK_SECRET, OTEL_TOKEN) — в
# Vault, рендерятся vault-agent'ом в .runtime/secrets/bot.env; non-secret tuning —
# inline в compose/bot.yml `environment:`. Остальное — code-defaults pylibinfra-китов.

# ─── Required ─────────────────────────────────────────────────────────
BOT_TOKEN=123456:replace-me-local-test-token   # local: реальный токен из @BotFather; прод: Vault
OTEL_SERVICE_NAME=bot
REDIS_URL=redis://localhost:6379/0

# ─── Local-dev удобства ───────────────────────────────────────────────
APP_ENV=dev
BOT_MODE=polling                 # webhook требует публичный TLS-URL → не для local
OTEL_STDOUT_ONLY=true            # без локального OTLP-коллектора всё в stdout
BOT_DROP_PENDING_UPDATES=true
# BOT_ADMIN_IDS=12345,67890
# BOT_DEFAULT_LOCALE=ru

# ─── Бэкенд (если бот дёргает go-backend локально) ────────────────────
BACKEND_API_BASE_URL=http://localhost:8080
# BACKEND_API_TIMEOUT=10.0

# ─── Webhook (только BOT_MODE=webhook; для local обычно не нужно) ──────
# WEBHOOK_BASE_URL=https://<your-tunnel>.example
# WEBHOOK_PATH=/webhook/local
# WEBHOOK_SECRET=local-secret-1234

# ─── Control-plane эндпоинты (two-paths: managed / self-hosted) ───────
# В проде задаёт <org>/infra (Vault/compose), не этот файл. Вендор-лока нет.
# OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.sftbmb.ru:443
# VAULT_ADDR=https://vault.sftbmb.ru
# REGISTRY_HOST=git.sftbmb.ru
```

### 3.2 `.env.local.example`

```dotenv
# .env.local.example — dev-tooling креды (НЕ runtime-секреты приложения).
# Скопируй в .env.local (gitignored). Парсится grep'ом, не sourcing'ом —
# без многострочных значений и $-подстановок. Токены в чат не вытаскивать.
#
# Назначение: чтение прод-логов/трейсов (scripts/tools/logs.sh / скилл /query-logs)
# и e2e-стек. Источник токена — корп-Vault kv/projects/<p>/<env>/otel (там ротация).

# Bearer для корп-observability (Loki/Tempo read API). Tenant зашит в токене.
SFTBMB_OBS_TOKEN=replace-me

# Адрес корп-Loki read API для logs.sh / query-logs. Обязателен (FAIL при пустом).
#   managed:     https://loki.sftbmb.ru
#   self-hosted: свой Loki из форка corp-infra-template
SFTBMB_LOKI_ADDR=https://loki.sftbmb.ru

# Tenant для e2e otel-agent. Совпадает с service_namespace (корп-инвариант). 
OTEL_TENANT=replace-me
```

`.gitignore`/`.dockerignore`: `.env`/`.env.local`/`*.pem`/`*.key` + `permissions.deny`
на их правку (`SECURITY.md`, `03 приложение`). Текущий `.gitignore` бота уже игнорит
`.env` — дополнить `.env.local`, `*.local`, `*.pem`, `*.key`.

---

## 4. Dockerfile (multi-stage uv) + .dockerignore

Зеркалит go-backend (`03 §2`): multi-stage, агрессивный кеш, приватный `pylibinfra`
через `--mount=type=ssh`, версия/commit прокидываются `ARG` → env образа → `service.version`.

```dockerfile
# Dockerfile — образ Telegram-бота. Symmetry с go-backend/Dockerfile, но uv вместо go.
ARG BUILDPLATFORM=linux/amd64
ARG TARGETPLATFORM=linux/amd64

# ─── build stage ───
FROM --platform=$BUILDPLATFORM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# openssh-client — для git+ssh://… приватного pylibinfra из Gitea (через --mount=type=ssh).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      git openssh-client ca-certificates && rm -rf /var/lib/apt/lists/*
RUN mkdir -p -m 0700 /root/.ssh && \
    ssh-keyscan git.sftbmb.ru >> /root/.ssh/known_hosts 2>/dev/null || true

# Слой deps отдельно от кода: bind-mount только uv.lock+pyproject.toml → кеш
# переживает правки кода бота (как go-mod cache в go-эталоне).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=ssh \
    uv sync --frozen --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=ssh \
    uv sync --frozen --no-dev

# ─── runtime stage ───
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"

ARG VERSION=dev
ARG GIT_SHA=unknown
ENV OTEL_SERVICE_VERSION=${VERSION} BOT_GIT_SHA=${GIT_SHA}

# webhook-режим: uvicorn/aiohttp слушает 8080. polling: порт не нужен (EXPOSE безвреден).
EXPOSE 8080
# curl — для healthcheck в webhook (HTTP /health); polling — liveness по процессу.
# HEALTHCHECK гейтится compose'ом (см. §6), но образу полезен curl в runtime-stage.
ENTRYPOINT ["python", "-m", "bot"]
```

Соответствия Go→Python (`03 §2.2`): go-mod/go-build cache → **uv cache**
(`/root/.cache/uv`); `GOPRIVATE`+ssh → `--mount=type=ssh` для `pylibinfra @ git+ssh://…`;
`-ldflags version/commit` → `ARG VERSION/GIT_SHA` → env → `service.version` + лог
`"starting" service=bot version=… commit=…` на старте.

**Без migrate-образа:** бот stateless (FSM в Redis), своей БД нет → отдельный
`Dockerfile.migrate` **не заводим** (не gold-plate, `03 §2.2`). Если у конкретного
форка появится Postgres — добавить позже, lockstep.

**Подводный камень** (`03 §2.2`): `python:3.13-slim` без toolchain не соберёт C-extensions
(`asyncpg`/`argon2-cffi` в deps pylibinfra) из исходников. uv ставит wheel'ы — обычно ок;
если deps без wheel под целевую платформу — `apt-get install build-essential`
**только в build-stage**.

### `.dockerignore` (порт go-списка, Python-специфика)

```gitignore
.git
.gitignore
.gitea
.github
.claude
.idea
.vscode
docs
design
aiogram-dialog-docs
*.md
tests
.venv
__pycache__
.pytest_cache
.ruff_cache
.mypy_cache
*.egg-info

# Local secrets. Дублирует .gitignore — на случай non-buildx builds без COPY-фильтрации.
.env
.env.local
*.pem
*.key
```

---

## 5. Локальное окружение (compose для dev)

Цель — поднять зависимости бота локально (как `local-deps.sh` go-эталона, `03 §1.3`):
**redis** (FSM/isolation) + опц. **nats** + опц. **otel-collector** (или `OTEL_STDOUT_ONLY=true`).
Бот в dev запускается `python -m bot` (polling) **вне** compose; compose даёт только deps.

```yaml
# compose.dev.yml — НЕ деплой, только локальные зависимости бота. Прод-стек — <org>/infra.
services:
  redis:
    image: redis:8-alpine          # FSM RedisStorage + RedisEventIsolation (07 §3)
    ports: ["6379:6379"]
    command: ["redis-server", "--save", "", "--appendonly", "no"]   # ephemeral dev
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 2s
      retries: 10

  nats:                            # опц. — только если бот publish/consume события
    image: nats:2-alpine
    ports: ["4222:4222"]
    profiles: [nats]

  otel-collector:                  # опц. альтернатива OTEL_STDOUT_ONLY=true
    image: otel/opentelemetry-collector-contrib:0.151.0   # пин как в проектной инфре
    command: ["--config=/etc/otel/config.yaml"]
    volumes: ["./dev/otel-collector.yaml:/etc/otel/config.yaml:ro"]
    ports: ["4318:4318"]
    profiles: [otel]               # без профиля → стек только redis; логи бота в stdout
```

Увязка с `project-infra-template-compose`: pin образов redis/nats/otel-collector — те же
линии, что в проектной инфре (otel-collector `0.151.0`, как `compose/otel-agent.yml`).
Дефолтный dev-путь — `OTEL_STDOUT_ONLY=true` (телеметрия в stdout, коллектор не нужен);
`--profile otel` поднимает локальный collector, когда нужно проверить реальный OTLP-экспорт.
`make local-deps-up` = `docker compose -f compose.dev.yml up -d redis`.

---

## 6. Топологии деплоя

### 6.1 Polling (dev / простой прод; 1 инстанс)

- **Без ingress/TLS:** нет входящего HTTP — Telegram не достучивается, бот сам тянет
  `getUpdates` (`07 §2.1`, `04 §webhook-vs-polling`). httpkit **не нужен**.
- **Строго 1 инстанс:** Telegram отдаёт `getUpdates` эксклюзивно одному поллеру; второй
  параллельный поллер → `409 Conflict`. Масштабирование горизонтально **невозможно**.
- **compose/bot.yml (polling):** без traefik-labels, без публикации портов.
  Healthcheck — liveness процесса; если хочется HTTP `/health` без вебхуков, можно
  поднять минимальный httpkit с `rps=0` (`04 §webhook-vs-polling`), но это опционально.
- **Когда:** local-dev, low-traffic прод, среды без публичного TLS-эндпоинта.

```yaml
# <org>/infra: compose/bot.yml — polling-вариант
services:
  bot:
    image: ${REGISTRY_HOST:-git.sftbmb.ru}/${PROJECT_NAME}/bot:${BOT_TAG}
    container_name: bot
    restart: unless-stopped
    profiles: [bot]
    environment:
      APP_ENV: ${ENV}
      OTEL_SERVICE_NAME: bot
      BOT_MODE: polling
      OTEL_EXPORTER_OTLP_ENDPOINT: otel-agent:4318
      OTEL_EXPORTER_OTLP_INSECURE: "true"
      REDIS_URL: redis://redis:6379/0
      BACKEND_API_BASE_URL: http://backend:8080
    env_file:
      - .runtime/secrets/otel.env    # OTEL_TOKEN + OTEL_TENANT (always-on)
      - .runtime/secrets/bot.env     # BOT_TOKEN (+ WEBHOOK_SECRET для webhook)
    depends_on:
      vault-agent: { condition: service_healthy }
      redis:       { condition: service_healthy }
      otel-agent:  { condition: service_healthy }
    networks: [backend-net]          # НЕ proxy: входящий трафик не нужен
    # polling: liveness по процессу. Если нужен HTTP /health — добавить httpkit (rps=0).
    healthcheck:
      test: ["CMD", "test", "-f", "/proc/1/cmdline"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

### 6.2 Webhook (прод за ingress/TLS; ≥1, опц. ≥2 инстанса)

- **За traefik/TLS:** Telegram POST'ит на `https://bot.${DOMAIN}${WEBHOOK_PATH}`; traefik
  терминирует TLS, роутит на контейнер (как `compose/backend.yml`). secret_token
  (`X-Telegram-Bot-Api-Secret-Token`) проверяется фреймворком (aiohttp `SimpleRequestHandler`)
  или вручную (FastAPI, `07 §2.2-2.3`).
- **Горизонтальное масштабирование ≥2 инстансов ВОЗМОЖНО** (в отличие от polling): traefik
  балансит вебхуки, **общий FSM-state и event-isolation в Redis** — `RedisStorage` +
  `RedisEventIsolation` (`storage.create_isolation()`, `07 §3`) дают per-user распределённый
  lock, так что апдейты одного юзера не гонятся между инстансами.
- **healthcheck:** HTTP `/health` (httpkit регистрирует `/health` liveness + `/ready`;
  `04 §8`), `traefik` роутит как backend.
- **Per-IP rate-limit:** Telegram шлёт вебхуки с пула IP — `HTTP_RATE_LIMIT_RPS` поднять
  или `0`, иначе апдейты ловят 429 (`04 §8 warn4`).

```yaml
# <org>/infra: compose/bot.yml — webhook-вариант (отличия от polling)
    environment:
      BOT_MODE: webhook
      WEBHOOK_BASE_URL: https://bot.${DOMAIN}
      HTTP_RATE_LIMIT_RPS: "0"       # Telegram шлёт с пула IP — per-IP-лимит отключаем
    networks: [proxy, backend-net]   # proxy: traefik достаёт входящий
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/health"]
    labels:
      traefik.enable: "true"
      traefik.docker.network: proxy
      traefik.http.routers.bot.rule: Host(`bot.${DOMAIN}`)
      traefik.http.routers.bot.entrypoints: websecure
      traefik.http.routers.bot.tls.certresolver: letsencrypt
      traefik.http.services.bot.loadbalancer.server.port: "8080"
```

### 6.3 Single-flight для `set_webhook` (≥2 инстанса)

`set_webhook` — **глобальный side-effect на бот-токене**: при N инстансах нельзя, чтобы
каждый на старте звал `set_webhook` (гонка, перетирание URL, лишние Telegram API-вызовы).
Решения (по возрастанию строгости):
1. **Идемпотентность по сравнению:** на старте `get_webhook_info` → `set_webhook` только
   если `url`/`secret`/`allowed_updates` отличаются. Дёшево, обычно достаточно.
2. **Redis-lock single-flight:** `SET webhook:lock <instance> NX EX 30` — только владелец
   лока зовёт `set_webhook` (Redis уже есть для FSM). Детерминированнее при rollout'е.
3. **Init-job / leader:** вынести `set_webhook` в отдельный one-shot перед раскаткой
   реплик (аналог migrate-job у backend). Самый чистый, но больше движущихся частей —
   заводить только если 1/2 не хватает.

Рекоменд. для шаблона: **(1) идемпотентность + (2) Redis-lock** — без отдельного job'а
(не gold-plate). На rotation `WEBHOOK_SECRET` (§2.5) тот же путь перепрописывает secret.

### 6.4 Выбор топологии

| | Polling | Webhook |
|---|---|---|
| Ingress/TLS | не нужен | **нужен** (traefik + LE) |
| Инстансов | строго **1** (409 при 2) | **≥1**, масштабируется при Redis-isolation |
| Сеть compose | `backend-net` | `proxy` + `backend-net` |
| httpkit | не нужен (опц. для /health) | нужен (или aiohttp-сервер) |
| `set_webhook` | — | single-flight (§6.3) |
| Когда | dev, low-traffic, без публ. TLS | прод-дефолт, высокий трафик, HA |

---

## 7. Release / handoff

Зеркалит go-release (`03 §6.3-6.4`, `ecosystem.md § Image registry`), но **один образ**
(нет migrate-lockstep, т.к. нет БД).

### 7.1 `make release VERSION=vX.Y.Z` (в репо бота)

Одним проходом (порт `go-backend/scripts/release.sh`):
1. **confirm-промпт** (неинтерактивно → отмена; `RELEASE_YES=1` для CI).
2. **annotated tag** `vX.Y.Z` (semver обязателен; `:latest`/`:edge`/lightweight отвергаются —
   `ecosystem.md § Image registry`, анти-паттерн повторён в pylibinfra).
3. **preflight:** ветка=main / clean / annotated semver / buildx + `make doctor`.
4. **buildx --push** (ОДИН образ; image-path из `git remote get-url origin` → форк без правок):
   ```bash
   IMAGE_BASE=$(git remote get-url origin | sed -E 's#…#\2/\3#')/bot
   docker buildx build --platform linux/amd64 --push \
     --build-arg VERSION="$VERSION" --build-arg GIT_SHA="$SHA" \
     -t "$IMAGE_BASE:$VERSION" .
   ```
5. **агрегированный INFRA-HANDOFF** → **STOP**.

Репо бота `vault kv patch`/`make ship`/`ssh` **сам не выполняет** — печатает handoff-блок
(порт awk-агрегации `**Infra impact.**` из roadmap, `03 §6.4`).

### 7.2 Handoff-блок (out-of-band инфра-админу)

```
=== INFRA HANDOFF · передай инфра-админу out-of-band ===
bot_tag → vX.Y.Z   (single image, git.${DOMAIN}/<org>/bot:vX.Y.Z)

корп:    vault kv patch kv/projects/<p>/<env>/meta bot_tag=vX.Y.Z
проект:  (<org>/infra) make ship   # vault-agent рендерит BOT_TAG в compose.env → force-recreate bot
```

### 7.3 Цепочка деплоя (как `backend_tag`, `ecosystem.md § happy-path`, `03 §6.4`)

1. **корп-админ:** `vault kv patch kv/projects/<p>/<env>/meta bot_tag=vX.Y.Z`.
2. **проект (`<org>/infra`):** `make ship` (`scripts/ship.sh`) → ssh-deploy →
   vault-agent перерендерит `meta.env` (always-on) → `BOT_TAG` в `.runtime/env/compose.env` →
   `deploy.sh` детектит изменение → **force-recreate `bot`**.
3. **verify:** `/query-logs` (корп-Loki, tenant `<p>-<env>`) / Grafana `Apps/*`
   (`biz_tg_*`, `OTEL_SERVICE_NAME=bot`) / Tempo trace search.

### 7.4 Первичный онбординг бота в существующий проект

1. `<org>/bot` (форк telegram-bot-template): `make release VERSION=v0.1.0` → push образа.
2. `<org>/infra`: `/request-secret` → блок `vault kv put kv/projects/<p>/<env>/bot
   token=… webhook_secret=…` → корп-админ выполняет.
3. корп-админ: `vault kv patch kv/projects/<p>/<env>/meta bot_tag=v0.1.0`.
4. `<org>/infra`: добавить `configs/vault-agent/templates/bot.env.tpl` +
   `agent.hcl.parts/bot.hcl`, `compose/bot.yml`, `COMPOSE_PROFILES=…,bot`.
5. `make ship` → vault-agent рендерит `bot.env`, бот force-recreate.

---

## Резюме решений (для сводки)

- **Поверхность конфига:** ~4 группы env — телеметрия/логи (наследуется от
  pylibinfra-китов, env-tuning поверх defaults), Telegram-ядро (`BOT_TOKEN`/`BOT_MODE`/
  `BOT_ADMIN_IDS`/locale; `allowed_updates` — из кода, не env), webhook (`WEBHOOK_*`),
  FSM/шина (`REDIS_URL`/`NATS_URL`), бэкенд-клиенты (`BACKEND_*_BASE_URL`+timeout+breaker).
- **В Vault** (объект `kv/projects/<p>/<env>/bot`, AppRole `projects-<p>-<env>` без правок):
  `BOT_TOKEN`, `WEBHOOK_SECRET`, опц. `BACKEND_*_TOKEN`/`REDIS_URL`; на VPS их рендерит
  **vault-agent** в `.runtime/secrets/bot.env` (бот читает как ENV — `config`-кит на VPS
  опционален); `OTEL_TOKEN` наследуется из always-on `otel.env`.
- **Деплой:** (1) polling = 1 инстанс, без ingress, `backend-net`; webhook = за traefik/TLS,
  ≥2 инстанса возможны при `RedisEventIsolation`. (2) `set_webhook` — single-flight
  (идемпотентность по `get_webhook_info` + Redis-lock), без отдельного job'а. (3) один
  образ (нет migrate — бот stateless/Redis-FSM). (4) release STOP на image-in-registry,
  handoff = `vault kv patch …meta bot_tag` + `make ship` (как `backend_tag`).
