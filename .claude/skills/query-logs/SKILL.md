---
name: query-logs
description: Прочитать или последить логи задеплоенного бота через корп-Loki (адрес из `STIT_LOKI_ADDR`) под bearer-токеном из `./.env.local`. Активируй когда юзер просит "посмотри логи", "что в логах", "следи за деплоем", "почему упало в проде", "/query-logs".
---

# Skill: query-logs

Чтение логов бота через корп-Loki read API. Адрес берётся из `STIT_LOKI_ADDR` (managed: `https://loki.stit.tech`; self-hosted: свой Loki из форка `corp-infra-template`) — без переменной обёртка падает с понятным `FAIL`, не уходит молча на managed-хост. Tenant-изоляция — на стороне `tenant-auth` ForwardAuth. Этот repo даёт обёртку `scripts/tools/logs.sh` + правила, ничего к корпу не патчит.

**Инструмент один:** `scripts/tools/logs.sh` (три режима). Tempo (trace API) — отдельно через `curl`, в этот skill пока не входит.

## Когда применять

- "Посмотри логи бота за последний час" / "что там по апдейтам"
- "Почему юзер X не смог оплатить вчера в 15:00"
- "Что упало в проде" → mode `errors`
- "Запусти мониторинг логов на 5 минут после деплоя" → mode `watch` (run_in_background + Monitor)

## Когда НЕ применять

- **Локальный dev без OTLP-коллектора.** Логи всегда в stdout (`LOG_STDOUT=true` по умолчанию), а экспорт в Loki молча дропается — в Loki пусто. Смотри прямо в терминал/stdout контейнера (`docker logs`, `make run`).
- **Юзер хочет метрики** (`tg_updates_*`, `tg_update_duration_seconds`, `tg_payments_*`, доставка notifications, RPS/latency) — это VictoriaMetrics, наружу не опубликована. Скажи юзеру смотреть в Grafana.
- **Юзер хочет трейсы по trace-id** — Tempo read API существует (`https://tempo.stit.tech/api/traces/<id>`), span корня — `tg.update`, сшит `X-Request-ID=tg-<update_id>`. Но в этом skill'е не покрыт, обёртки нет. **Не** дёргай `curl` с inline-подстановкой токена из `.env.local` — значение утечёт в transcript. Нужны трейсы — заведи agent-tool по образцу `logs.sh`.

## Pre-flight

- [ ] `command -v logcli` — установлен? Если нет → `make setup` (или скажи юзеру).
- [ ] `./.env.local` существует и содержит `STIT_OBS_TOKEN=...`? Сам файл читать не нужно — `logs.sh` прочитает токен через bash (значение не попадёт в чат), или вернёт `FAIL: no STIT_OBS_TOKEN`.
- [ ] `STIT_LOKI_ADDR` задан (env или строка в `./.env.local`)? Обязателен — managed `https://loki.stit.tech`, self-hosted — свой Loki. Без него обёртка вернёт `FAIL: no STIT_LOKI_ADDR`.
- [ ] Знаешь `service` label? Дефолт в шаблоне — имя бота (`OTEL_SERVICE_NAME` env при деплое; дефолт `telegram-bot`, см. `config.py`).
- [ ] Для `watch` — оценил длительность? Не больше 10m по дефолту, юзер может расширить.

## Режимы

### `query` — точечный поиск

```bash
scripts/tools/logs.sh query --service telegram-bot --match 'panic' --since 1h --limit 200
# или raw LogQL:
scripts/tools/logs.sh query --raw '{service="telegram-bot",env="prod"} |~ "tg_id=12345"' --since 6h
```

Возвращает совпавшие строки. По умолчанию `--since 1h --limit 200`. Усечение при > 25k символов.

**Когда:** юзер дал конкретное уточнение ("найди ошибку по tg_id=X" / "что было в момент Y" / "что с charge_id=Z").

### `errors` — триаж недавних ошибок

```bash
scripts/tools/logs.sh errors --service telegram-bot --since 15m --top 10
```

Группирует error-строки по сигнатуре (числа/uuid/hex/timestamps нормализованы), выдаёт топ-N групп с count'ом. Полезно когда «что упало», а не «найди конкретное».

**Сигнатуры ловит**: `level=error`, `panic:`, traceback, `"level":"error"` (JSON-логи logkit). Частые у бота: `TelegramRetryAfter` (flood), `UnknownState`/`UnknownIntent` (stale-callback), backend-`BreakerOpen`/timeout, ошибка доставки notification.

### `watch` — мониторинг N минут

```bash
scripts/tools/logs.sh watch --service telegram-bot --for 5m
```

**Запускай через `run_in_background: true`**, потом следи через `Monitor` tool. Стримит `logcli query --tail` за окно, в конце — сводка (total lines, errors count). По SIGTERM/timeout — `OK` exit.

**Когда:** "инфра выкатывает релиз, последи 5 минут" или "следи пока я тестирую онбординг". Если окно > 10m — спроси, точно ли надо (cache TTL 5m, долгий Monitor тянет токены).

## После

- Нашёл проблему → переключайся в `triage-failure` (TDD-first для багфикса). Если это `UnknownState`-волна после деплоя — скорее `state-migration` (вырезали живой State).
- Ничего значимого → отчёт юзеру в 1-2 предложениях, не пересказывай весь output.

## Anti-patterns

- ❌ `cat ./.env.local` / `Read` на него ради токена — значение утечёт в transcript/память. Доступ к токену — только через `logs.sh`.
- ❌ Цитировать токен в чат, даже частично. Случайно подсмотрел в exec output — НЕ повторяй.
- ❌ `watch --for 30m` без явного OK. Cache miss + большой transcript.
- ❌ `query --raw` без `{}-matcher` — Loki потребует label selector, выдаст 400.
- ❌ Искать в Loki логи из локального dev без коллектора — экспорт дропнут, в Loki пусто; смотри stdout контейнера.

## См. также

- `.claude/rules/env-local.md` — формат `.env.local`, какие ключи там живут.
- `scripts/tools/logs.sh --help` — точный синтаксис флагов.
- infra-repo `docs/project-secrets.md` → «Observability read API» — где брать токен, как ротировать.
