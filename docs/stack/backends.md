---
id: stack.backends
kind: backends
name: backends
status: draft
---

# Backends — HTTP API источники

Бот — фронтенд: бизнес-данные/логика на бэкендах. Доступ — через `pylibinfra.httpclient` (retry/
breaker/OTel/X-Request-ID внутри), обёрнутый в `platform/backend/client.py: BackendClient`
(добавляет маппинг статусов в транспорт-ошибки + `Idempotency-Key`).

## Backends list
<Список бэкендов: имя, base_url (env), назначение. Несколько бэкендов = именованные
`Client`/провайдеры. Пример:
| Бэкенд | base_url (env) | Назначение |
|---|---|---|
| core-api | `HTTPCLIENT_BASE_URL` | профиль, заказы, оплата |
| (опц.) billing | `BILLING_BASE_URL` | подтверждение платежей |>

## Resilience
<Таймауты (`HTTPCLIENT_TIMEOUT`), circuit breaker, ретраи — настройки httpclient. Деградация при
open-breaker: gateway мапит `BreakerOpenError`/5xx → `BackendUnavailable` → `views.error_text` →
заранее заданный UX-текст («Сервис временно недоступен»). Опиши, какой UX при недоступности
каждого бэкенда. ВАЖНО: httpclient райзит сам только на 5xx-после-ретраев; 4xx возвращает Response
— статусы (404/409/4xx) разбирает `BackendClient._decode`.>

## Auth
<Как бот аутентифицируется в бэкенде: заголовок (Bearer/service-token), где секрет (Vault). Связь
пользователя с аккаунтом — identity-link (см. auth.md): `backend_user_id` из `link:tg:<id>`,
фолбэк до линковки — сам `tg_id`.>

## Idempotency
<Мутации защищаются `Idempotency-Key` (от двойных кликов/ретраев httpclient). Формат ключа —
детерминированный по операции (напр. `profile-rename:<uid>:<name>`, платежи — `charge_id`). Опиши
ключи для своих мутаций.>

## Generates
<Что de-template родит:
- `HttpClientProvider()` в `app.py` + `HTTPCLIENT_*` в `.env.example`
- `platform/backend/` (BackendClient + транспорт-ошибки)
- (несколько бэкендов) именованные провайдеры/клиенты
- `gateway.py` фич мапит транспорт→домен (anti-corruption DTO)>
