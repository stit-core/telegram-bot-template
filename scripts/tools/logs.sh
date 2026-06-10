#!/usr/bin/env bash
# tools/logs.sh — обёртка над logcli для чтения корп-Loki под bearer-токеном (skill /query-logs).
#
# Использование:
#   scripts/tools/logs.sh query   --service NAME [--match REGEX] [--since 1h] [--limit 200]
#   scripts/tools/logs.sh query   --raw '{service_name="telegram-bot"} |~ "panic"'  [--since 1h] [--limit 200]
#   scripts/tools/logs.sh errors  --service NAME [--since 15m] [--top 10]
#   scripts/tools/logs.sh watch   --service NAME [--match REGEX] --for 5m
#
# Токен берётся в этом порядке:
#   1) env STIT_OBS_TOKEN
#   2) строка `STIT_OBS_TOKEN=...` в ./.env.local
#
# Endpoint:
#   STIT_LOKI_ADDR — обязателен (FAIL при пустом, не уходим молча на managed).
#   managed: https://loki.stit.tech; self-hosted: свой Loki. Tenant зашит в токен — не передаётся отдельно.
#
# Канонический status-line в конце: `OK` / `FAIL: <reason>`.

set -uo pipefail

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

if [ $# -eq 0 ]; then usage 0; fi
case "$1" in -h|--help) usage 0 ;; esac
MODE="$1"; shift

# === Defaults ===
SERVICE=""
RAW_QUERY=""
MATCH=""
SINCE=""
LIMIT="200"
TOP="10"
FOR=""
MAX_BYTES="${MAX_BYTES:-25000}"

# === Args ===
while [ $# -gt 0 ]; do
    case "$1" in
        --service)  SERVICE="$2"; shift 2 ;;
        --match)    MATCH="$2"; shift 2 ;;
        --raw)      RAW_QUERY="$2"; shift 2 ;;
        --since)    SINCE="$2"; shift 2 ;;
        --limit)    LIMIT="$2"; shift 2 ;;
        --top)      TOP="$2"; shift 2 ;;
        --for)      FOR="$2"; shift 2 ;;
        -h|--help)  usage 0 ;;
        *) echo "FAIL: unknown arg: $1" >&2; exit 1 ;;
    esac
done

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# === Token resolution (НЕ логируем токен, НЕ возвращаем его наружу) ===
TOKEN=""
if [ -n "${STIT_OBS_TOKEN:-}" ]; then
    TOKEN="$STIT_OBS_TOKEN"
elif [ -f .env.local ]; then
    line=$(grep -E '^[[:space:]]*(export[[:space:]]+)?STIT_OBS_TOKEN=' .env.local 2>/dev/null | tail -1)
    TOKEN="${line#*=}"
    TOKEN="${TOKEN%\"}"; TOKEN="${TOKEN#\"}"
    TOKEN="${TOKEN%\'}"; TOKEN="${TOKEN#\'}"
fi
if [ -z "$TOKEN" ]; then
    echo "FAIL: no STIT_OBS_TOKEN. Set env or add line 'STIT_OBS_TOKEN=<token>' to ./.env.local" >&2
    exit 1
fi

# === Endpoint ===
# FAIL-fast при пустом: без явного адреса не уходим молча на managed-хост stit
# (self-hosted форк иначе утёк бы свои запросы на чужой control-plane). Managed —
# выставь STIT_LOKI_ADDR=https://loki.stit.tech; self-hosted — адрес своего Loki.
if [ -z "${STIT_LOKI_ADDR:-}" ]; then
    addr_line=$(grep -E '^[[:space:]]*(export[[:space:]]+)?STIT_LOKI_ADDR=' .env.local 2>/dev/null | tail -1)
    STIT_LOKI_ADDR="${addr_line#*=}"
    STIT_LOKI_ADDR="${STIT_LOKI_ADDR%\"}"; STIT_LOKI_ADDR="${STIT_LOKI_ADDR#\"}"
fi
if [ -z "${STIT_LOKI_ADDR:-}" ]; then
    echo "FAIL: no STIT_LOKI_ADDR. Set env or add 'STIT_LOKI_ADDR=<loki-url>' to ./.env.local (managed: https://loki.stit.tech; self-hosted: свой Loki из corp-infra-template)" >&2
    exit 1
fi
LOKI_ADDR="$STIT_LOKI_ADDR"
export LOKI_ADDR LOKI_BEARER_TOKEN="$TOKEN"

# === Tool check ===
if ! command -v logcli >/dev/null 2>&1; then
    echo "FAIL: logcli not installed (grafana/loki logcli)" >&2
    exit 1
fi

# === Helper: build LogQL ===
build_query() {
    if [ -n "$RAW_QUERY" ]; then
        printf '%s\n' "$RAW_QUERY"
        return
    fi
    if [ -z "$SERVICE" ]; then
        echo "FAIL: provide --service NAME or --raw '<LogQL>'" >&2
        exit 1
    fi
    local q="{service_name=\"$SERVICE\"}"
    if [ -n "$MATCH" ]; then
        q="$q |~ \"$MATCH\""
    fi
    printf '%s\n' "$q"
}

# === Modes ===

run_query() {
    local q since
    q=$(build_query) || exit 1
    since="${SINCE:-1h}"

    echo "== Query =="
    echo "  query: $q"
    echo "  since: $since   limit: $LIMIT"
    echo

    local tmp
    tmp=$(mktemp); trap 'rm -f -- "${tmp:-}"' EXIT
    if ! logcli query --quiet --no-labels --since="$since" --limit="$LIMIT" "$q" >"$tmp" 2>&1; then
        head -c "$MAX_BYTES" "$tmp"
        echo
        echo "FAIL: logcli query failed (see stderr above)"
        exit 1
    fi

    local lines
    lines=$(wc -l <"$tmp" | tr -d ' ')
    if [ "$(wc -c <"$tmp")" -gt "$MAX_BYTES" ]; then
        head -c "$MAX_BYTES" "$tmp"
        echo
        echo "... (truncated at ${MAX_BYTES}B; full result has $lines lines)"
    else
        cat "$tmp"
    fi
    echo
    echo "Total lines: $lines"
    echo "OK"
}

run_errors() {
    if [ -z "$SERVICE" ] && [ -z "$RAW_QUERY" ]; then
        echo "FAIL: provide --service NAME" >&2
        exit 1
    fi
    local since q
    since="${SINCE:-15m}"
    if [ -n "$RAW_QUERY" ]; then
        q="$RAW_QUERY"
    else
        # Стандартный набор error-паттернов: JSON-логи logkit + python traceback + общие.
        q="{service_name=\"$SERVICE\"} |~ \"(?i)level=error|panic:|fatal|Traceback|\\\"level\\\":[[:space:]]*\\\"error\\\"\""
    fi

    echo "== Errors =="
    echo "  service: ${SERVICE:-(raw)}   since: $since   top: $TOP"
    echo

    local tmp
    tmp=$(mktemp); trap 'rm -f -- "${tmp:-}"' EXIT
    if ! logcli query --quiet --no-labels --since="$since" --limit="5000" "$q" >"$tmp" 2>&1; then
        head -c "$MAX_BYTES" "$tmp"
        echo
        echo "FAIL: logcli query failed"
        exit 1
    fi

    local total
    total=$(wc -l <"$tmp" | tr -d ' ')

    # Группировка по сигнатуре: убираем числа, uuid-подобные, hex ≥6, timestamp-подобные.
    awk '
        {
            sig = $0
            # timestamp ISO
            gsub(/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z?/, "<ts>", sig)
            # uuid
            gsub(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/, "<uuid>", sig)
            # long hex
            gsub(/[0-9a-f]{12,}/, "<hex>", sig)
            # numbers (after the above)
            gsub(/[0-9]+/, "<n>", sig)
            # обрезаем сигнатуру до 160 символов
            if (length(sig) > 160) sig = substr(sig, 1, 160) "..."
            counts[sig]++
        }
        END {
            for (s in counts) printf "%d\t%s\n", counts[s], s
        }
    ' "$tmp" | sort -rn -k1,1 | head -n "$TOP" | awk -F'\t' '{ printf "  %4d×  %s\n", $1, $2 }'

    echo
    echo "Total error lines: $total"
    echo "OK"
}

run_watch() {
    if [ -z "$SERVICE" ] && [ -z "$RAW_QUERY" ]; then
        echo "FAIL: provide --service NAME or --raw" >&2
        exit 1
    fi
    if [ -z "$FOR" ]; then
        echo "FAIL: --for DURATION required (e.g. --for 5m)" >&2
        exit 1
    fi
    local q
    q=$(build_query) || exit 1

    echo "== Watch =="
    echo "  query: $q"
    echo "  duration: $FOR"
    echo

    # logcli query --tail стримит новые строки. timeout прерывает на $FOR.
    # 124 = timeout normal exit, 143 = SIGTERM.
    local tmp ec
    tmp=$(mktemp); trap 'rm -f -- "${tmp:-}"' EXIT
    timeout "$FOR" logcli query --quiet --tail --no-labels "$q" 2>&1 | tee "$tmp"
    ec="${PIPESTATUS[0]}"

    local total errors
    total=$(wc -l <"$tmp" | tr -d ' ')
    errors=$(grep -cE "(?i)level=error|panic:|fatal|Traceback" "$tmp" 2>/dev/null || true)

    echo
    echo "== Summary =="
    echo "  total lines: $total"
    echo "  error-ish:   $errors"
    case "$ec" in
        124|143|0) echo "OK" ;;
        *) echo "FAIL: logcli exited $ec"; exit 1 ;;
    esac
}

case "$MODE" in
    query)  run_query ;;
    errors) run_errors ;;
    watch)  run_watch ;;
    *) echo "FAIL: unknown mode '$MODE' — use query | errors | watch" >&2; exit 1 ;;
esac
