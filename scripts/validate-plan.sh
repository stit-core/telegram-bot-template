#!/usr/bin/env bash
# tools/validate-plan.sh — детерминированный валидатор единого плана-roadmap.
#
# Модель: единственный артефакт планирования — .claude/plans/roadmap.md.
# Активные планы — inline-секции `### <slug> — <title>` под `## Active`.
# Подпапок и отдельных <slug>.md нет. ## Backlog и преамбула не валидируются.
#
# Использование:
#   scripts/validate-plan.sh            # .claude/plans/roadmap.md
#   scripts/validate-plan.sh <file>     # явный путь
#
# Для каждой ### -секции под ## Active проверяет:
#   1. **Создан:** присутствует.
#   2. **Статус:** ∈ {planning, in-progress, blocked}; blocked → есть "blocked by".
#   3. Обязательные подсекции: Контекст, Не входит в скоуп, Атомы, Чекпоинты.
#   4. ≥1 атом (`- [ ]/[x] **A<N>:**`); у каждого — `Verify:` и `Зависит от:`.
#   5. Ссылки `Зависит от: A<M>` указывают на атом ЭТОЙ же секции
#      (—, Q-*, слаги — внешние/допустимые, не валидируются как атомы).
#
# НЕ сканирует код на инфра-изменения: детект инфра — rule+skill (infra-impact /
# infra-handoff). Здесь только структура плана.
#
# Выход: 0 — валидно; 1 — ошибки (список + канонический status-line).
# Зависимости: bash + awk (без внешних).

set -uo pipefail
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$ROOT"

TARGET="${1:-.claude/plans/roadmap.md}"
[ -f "$TARGET" ] || {
    echo "FAIL: target not found: $TARGET"
    exit 1
}

OUT=$(awk '
function finalize(   i,k,kk) {
    if (plan == "") return
    np++
    if (!created)             err[++ne] = plan ": нет **Создан:**"
    if (status == "")         err[++ne] = plan ": нет **Статус:**"
    else if (status !~ /^(planning|in-progress|blocked)$/)
                              err[++ne] = plan ": Статус=" status " не из {planning,in-progress,blocked}"
    else if (status == "blocked" && !blockedBy)
                              err[++ne] = plan ": статус blocked без пометки (blocked by: ...)"
    nreq = split("Контекст|Не входит в скоуп|Атомы|Чекпоинты", req, "|")
    for (i = 1; i <= nreq; i++)
        if (!(req[i] in sec)) err[++ne] = plan ": нет подсекции **" req[i] "**"
    if (natoms == 0)          err[++ne] = plan ": нет атомов (- [ ] **A<N>:**)"
    for (i = 1; i <= natoms; i++) {
        a = aorder[i]
        if (!(a in vf)) err[++ne] = plan ": атом " a " без Verify:"
        if (!(a in df)) err[++ne] = plan ": атом " a " без \"Зависит от:\""
    }
    for (k in deps) {
        split(k, kk, SUBSEP)
        # kk = (plan, cur, dep): валидируем что dep (kk[3]) — атом этой секции.
        if (kk[1] == plan && !(kk[3] in atomids))
            err[++ne] = plan ": атом " kk[2] " зависит от несуществующего " kk[3]
    }
    plan = ""; status = ""; created = 0; blockedBy = 0; natoms = 0; cur = ""
    delete sec; delete vf; delete df; delete atomids; delete aorder
}
/^## Active/            { inact = 1; next }
/^## /                 { finalize(); inact = 0; next }
                       { if (!inact) next }
/^### /                { finalize(); plan = $0; sub(/^### /, "", plan); sub(/ .*/, "", plan); next }
plan == ""             { next }
/\*\*Создан:\*\*/      { created = 1 }
/\*\*Статус:\*\*/ {
    s = $0; sub(/.*\*\*Статус:\*\*[[:space:]]*/, "", s); sub(/[[:space:]].*/, "", s)
    status = s
    if ($0 ~ /blocked by/) blockedBy = 1
}
/^\*\*[^*]+\.\*\*/ {
    lbl = $0; sub(/^\*\*/, "", lbl); sub(/\.\*\*.*/, "", lbl); sec[lbl] = 1
}
/^- \[[ x]\] \*\*A[0-9]+:/ {
    id = $0; sub(/^- \[[ x]\] \*\*/, "", id); sub(/:.*/, "", id)
    cur = id; atomids[id] = 1; aorder[++natoms] = id; next
}
/Verify:/              { if (cur != "") vf[cur] = 1 }
/Зависит от:/ {
    if (cur != "") {
        df[cur] = 1
        ln = $0; sub(/.*Зависит от:[[:space:]]*/, "", ln)
        n = split(ln, p, /[ ,·]+/)
        for (i = 1; i <= n; i++) if (p[i] ~ /^A[0-9]+$/) deps[plan, cur, p[i]] = 1
    }
}
END {
    finalize()
    for (i = 1; i <= ne; i++) print err[i]
    print "@@SUMMARY@@ " np " " ne
}
' "$TARGET")

NP=$(printf '%s\n' "$OUT" | awk '/^@@SUMMARY@@/{print $2}')
NE=$(printf '%s\n' "$OUT" | awk '/^@@SUMMARY@@/{print $3}')
printf '%s\n' "$OUT" | grep -vE '^@@SUMMARY@@|^$' || true

if [ "${NE:-0}" -gt 0 ]; then
    echo "FAIL: ${NE} error(s) across ${NP:-0} plan(s)"
    exit 1
fi
echo "OK (${NP:-0} plan(s) checked)"
