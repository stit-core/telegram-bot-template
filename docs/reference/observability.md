# Observability

Наблюдаемость бота — **структурные JSON-логи в stdout** через `pylibinfra.logkit` плюс health-пробы
`/health` и `/ready` на порту `httpkit`. Kit пишет технические логи апдейтов автоматически — шаблон
добавляет бизнес-логи. Логи собирает рантайм контейнера (`docker/compose logs`).

## Логи (logkit)

- **Только `pylibinfra.logkit.Logger`** (`print`/stdlib `logging` забанены ruff). Формат — JSON
  (`LOG_FORMAT=json`; `text` — для глаз на локалке), уровень `LOG_LEVEL`, `LOG_SILENT=true`
  глушит sink. Логи aiogram/uvicorn уводит в тот же формат `capture_stdlib` (делает
  `LogkitProvider`).
- **Старт** — `"starting" service=bot version=<SERVICE_VERSION> commit=<GIT_COMMIT>` (`app.run`;
  значения зашивает Dockerfile при `make release`, дефолты `dev`/`unknown`).
- **Корреляция** — `request_id` (UUID v7 на апдейт; в webhook-режиме — `X-Request-ID` запроса) и
  ctx-поля `update_id`/`tg_user_id`/`chat_id` кит кладёт в каждую запись апдейта, включая записи
  usecase'ов; тот же `request_id` уезжает заголовком `X-Request-ID` в вызовы бэкендов
  (`pkg/http_client`). Фоновая доставка (`Delivery`) идёт под своим свежим id.
- **PII-redact** — `LOG_REDACT_ENABLED=true` (+ `LOG_REDACT_PATTERNS`): маски на `msg` и строковых
  полях; `config.py` отдаёт `logkit.OptionalRedactConfig` из ENV.

## Бизнес-логи (что добавляешь сам)

`log.info("profile.renamed", tg_id=…)` — структурные поля, не строковая интерполяция; ключ —
`<фича>.<событие>`. Осмысленные доменные события (успешная оплата, отправка уведомления,
истёкший резерв `payments.reservation_lost`/`notifications.reservation_lost`) эмить из
usecase/handler. Секреты/PII не логируем.

## Health

`HttpProvider(autostart=False)` собирает сервер httpkit, а порт (`HTTP_ADDR`, дефолт `:8080`)
занимает `BotRunner` — и в polling, и в webhook (там же живёт роут вебхука). `/health` —
liveness; `/ready` гоняет пробы из `ExtensionProvider.probes` параллельно с дедлайном
`HTTP_READY_PROBE_TIMEOUT` и отвечает `503`, если упала хоть одна:

| Проба | Что проверяет |
|---|---|
| `tgbotkit` | `getMe` — Bot API доступен, токен валиден |
| `tgbotkit/redis` | `PING` — Redis (FSM/dedup/лимиты/identity-link) |
| `natskit` | статус соединения NATS (push-события) |

Инфра проверяет `make ps` → `healthy`. Деградация Redis видна и в логах кита
(`tgbotkit: dedup unavailable, update passed through` — fail-open по апдейтам).

## Метрики и спаны

Киты инструментированы OTel (`tg_updates_total`, `tg_update_duration_seconds`, `http_client_*`,
спан `tg.update` на апдейт и т.п.), но кит `telemetry` в шаблоне не подключён: без
`MeterProvider`/`TracerProvider` эти сигналы no-op и никуда не уходят. Наблюдаемость бота — логи и
health выше.

## Чтение прод-логов

Прод-стек живёт в хабе `<org>/infra`, этот репо к нему не ходит. Логи задеплоенного бота читаются
там: `make logs SVC=bot` (`docker compose logs --tail=100`; с workstation — через ssh на VPS).

## Локально (e2e)

`make test-integration` поднимает стек (testcontainers redis/nats). Дев-наблюдаемость — те же логи
в stdout (`LOG_FORMAT=text`).
