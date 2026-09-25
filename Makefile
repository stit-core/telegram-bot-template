.PHONY: help setup doctor fmt fmt-check lint typecheck test test-integration test-cover cover-check lock-check check run status validate-stack-docs plan-check release lock sync

# Пол покрытия (branch) для канонического гейта; scope — весь src/bot: дилоги/провайдеры
# исполняются flow/composition-тестами, отдельного исключения обвязки не требуется.
COVER_FLOOR ?= 85

# Тонкий словарь verbs (зеркало go-backend-template), реализация делегируется uv.
# Канонический гейт перед claim «готово»/push — `make check`.

help: ## список команд
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ SETUP
setup: ## uv sync (dev) + git-хуки (commit-msg/pre-commit/pre-push)
	uv sync
	@cp scripts/git-hooks/commit-msg .git/hooks/commit-msg
	@cp scripts/git-hooks/pre-commit .git/hooks/pre-commit
	@cp scripts/git-hooks/pre-push  .git/hooks/pre-push
	@chmod +x .git/hooks/commit-msg .git/hooks/pre-commit .git/hooks/pre-push
	@echo "✓ setup: deps + git hooks"

doctor: ## preflight окружения: uv, docker-логин к registry, git-хуки, план
	@bash scripts/doctor.sh

lock: ## пересобрать uv.lock
	uv lock

sync: ## установить зависимости из uv.lock
	uv sync --frozen

##@ LOOP
fmt: ## ruff format .
	uv run ruff format .

fmt-check: ## ruff format --check . (для check/CI)
	uv run ruff format --check .

lint: ## ruff check + import-linter
	uv run ruff check .
	uv run lint-imports --config importlinter.toml

typecheck: ## mypy src + tests (тесты типизируются строго)
	uv run mypy src tests

test: ## быстрые тесты (без integration/e2e)
	uv run pytest -m "not integration and not e2e" -q

test-integration: ## integration-тесты (нужен Docker; testcontainers redis/nats)
	uv run pytest -m integration -q

test-cover: ## тесты с покрытием (информационно, без пола)
	uv run pytest -m "not integration and not e2e" --cov=src/bot --cov-report=term-missing -q

cover-check: ## тесты + пол покрытия COVER_FLOOR (гейт)
	uv run pytest -m "not integration and not e2e" --cov=src/bot --cov-fail-under=$(COVER_FLOOR) -q

lock-check: ## uv.lock не дрейфует от pyproject (аналог gen-check)
	uv lock --check

check: ## КАНОНИЧЕСКИЙ gate: fmt-check + lint + typecheck + lock-check + cover-check
	@echo "→ ruff format --check"; $(MAKE) -s fmt-check
	@echo "→ lint (ruff + import-linter)"; $(MAKE) -s lint
	@echo "→ mypy (src + tests)"; $(MAKE) -s typecheck
	@echo "→ uv lock --check"; $(MAKE) -s lock-check
	@echo "→ pytest + cover-floor $(COVER_FLOOR)%"; $(MAKE) -s cover-check
	@echo "✓ check clean"

##@ RUN
run: ## локальный polling-бот (нужен BOT_TOKEN; JSON-логи в stdout, LOG_FORMAT=text для глаз)
	uv run python -m bot

##@ INTEL
status: ## сводка состояния репо (ветка/drift/план/гейт) — A='--full'
	@bash scripts/status.sh $(A) 2>/dev/null || { echo "branch: $$(git branch --show-current)"; git status -s; }

validate-stack-docs: ## проверить целостность docs/stack/* (вход de-template)
	@bash scripts/validate-stack-docs.sh

plan-check: ## формат планов .claude/plans/ (A=--summary — сводка)
	@bash scripts/validate-plan.sh $(A)

##@ RELEASE
release: ## release VERSION=vX.Y.Z — собрать+запушить образ + INFRA-HANDOFF
	@bash scripts/release.sh "$(VERSION)"
