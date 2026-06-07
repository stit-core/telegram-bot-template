#!/usr/bin/env bash
# release VERSION=vX.Y.Z — собрать и запушить ОДИН образ бота + агрегированный INFRA-HANDOFF.
# Бот stateless (FSM в Redis), migrate-образа нет. STOP на image-in-registry: дальше деплой —
# в <org>/infra (handoff = vault kv patch bot_tag + make ship). Пуш — после явного confirm.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
version="${1:-}"

if ! [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "✗ usage: make release VERSION=vX.Y.Z" >&2
  exit 1
fi

# image-path выводим из origin (host/org/repo), чтобы шаблон работал без правки при форке.
origin="$(git remote get-url origin 2>/dev/null || echo '')"
slug="$(echo "$origin" | sed -E 's#.*[/:]([^/]+/[^/]+?)(\.git)?$#\1#')"
host="$(echo "$origin" | sed -E 's#^https?://([^/@]*@)?([^/]+)/.*#\2#')"
image="${REGISTRY:-$host}/${slug}:${version}"

echo "версия:  $version"
echo "образ:   $image"
echo "коммит:  $(git rev-parse --short HEAD)"
echo

echo "→ гейт перед релизом (make check)"
make check

echo
echo "→ сборка образа"
echo "docker buildx build --secret id=git_token,src=<token> \\"
echo "  --build-arg SERVICE_VERSION=$version --build-arg GIT_COMMIT=$(git rev-parse HEAD) \\"
echo "  -t $image --push ."
echo
echo "STOP. Сборку/пуш выполни вручную (нужен git_token для приватного pylibinfra и доступ в registry)."
echo
echo "── INFRA-HANDOFF ──────────────────────────────────────────"
echo "После пуша образа $image задеплоить в <org>/infra:"
echo "  vault kv patch <path>/bot bot_tag=$version"
echo "  (в infra-репо) make ship"
echo "Проверить env-поверхность (BOT_*/REDIS_URL/NATS_*/OTEL_*) — см. docs/reference/release.md."
