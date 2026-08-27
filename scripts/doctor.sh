#!/usr/bin/env bash
# scripts/doctor.sh — fail-fast preflight здоровья репо/окружения (зеркало
# go-backend-template doctor.sh, адаптированное под uv-тулчейн бота).
#
# Read-only: ничего не мутирует.
# FAIL-класс (exit 2): нет uv; нет docker-логина к registry (сломает make release).
# WARN-класс (exit 0): git-хуки не установлены, draft stack-доки.
# Канонический status-line в конце: `OK: ...` / `FAIL: N blocking`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

FAIL=0
WARN=0
ok()   { echo "OK   : $*"; }
warn() { echo "WARN : $*"; WARN=$((WARN + 1)); }
fail() { echo "FAIL : $*"; FAIL=$((FAIL + 1)); }

# 1. uv — единственный тулчейн-вход (make check/test/run делегируют ему).
if command -v uv >/dev/null 2>&1; then
    ok "uv: $(uv --version 2>/dev/null | head -1)"
else
    fail "uv: не найден — установи uv (все make-вербы делегируют ему)"
fi

# 2. docker-registry auth — make release падает на unauthorized в середине
#    пуша. Проверяем присутствие кред, не валидность токена.
HOST=$(git remote get-url origin 2>/dev/null | sed -E 's#^(git@|https?://)([^:/]+)[:/].*#\2#')
if [ -z "$HOST" ]; then
    warn "docker: не определить registry host из git remote"
elif ! command -v docker >/dev/null 2>&1; then
    warn "docker: бинарь не найден (нужен для make release)"
else
    CFG="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
    if [ -f "$CFG" ] && grep -q "\"$HOST\"" "$CFG" 2>/dev/null; then
        ok "docker auth: креды для $HOST присутствуют"
    elif [ -f "$CFG" ] && grep -qE '"(credsStore|credHelpers)"' "$CFG" 2>/dev/null; then
        ok "docker auth: настроен credential helper (проверь покрытие $HOST)"
    else
        fail "docker auth: нет логина к $HOST — перед make release: docker login $HOST"
    fi
fi

# 3. git-хуки — gate живёт на pre-push; без хуков он не срабатывает.
if [ -x .git/hooks/pre-push ] && [ -x .git/hooks/commit-msg ]; then
    ok "git hooks: установлены (commit-msg + pre-push)"
else
    warn "git hooks: не установлены — make setup"
fi

# 4. Структура плана — единый roadmap.md.
if bash scripts/validate-plan.sh >/dev/null 2>&1; then
    ok "roadmap: структура плана валидна"
else
    warn "roadmap: validate-plan.sh красный — make plan-check покажет детали"
fi

# 5. Draft stack-доки — напоминание, не блокер (gate de-template — stable).
drafts=$(grep -l '^status: draft' docs/stack/*.md 2>/dev/null | wc -l | tr -d ' ')
if [ "${drafts:-0}" -gt 0 ]; then
    warn "docs/stack: ${drafts} draft-артефакт(ов) — /stack-deep-dive до stable"
else
    ok "docs/stack: draft-артефактов нет"
fi

echo
if [ "$FAIL" -gt 0 ]; then
    echo "FAIL: ${FAIL} blocking (warn: ${WARN})"
    exit 2
fi
echo "OK: doctor clean (warn: ${WARN})"
