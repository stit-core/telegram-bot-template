#!/usr/bin/env bash
# scripts/release.sh — релиз одной командой: semver-валидация → confirm →
# annotated tag → preflight (main/clean/annotated-semver/buildx/docker-auth) →
# buildx push ОДНОГО образа → агрегированный INFRA-HANDOFF → STOP.
#
#   make release VERSION=vX.Y.Z
#
# Бот stateless (FSM в Redis), migrate-образа нет — один образ <host>/<org>/bot.
# Приватный pylibinfra тянется build-secret'ом git_token (см. Dockerfile):
# положи токен в файл и передай GIT_TOKEN_FILE=<path>; без секрета сборка
# работает только с публичным pylibinfra.
#
# Зона ответственности этого репо: код → image в registry. На STOP — всё.
# Деплой (make bump SVC=bot TAG=… — BOT_TAG в .env VPS) — в <org>/infra, НЕ здесь.
#
# Неинтерактивный запуск (нет TTY / EOF на prompt) → отмена (exit 1):
# accidental release невозможен. Для CI-автоматизации: RELEASE_YES=1.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail() { echo "release: $*" >&2; exit 2; }

VERSION="${1:-}"
[ -n "$VERSION" ] || fail "нужен VERSION. Usage: make release VERSION=vX.Y.Z"
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || fail "VERSION=$VERSION не semver vX.Y.Z (lightweight/:latest/:edge запрещены)"

BR=$(git rev-parse --abbrev-ref HEAD)
SHA=$(git rev-parse --short HEAD)
# image-path выводим из origin (host/org), чтобы шаблон работал без правки при форке.
ORIGIN=$(git remote get-url origin 2>/dev/null) || fail "нет git remote origin"
HOST=$(echo "$ORIGIN" | sed -E 's#^(git@|ssh://git@|https?://)([^:/@]+)[:/].*#\2#')
ORG=$(echo "$ORIGIN" | sed -E 's#^(git@|ssh://git@|https?://)[^:/@]+[:/]([^/]+)/.*#\2#')
IMAGE="${REGISTRY:-$HOST}/$ORG/bot:$VERSION"

echo "версия:  $VERSION"
echo "образ:   $IMAGE"
echo "коммит:  $SHA ($BR)"
echo

# --- confirm (видимое вне репо действие — explicit OK обязателен) ---
if [ "${RELEASE_YES:-}" = "1" ]; then
    echo "release: RELEASE_YES=1 — пропускаю prompt"
else
    printf "⚠ confirm release %s from %s@%s? [y/N] " "$VERSION" "$BR" "$SHA"
    read -r ans 2>/dev/null || ans=""
    case "$ans" in
        y | Y) ;;
        *) echo "release: отменено (нет подтверждения)"; exit 1 ;;
    esac
fi

# --- annotated tag, если на HEAD ещё нет ---
existing=$(git describe --tags --exact-match HEAD 2>/dev/null || true)
if [ -z "$existing" ]; then
    git tag -a "$VERSION" -m "release $VERSION"
    echo "release: создан annotated tag $VERSION (push: git push origin $VERSION)"
elif [ "$existing" != "$VERSION" ]; then
    fail "на HEAD уже тег $existing ≠ запрошенному $VERSION"
fi

# --- preflight: main / clean / annotated semver на HEAD / buildx / docker-auth ---
[ "$BR" = "main" ] || fail "branch=$BR, релиз только с main"
[ -z "$(git status --porcelain)" ] || fail "working tree dirty — закоммить или stash"
kind=$(git cat-file -t "$VERSION" 2>/dev/null || echo "?")
[ "$kind" = "tag" ] || fail "tag=$VERSION не annotated (kind=$kind) — пересоздай через git tag -a"
docker buildx version >/dev/null 2>&1 || fail "docker buildx не доступен"
if ! grep -q "$HOST" "${DOCKER_CONFIG:-$HOME/.docker}/config.json" 2>/dev/null; then
    fail "нет docker-auth для $HOST — оператор делает docker login $HOST (вне процесса)"
fi
echo "release: preflight OK"

# --- build + push ОДНОГО образа (multi-stage uv; pylibinfra — build-secret git_token) ---
SECRET_ARGS=()
if [ -n "${GIT_TOKEN_FILE:-}" ]; then
    [ -f "$GIT_TOKEN_FILE" ] || fail "GIT_TOKEN_FILE=$GIT_TOKEN_FILE не найден"
    SECRET_ARGS=(--secret "id=git_token,src=$GIT_TOKEN_FILE")
fi
docker buildx build --platform linux/amd64 --push \
    "${SECRET_ARGS[@]}" \
    --build-arg SERVICE_VERSION="$VERSION" \
    --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
    -t "$IMAGE" .

echo "✓ released $IMAGE"

# --- агрегированный INFRA-HANDOFF ---
echo
echo "=== INFRA HANDOFF · передай инфра-админу out-of-band ==="
echo "BOT_TAG → $VERSION   (один образ; migrate-образа нет, бот stateless)"

# Single-file модель: единый roadmap.md. На каждую `### <slug>`-секцию под `## Active`
# захватываем подсекцию `**Infra impact.**` (bold-лейбл) до следующего bold-лейбла /
# `#### `-фазы / `### `/`## `-границы. Пустой маркер `—`/`|` пропускаем.
roadmap=.claude/plans/roadmap.md
impacts=""
if [ -f "$roadmap" ]; then
    impacts=$(awk '
      function emit(s, line,   t) {
        t = line; gsub(/^[[:space:]]+|[[:space:]]+$/, "", t)
        if (t == "" || t == "—" || t == "|") return
        if (!hdr[s]) { print "--- " s " ---"; hdr[s] = 1 }
        print line
      }
      /^## Active/ { inact = 1; next }
      /^## /       { inact = 0; slug = ""; cap = 0; next }
      !inact       { next }
      /^### /      { slug = $0; sub(/^### /, "", slug); sub(/ .*/, "", slug); cap = 0; next }
      slug == ""   { next }
      /^\*\*Infra impact\.\*\*/ {
        cap = 1
        rest = $0; sub(/^\*\*Infra impact\.\*\*[[:space:]]*/, "", rest)
        emit(slug, rest)
        next
      }
      cap && /^\*\*[^*]+\.\*\*/  { cap = 0; next }
      cap && /^(#### |### |## )/ { cap = 0 }
      cap                        { emit(slug, $0) }
    ' "$roadmap")
fi
if [ -n "$impacts" ]; then
    echo
    echo "Накопленные infra-изменения (roadmap.md → **Infra impact.** в активных планах):"
    echo "$impacts"
else
    echo
    echo "(нет записанных **Infra impact.** — убедись, что всё инфра-затрагивающее"
    echo " зафиксировано: .claude/rules/infra-impact.md / skill infra-handoff)"
fi

cat <<EOF

Действия инфра-стороны:
  проект:  в <org>/infra — make bump SVC=bot TAG=$VERSION
           (правит BOT_TAG в .env на VPS + force-recreate)

=== STOP. Зона этого репо закрыта (image в registry). Деплой — не здесь. ===
EOF
