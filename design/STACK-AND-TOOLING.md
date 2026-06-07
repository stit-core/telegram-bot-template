---
title: "telegram-bot-template — стек, тулинг, CI, контейнеризация"
description: "Зафиксированный стек версий, dev-loop (uv/ruff/mypy/pytest/import-linter), Makefile-гейты, Gitea Actions CI, multi-stage uv Dockerfile, git-hooks — Python-аналог тулинга go-backend-template."
status: design
lang: ru
based_on: design/_research/03, design/_research/07, design/_research/12
---

# Стек, тулинг, CI, контейнеризация

Python-аналог тулинга `go-backend-template`, унаследованный из `pylibinfra` (готовая петля). Полная
детализация — `_research/03` (тулинг/CI/доки go-template → Python), `_research/07` (версии стека),
`_research/12` (Dockerfile/деплой).

---

## 1. Зависимости (`pyproject.toml`)

> **Директива «вся инфра в pylibinfra».** Шаблон зависит **только** от `pylibinfra[tgbotkit]` — ноль
> прямых инфра-пинов. `aiogram`/`aiogram-dialog`/`fluent.runtime` приезжают через extra `[tgbotkit]`
> (там же `tgbotkit`), остальная инфра (dishka/redis/httpx/otel/fastapi/structlog) — транзитив
> pylibinfra. См. [ARCHITECTURE.md §3, §16](ARCHITECTURE.md).

```toml
[project]
requires-python = ">=3.12"           # как pylibinfra
dependencies = [
    # единственная рантайм-зависимость: pylibinfra с extra [tgbotkit] (tgbotkit + aiogram + fluent)
    "pylibinfra[tgbotkit] @ git+https://git.sftbmb.ru/sftbmb-core/pylibinfra.git@vX.Y.Z",
]

[dependency-groups]
dev = [
    "ruff>=0.15", "mypy>=2.1", "import-linter>=2.5",
    "pytest>=9,<10", "pytest-asyncio>=1.4,<2", "pytest-cov>=7.1,<8",
    "respx>=0.22",                   # мок httpx для backend-тестов
    "pylibinfra[testkit]",           # testcontainers redis/nats
]
```

`uv lock && uv sync` подтянет; `.python-version` + `uv.lock` коммитятся.

---

## 2. Dev-loop и гейты (Makefile)

Тонкий `Makefile` с тем же словарём verbs, что у go-эталона; реализация делегируется `uv run …`.
Канонический gate перед claim «готово»/push — `make check`.

| `make <verb>` | Делает | Go-аналог |
|---|---|---|
| `make fmt` | `uv run ruff format .` | `gofumpt` |
| `make lint` | `uv run ruff check .` + `uv run lint-imports` (import-linter) | `golangci-lint` + `depguard` |
| `make typecheck` | `uv run mypy src` | `go vet` (растворён в ruff+mypy) |
| `make test` | `uv run pytest -m "not integration and not e2e"` | `go test -short` |
| `make test-integration` | `uv run pytest -m integration` (нужен Docker) | integration |
| `make check` | fmt-check + lint + typecheck + test | `make check` |
| `make status` | ветка/drift/активный план/инфра-touch (cockpit-вход) | `make status` |
| `make run` | `uv run python -m bot` (polling, локально) | `make run` |
| `make release` | build+push образа + агрегированный INFRA-HANDOFF | `make release` |

**Чего у бота НЕТ** (в отличие от go): `sqlc`/`mockery`/`make gen`/`gen-check` — в Python нет
кодогена (моки — фейки-Protocol'ы или `respx`).

---

## 3. Конфигурация инструментов (`pyproject.toml`)

- **ruff** (`target-version=py312`): format + check; select-набор включает `S` (bandit/security),
  `I` (isort), `ASYNC`, `TID252` (запрет relative imports); запрет `print`/прямого `logging`
  (аналог forbidigo — только `logkit.Logger`).
- **mypy** `strict = true` + pydantic-плагин: полная типизация, Protocol-порты проверяются
  структурно (адаптер обязан удовлетворять порту), запрет `Any` на границах.
- **pytest**: маркеры `unit`/`dialog`/`integration`/`e2e`; `asyncio_mode = "auto"`.
- **import-linter** (`importlinter.toml`): 3 контракта (слоистость внутри фичи; независимость фич;
  чистое ядро не импортит `httpx`/`aiogram`/`redis`/`gateway`) — аналог depguard (`_research/14` §5).

---

## 4. CI — Gitea Actions (`.gitea/workflows/ci.yml`)

Копируем структуру из `pylibinfra/.gitea/workflows/ci.yml`:

- job `lint`: `setup-uv` (+ enable-cache) → `uv sync --frozen` → `ruff format --check` +
  `ruff check` + `lint-imports` + `mypy src`.
- job `test`: `uv sync --frozen` → `pytest -m "not integration and not e2e"`; отдельный job/шаг
  `integration` поднимает Docker (testcontainers redis/nats).
- job `build` (на тег/main): `docker buildx` образа бота (а не `uv build` — бот сервис, не lib).
- Для приватного `pylibinfra @ git+…` — Gitea-token/ssh-ключ в secrets раннера.
- Релиз — **локальный** `make release` (как go-эталон): меньше секретов в раннере.

---

## 5. Контейнеризация (`Dockerfile`)

Multi-stage uv (`_research/12`):

```dockerfile
# builder
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# приватный pylibinfra по git+ssh
RUN --mount=type=ssh \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# runtime
FROM python:3.12-slim
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
ENTRYPOINT ["python", "-m", "bot"]
```

`ARG`-ы для версии/commit (resource-attrs telemetry). **Один образ** — migrate-образа нет (бот
stateless, FSM в Redis). `.dockerignore` исключает `.venv/.git/tests/docs/.claude`.

---

## 6. Git workflow

- **Conventional Commits** (`scripts/git-hooks/commit-msg`): типы `feat|fix|refactor|docs|test|
  chore|meta` (с `meta` — у бота тоже `.claude`-мета-слой), формат `<type>(<scope>)?: <subject>`,
  subject ≤72.
- **Линейная история**, push в `main` через pre-push → `make check`.
- git-хуки ставятся `make setup` (commit-msg/pre-commit/pre-push).

---

## 7. Документная таксономия (`docs/`)

Зеркало go-template:

- `docs/README.md` — карта.
- `docs/getting-started.md` — путь потребителя форка (форк → `/init-service` → стек → `/de-template`
  → scaffold).
- `docs/contributing.md` — устройство `.claude`-системы.
- `docs/reference/{architecture,observability,release,ecosystem}.md` + новый `dialog-mapping.md`
  (аналог `domain-mapping.md`: маппинг флоу диалога → файлы фичи).
- `docs/stack/` — 8+ stack-артефактов (см. [CLAUDE-SYSTEM.md](CLAUDE-SYSTEM.md) §2) + bash-валидатор.

Доки по самой `aiogram_dialog` — уже готовы в `aiogram-dialog-docs/` (этот же репо).
