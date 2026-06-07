# Observability

Бот эмитит **метрики, логи, трейсы** через OTel в корп OTLP-ingest. Три сигнала коррелируются
через `trace_id`; вызов бэкенда сшивается с апдейтом через `X-Request-ID`. Бóльшую часть сигналов
эмитит `tgbotkit`/kit'ы автоматически — шаблон добавляет лишь бизнес-метрики и trace-точки в
usecase. Telemetry-режим задаётся артефактом `docs/stack/observability.md`.

## Режимы telemetry

`pylibinfra/telemetry`:
- **Local dev** (дефолт `.env.example`): `OTEL_STDOUT_ONLY=true` — все сигналы в stdout.
- **Production:** OTLP-endpoint + Bearer (`OTEL_TOKEN`). Resource attrs приложения — только
  `service.name` / `service.version` / `deployment.environment.name`. `tenant` /
  `service.namespace` ставит/перезатирает корп-сторона (otel-collector) — **не ставить руками**.

Резолв Tracer в `app.run()` (`await container.get(Tracer)`) триггерит `telemetry.init`;
`container.close()` на shutdown делает telemetry-flush.

## Что эмитится автоматически

**Апдейты Telegram** (`tgbotkit` outer-middleware): `tg_updates_total{type,result}`,
`tg_update_duration_seconds`; корневой span `tg.update` на каждый апдейт (вкл. фоновые через
`DIALOG_EVENT_NAME`). Дедуп/throttle тоже учитываются в `result`.

**Отправка/флуд** (`tgbotkit`): счётчики API-вызовов и flood-wait (`TelegramRetryAfter`-ретраи).

**Платежи** (`tgbotkit`): `tg_payments_*` — pre_checkout-решения (confirm/decline/timeout),
успешные/дедупнутые `successful_payment`.

**Доставка notifications** (`tgbotkit`): метрики доставки event→Telegram + дедуп.

**HTTP-клиент бэкенда** (`httpclient`): `http_client_request_duration_seconds{host,method,status}`,
`http_client_breaker_transitions_total`, `http_client_breaker_open{name}`,
`http_client_retry_attempts_total{host}` — backend RED бесплатно.

**Redis/NATS** (`cachekit`/`natskit`): метрики операций кэша и publish/consume.

**Health** (`httpkit`, только webhook-режим): `/health` (liveness) + `/ready` (readiness). В
polling-режиме HTTP-сервера нет — health через сам процесс/`emit_startup`-smoke.

**Логи** (`logkit`): структурный structlog → OTLP → Loki; `trace_id`/`span_id` в каждом
сообщении; **PII-redact** из коробки (токены/телефоны/etc не утекают). В коде — только
`pylibinfra.logkit.Logger` (stdlib `logging`/`print` забанены ruff'ом).

## Business-метрики

Конвенция `biz_tg_<event>_{total|seconds}` — автодискавер на корп-дашборде через
`{__name__=~"biz_tg_.*"}`. Добавляются через `bizmetric` в `usecase` (там же, где
доменная логика; не в presentation). Конверсии/команды/выполненные сценарии — сюда. Логи
бизнес-событий — `log.info("profile.renamed", tg_id=…)` (структурно, с `trace_id`).

## Трейс апдейта и корреляция

- Корень `tg.update` ставит tgbotkit-middleware; usecase-шаги — child-span'ы через telemetry.
- **`X-Request-ID = tg-<update_id>`** ставит tgbotkit-middleware и прокидывает `httpclient` в
  заголовок к бэкенду → один апдейт сшит с вызовом бэкенда сквозным id. Бэкенд видит его в своих
  логах/трейсах.
- Backend HTTP-span — child от `tg.update` (W3C trace-propagation в httpclient).
- Фоновые апдейты (notifications вне обычного middleware) — `request_id`/локаль проставляются
  руками внутри `Delivery`-обёртки (грабли BgManager закрыты в kit'е).

## Где смотреть

Корп-Grafana (папка **Apps/**) — общие дашборды для всех `pylibinfra`-сервисов; фильтр по
`service`/`env`. Релевантные для бота: Service Overview, Telegram Updates, HTTP client, Bus,
Logs, Traces, Business. Project-specific funnel'ы (не покрытые общими) — PR в корп control-plane,
не в этот репо.
