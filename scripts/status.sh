#!/usr/bin/env bash
# Cockpit-сводка для /smartdev: ветка, drift рабочего дерева, активный план, состояние гейта.
# Read-only. Подробный режим: scripts/status.sh --full.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

branch="$(git branch --show-current 2>/dev/null || echo '?')"
dirty="$(git status --porcelain | wc -l | tr -d ' ')"
echo "ветка:        $branch"
echo "изменений:    $dirty файл(ов)"

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
if [ -n "$upstream" ]; then
  ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"
  behind="$(git rev-list --count HEAD..@{u} 2>/dev/null || echo 0)"
  echo "vs $upstream: +$ahead / -$behind"
fi

roadmap=".claude/plans/roadmap.md"
if [ -f "$roadmap" ]; then
  focus="$(grep -m1 'Current focus' "$roadmap" | sed 's/.*Current focus:\**[[:space:]]*//' || true)"
  echo "активный план: ${focus:-—}"
fi

if [ "${1:-}" = "--full" ]; then
  echo "--- git status -s ---"
  git status -s
  echo "--- последние коммиты ---"
  git log --oneline -5
  echo "--- гейт (make check) ---"
  if make -q check >/dev/null 2>&1; then echo "(запусти 'make check' для проверки)"; fi
fi
