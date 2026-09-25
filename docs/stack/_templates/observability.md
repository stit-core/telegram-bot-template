---
id: stack.observability
kind: observability
name: observability
status: draft
---

# Observability — логи

## Logging
<Структурные JSON-логи в stdout через `pylibinfra.logkit` (`LOG_LEVEL`/`LOG_FORMAT`/`LOG_SILENT`,
redact — `LOG_REDACT_*`). Метрики/трейсы шаблон не экспортирует (кит `telemetry` не подключён —
сигналы китов no-op). Trace-correlation (`request_id`, `X-Request-ID` к бэкендам) и PII-redact — из logkit.>

## Auto-emitted (kit)
<Что даёт logkit/tgbotkit само: структурные логи апдейтов с ctx-полями `request_id`/`update_id`/
`tg_user_id`/`chat_id`, `/health` + `/ready` по пробам `ExtensionProvider.probes`
(`tgbotkit`, `tgbotkit/redis`, `natskit`). См. `docs/reference/observability.md`.>

## Business signals
<Свои биз-логи (структурные поля: успех оплаты/доставки). Что считаем «успехом» и где эмитим
(usecase/handler). PII/секреты не логируем (RedactConfig).>

## Generates
<Что de-template родит:
- `logkit.Config` + `logkit.OptionalRedactConfig` в `config.py` (`new_config()`/`new_redact_config()`)
- `probes` → `healthkit.Probes` в `ExtensionProvider` (`app.py`)
- env: `LOG_*`, `HTTP_ADDR`/`HTTP_READY_PROBE_TIMEOUT` (health-порт)
- лог `"starting" service/version/commit` (`SERVICE_VERSION`/`GIT_COMMIT`)
- точки биз-логов (указатель, scaffold по фичам)>
