---
id: stack.observability
kind: observability
name: observability
status: draft
---

# Observability — telemetry/логи/метрики

## Telemetry mode
<OTLP-режим (managed `otel.${DOMAIN}` / self-hosted из corp-infra-template). Resource-attrs
(`service.name`/`service.version`/`deployment.environment.name` из образа; `tenant` ставит корп-edge).
Эндпоинт — `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_*`.>

## Auto-emitted (kit)
<Что эмитит tgbotkit само: трейс (span `tg.update`, `X-Request-ID=tg-<update_id>`), метрики апдейтов
(`tg_*`), breaker pkg-клиента (`http_client_breaker_*{name}`), структурные логи (logkit), health.
См. `docs/reference/observability.md`.>

## Business signals
<Свои биз-метрики (`biz_tg_*`: оплата/доставка) и биз-логи (структурные поля). Что считаем «успехом»
и где эмитим (usecase/handler). PII/секреты не логируем (RedactConfig).>

## Generates
<Что de-template родит:
- `TelConfig` (service_name) + `RedactConfig` в `config.py`
- env: `OTEL_*`
- лог `"starting" service/version/commit`
- точки биз-метрик (указатель, scaffold по фичам)>
