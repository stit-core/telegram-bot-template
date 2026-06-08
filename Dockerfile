# syntax=docker/dockerfile:1.7
# Multi-stage uv (STACK-AND-TOOLING §5). Один образ — бот stateless, FSM в Redis,
# migrate-образа нет. Приватный pylibinfra (git+https) тянется на этапе sync с
# build-secret токеном (через git insteadOf) — секрет не остаётся в слоях.

# ── builder ───────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# git — uv нужен для git-источника pylibinfra; ca-certificates — для https-клона.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Слой зависимостей (без кода проекта) — кэшируется, пока не меняются lock/pyproject.
# git_token (build-secret) аутентифицирует приватную gitea; без секрета (публичный
# pylibinfra) шаг работает как есть. Альтернатива — --mount=type=ssh + git+ssh-source.
RUN --mount=type=secret,id=git_token \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    sh -c 'if [ -f /run/secrets/git_token ]; then \
              git config --global url."https://oauth2:$(cat /run/secrets/git_token)@git.stit.tech/".insteadOf "https://git.stit.tech/"; \
           fi' \
    && uv sync --frozen --no-dev --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# ── runtime ─────────────────────────────────────────────────────────────────
FROM python:3.13-slim
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
USER app

# resource-attrs telemetry (service.version) — прокидываются на build.
ARG SERVICE_VERSION=dev
ARG GIT_COMMIT=unknown
ENV OTEL_SERVICE_VERSION=${SERVICE_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "bot"]
