#!/usr/bin/env bash
# Гейт целостности stack-артефактов (вход /de-template): каждый docs/stack/*.md (кроме README)
# должен иметь frontmatter, хотя бы один H2 и секцию Generates (что артефакт порождает в код/конфиг).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
fail=0

shopt -s nullglob
for f in docs/stack/*.md; do
  [ "$(basename "$f")" = "README.md" ] && continue
  head -1 "$f" | grep -q '^---$' || { echo "✗ $f: нет YAML-frontmatter"; fail=1; }
  grep -q '^## ' "$f" || { echo "✗ $f: нет H2-секций"; fail=1; }
  grep -qi 'Generates' "$f" || { echo "✗ $f: нет секции Generates"; fail=1; }
done

if [ "$fail" -eq 0 ]; then
  echo "✓ stack-доки валидны"
else
  exit 1
fi
