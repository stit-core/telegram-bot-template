#!/usr/bin/env bash
# Прод-логи бота через корп-Loki (skill /query-logs). Адрес — SFTBMB_LOKI_ADDR, токен — из
# .env.local (LOKI_TOKEN). Передаёт аргументы в logcli. Пример:
#   make logs A='query --limit 100 {service_name="telegram-bot"} |= "error"'
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
# shellcheck disable=SC1091
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }

: "${SFTBMB_LOKI_ADDR:?SFTBMB_LOKI_ADDR не задан — положи его в .env.local (см. rule env-local)}"

if ! command -v logcli >/dev/null 2>&1; then
  echo "✗ logcli не установлен (grafana/loki logcli)" >&2
  exit 127
fi

exec logcli --addr="$SFTBMB_LOKI_ADDR" ${LOKI_TOKEN:+--bearer-token="$LOKI_TOKEN"} "$@"
