---
id: stack.observability
kind: observability
name: observability
status: draft
---

# Observability — метрики, трейсы, логи

Сигналы эмитит `tgbotkit`/kit'ы автоматически (см. docs/reference/observability.md). Здесь —
**telemetry-режим**, бизнес-метрики и trace-точки твоего бота.

## Telemetry mode
<- dev: `OTEL_STDOUT_ONLY=true` (всё в stdout).
- prod: OTLP-endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`) + Bearer (`OTEL_TOKEN`). Resource attrs —
  только `service.name`/`service.version`/`deployment.environment.name`; `tenant`/`service.namespace`
  ставит корп-сторона (не ставить руками). Пример: dev=stdout, prod=otel.example.com.>

## Auto-emitted (kit)
<Что приходит бесплатно (перечисли, что релевантно боту):
- апдейты: `tg_updates_total{type,result}`, `tg_update_duration_seconds`, span `tg.update`.
- платежи: `tg_payments_*` (если есть payments).
- backend RED: `http_client_*` (из httpclient).
- доставка notifications (если есть).
- логи: structlog → Loki, PII-redact, `trace_id` в каждом.
- health: `/health`+`/ready` (webhook).>

## Business metrics
<Свои `biz_tg_<event>_{total|seconds}` — конверсии/команды/выполненные сценарии. Эмитятся через
`bizmetric` в `usecase` (не в presentation). Перечисли свои бизнес-события и где их Record.
Пример: `biz_tg_purchase_total{currency}`, `biz_tg_onboard_completed_total`.>

## Trace points & correlation
<Корень `tg.update` (kit). usecase-шаги — child-span через telemetry. **`X-Request-ID=tg-<update_id>`**
сшивает вызов бэкенда (ставит kit, прокидывает httpclient). Опиши, какие usecase-операции
оборачиваешь в span (платёж/доставка/длинные цепочки).>

## Generates
<Что de-template родит:
- `TelemetryProvider()`+`LogkitProvider()` в `app.py` + `OTEL_*`/`LOG_*` в `.env.example`
- `OTEL_SERVICE_NAME` дефолт в `config.py`
- (biz-метрики) точки `bizmetric` в usecase фич>
