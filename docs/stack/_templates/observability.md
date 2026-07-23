---
id: stack.observability
kind: observability
name: observability
status: draft
---

# Observability — логи

## Logging
<Структурные JSON-логи в stdout через `pylibinfra.logkit` (`LOG_LEVEL`/`LOG_STDOUT`). Метрики/трейсы
по OTLP шаблон не экспортирует. Trace-correlation (`X-Request-ID`) и PII-redact — из logkit.>

## Auto-emitted (kit)
<Что даёт logkit/tgbotkit само: структурные логи апдейтов, trace-id корреляция
(`X-Request-ID=tg-<update_id>`), health. См. `docs/reference/observability.md`.>

## Business signals
<Свои биз-логи (структурные поля: успех оплаты/доставки). Что считаем «успехом» и где эмитим
(usecase/handler). PII/секреты не логируем (RedactConfig).>

## Generates
<Что de-template родит:
- `LogConfig` + `RedactConfig` в `config.py`
- env: `LOG_*`
- лог `"starting" service/version/commit`
- точки биз-логов (указатель, scaffold по фичам)>
