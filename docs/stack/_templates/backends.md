---
id: stack.backends
kind: backends
name: backends
status: draft
---

# Backends — HTTP-клиенты (`pkg/http_client`)

## Topology
<Какие бэкенды зовёт бот. По умолчанию — один internal-бэкенд `core` (profile/booking/payments
живут на одном base_url). Несколько бэкендов → именованные клиенты + `HTTPCLIENT_BACKENDS`/
`<NAME>_BASE_URL`. Сторонние API — `external/`.>

## Clients
<Перечень API-классов (`internal/<name>.py`): срез путей + pydantic wire-модели поверх kit-`ApiClient`.
Имя бэкенда = ключ `BackendsConfig` = label breaker-метрик (дефолт `core`).>

## Idempotency & errors
<Где нужен `Idempotency-Key` (мутации). typed-ошибки kit'а (`NotFound`/`Conflict`/`Unavailable`)
мапятся в sentinel'ы фичи в `usecase` (anti-corruption), не в presentation.>

## Generates
<Что de-template/scaffold родят:
- `pkg/http_client/internal/<name>.py` (API-классы + wire-модели)
- `BackendsConfig` + `http` в `config.py`
- `InternalApiProvider` (`@provide`) в `pkg/http_client/provider.py`
- env: `HTTPCLIENT_BASE_URL` (+ `<NAME>_BASE_URL`/`HTTPCLIENT_BACKENDS` при нескольких)>
