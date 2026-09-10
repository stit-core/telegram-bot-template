# Observability

Наблюдаемость бота — **структурные JSON-логи в stdout** через `pylibinfra.logkit` плюс health-пробы
`/health` и `/ready` на порту `httpkit`. Метрики и спаны киты эмитят через глобальные
OTel-провайдеры, но шаблон их не экспортирует (кит `telemetry` не подключён — сигналы no-op).
Kit пишет технические логи апдейтов автоматически — шаблон добавляет бизнес-логи. Логи собирает
рантайм контейнера (`docker/compose logs`).

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

## Метрики и спаны (не экспортируются)

Киты инструментированы OTel: `tg_updates_total`, `tg_update_duration_seconds`,
`tg_update_panics_total`, `tg_payments_total`, `http_client_*`, `cache_*`, `nats_*`,
`log_messages_total`; спан `tg.update` на апдейт (в webhook — child server-спана httpkit). Без
`MeterProvider`/`TracerProvider` они no-op. Включение экспорта — `telemetry.TelemetryProvider()`
после `LogkitProvider()` в `build_container` + `telemetry.start(container)` в `app.run`; это
изменение инфра-поверхности (`OTEL_*` env, коллектор) → skill `infra-handoff`.

## Чтение

Логи — в stdout, собираются рантаймом контейнера. Чтение/агрегация прод-логов (`make logs` и куда
они складываются) — забота деплой-репо `<org>/infra`, не этого репо.

## Локально (e2e)

`make test-integration` поднимает стек (testcontainers redis/nats). Дев-наблюдаемость — те же логи
в stdout (`LOG_FORMAT=text`).
