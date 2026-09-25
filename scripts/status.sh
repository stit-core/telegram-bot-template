#!/usr/bin/env bash
# scripts/status.sh — always-on cockpit feed для /smartdev.
#
# Использование:
#   scripts/status.sh          # быстрая сводка + критичный детект (~2s)
#   scripts/status.sh --full   # + ruff issue count (потяжелее)
#
# Критичный детект (syntax/draft-артефакты/infra-touch) гонится ВСЕГДА — не за
# --full. Тяжёлый гейт (mypy/pytest/import-linter) status не гоняет — это
# `make check` (status read-only и быстрый). Каждая секция `== Name ==` — для
# парсинга агентом. Финальная строка: `OK` / `ATTENTION: <что>` — сигнал cockpit'у.

set -uo pipefail

FULL=0
for arg in "$@"; do
    case "$arg" in
        --full) FULL=1 ;;
        -h | --help)
            sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ATTN=""

# === Branch ===
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "DETACHED")
LAST_COMMIT=$(git log -1 --format='%h %s (%ar)' 2>/dev/null || echo "—")
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || echo "")
AHEAD_BEHIND=""
if [ -n "$UPSTREAM" ]; then
    AB=$(git rev-list --left-right --count "HEAD...$UPSTREAM" 2>/dev/null | awk '{print $1" ahead, "$2" behind"}')
    AHEAD_BEHIND=" ($AB $UPSTREAM)"
fi
echo "== Branch =="
echo "$BRANCH$AHEAD_BEHIND"
echo "last: $LAST_COMMIT"
echo

# === Working tree ===
MODIFIED=$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')
echo "== Working tree =="
echo "modified: $MODIFIED, staged: $STAGED, untracked: $UNTRACKED"
if [ "$MODIFIED" -gt 0 ] || [ "$STAGED" -gt 0 ]; then
    git diff --name-only HEAD 2>/dev/null | head -20 | sed 's|^|  |'
fi
echo

# === Critical === (всегда, быстро)
echo "== Critical =="

# syntax — дерево хотя бы компилируется (дешёвый сигнал; полный гейт — make check)
if command -v uv >/dev/null 2>&1 && [ -d .venv ]; then
    if uv run python -m compileall -q src tests >/dev/null 2>&1; then
        echo "SYNTAX: OK"
    else
        echo "SYNTAX: BROKEN — make check для диагноза"
        ATTN="$ATTN syntax"
    fi
else
    echo "SYNTAX: (uv/.venv недоступны — make setup)"
fi
echo "GATE: ruff/import-linter/mypy/pytest гоняет make check (status read-only)"

# stack draft-артефакты (companion README/_templates исключены).
# Дизайн диалогов — слой telegram-bot-flow соседнего strategy-репо; его статус смотрят там.
if [ -d docs/stack ]; then
    sdrafts=$(grep -rl '^status: draft' docs/stack --include='*.md' 2>/dev/null \
        | grep -vE '/_templates/|/README\.md$' \
        | sed 's#docs/stack/##' | tr '\n' ' ')
    if [ -z "$sdrafts" ]; then
        echo "STACK-DRAFTS: none"
    else
        echo "STACK-DRAFTS:$sdrafts (/stack-deep-dive)"
    fi
fi
echo

# === Infra-touch === (незакоммиченный diff по инфра-поверхности → infra-handoff)
echo "== Infra-touch =="
INFRA_RE='(^|/)\.env|^src/bot/config\.py$|^Dockerfile$|^compose\.dev\.yml$|^pyproject\.toml$|notification[^/]*\.py$|^src/bot/features/notifications/'
INFRA_HITS=$(git status --porcelain 2>/dev/null | awk '{print $2}' | grep -E "$INFRA_RE" || true)
if [ -n "$INFRA_HITS" ]; then
    echo "незакоммиченные изменения задевают инфра-поверхность:"
    echo "$INFRA_HITS" | sed 's|^|  |'
    echo "→ оформи INFRA-HANDOFF (skill infra-handoff / .claude/rules/infra-impact.md)"
    ATTN="$ATTN infra-touch"
else
    echo "none"
fi
echo

# === Plan === (активные планы .claude/plans/: статус, прогресс, следующий шаг; бэклог)
echo "== Plan =="
bash scripts/validate-plan.sh --summary
echo

# === Recent commits ===
echo "== Recent commits =="
git log --oneline -5 2>/dev/null | sed 's|^|  |'
echo

# === TODOs in changed files ===
echo "== TODOs in changed files =="
CHANGED_PY=$(git diff --name-only HEAD 2>/dev/null | grep '\.py$' || true)
if [ -n "$CHANGED_PY" ]; then
    # shellcheck disable=SC2086
    grep -nE '(TODO|FIXME|XXX|HACK):' $CHANGED_PY 2>/dev/null | head -10 | sed 's|^|  |' || echo "  (none)"
else
    echo "  (no changed .py files)"
fi
echo

# === Lint === (потяжелее, opt-in)
if [ "$FULL" -eq 1 ]; then
    echo "== Lint =="
    if command -v uv >/dev/null 2>&1; then
        ISSUES=$(uv run ruff check --quiet --output-format=concise . 2>/dev/null | wc -l | tr -d ' ')
        echo "ruff issues: $ISSUES"
    else
        echo "(uv не установлен — make setup)"
    fi
    echo
fi

if [ -n "$ATTN" ]; then
    echo "ATTENTION:$ATTN"
else
    echo "OK"
fi
