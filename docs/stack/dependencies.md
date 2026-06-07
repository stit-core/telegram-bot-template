---
id: stack.dependencies
kind: dependencies
name: dependencies
status: draft
---

# Dependencies — внешние зависимости и деградация

## pylibinfra kits
<Единственная рантайм-зависимость — `pylibinfra[tgbotkit]` (ноль прямых инфра-пинов; пин по
git-ref в `[tool.uv.sources]`). Какие kit'ы бот реально потребляет:
| Kit | Роль | Когда |
|---|---|---|
| tgbotkit | вся bot-инфра (Bot/Dispatcher/runner/middleware/error-UX/i18n/notify/pay) | всегда |
| telemetry/logkit | OTel + structlog (PII-redact) | всегда |
| cachekit | Redis (FSM-коннект/dedup/link) | всегда |
| httpclient | backend-gateway (retry/breaker/OTel/X-Request-ID) | всегда |
| natskit | подписка на события бэкенда → push | если notifications |
| httpkit | FastAPI: health + приём вебхуков | webhook |
| timerkit | джобы | опц. |
Postgres-kit — **не нужен** (боту Postgres не нужен).>

## External runtime deps
<Внешние сервисы, без которых бот не работает / деградирует:
| Зависимость | Роль | Деградация при недоступности |
|---|---|---|
| Redis | state/dedup/link | **критично** — бот не стартует (нет storage) |
| Telegram API | транспорт | ретраи `TelegramRetryAfter` (kit) |
| бэкенд (HTTP) | бизнес-данные | breaker open → UX-текст «недоступно» (graceful) |
| NATS | push-уведомления | notifications не доставляются; диалоги работают |
Опиши деградацию каждой зависимости в твоём боте.>

## Capacity
<Ожидаемая нагрузка (апдейтов/сек), число инстансов (polling=1, webhook≥2), Redis-память
(контексты+TTL), connection-пулы httpclient/redis/nats. Лимиты Telegram (флуд, 30 msg/sec на чат).>

## Generates
<Что de-template родит:
- состав провайдеров в `app.py` (только нужные kit'ы)
- `pylibinfra[tgbotkit]` pin в `pyproject.toml` (+ `[testkit]` в dev)
- runtime-deps в compose.dev.yml (redis/nats) и INFRA-HANDOFF>
