# de-template › doc-driven wiring

Артефакты, которые движок разворачивает как **reviewable diff поверх скелета** (в отличие от детерминированной механики Phase A). Каждый kind: прочитай его `Generates` в `docs/stack/<kind>.md`, наложи дифф в названном месте, покажи юзеру на ревью. Порядок — фундамент → роллап (зеркалит волны `stack-deep-dive`); `runtime` последним.

Ключевой принцип бота: **инфра-проводки в шаблоне нет** — она в `tgbotkit`. Wiring сводится к трём тонким файлам: `app.py` (список провайдеров), `extensions.py` (точки расширения), `config.py` (значения `*Config`). Если артефакт требует новой инфра-механики (middleware, runner) — это **не wiring, а PR в `tgbotkit`** (rule `tgbotkit-boundary`, skill `infra-handoff`).

## Порядок и маппинг

### 1. dependencies → `docs/stack/dependencies.md`
- kit-провайдеры в `app.py` `make_async_container(...)` — **только нужные** киты `pylibinfra`. Если форк без NATS — убери `NatsProvider()` и `OptionalStreamBus`/`notifiers`. Без бэкенда — но `BackendProvider` обычно остаётся.
- порядок провайдеров критичен: `BotProvider()` даёт дефолты (Logger=nop, bundles, ErrorUX, Optional*), поэтому `LogkitProvider()` и `ExtensionProvider()` — **после** него (last-wins). `AiogramProvider()` обязателен (REQUEST-контекст для identity).

### 2. storage → `docs/stack/storage.md`
- Redis-проводка — **в kit'е** (`RedisStorage` с `with_destiny`, `RedisEventIsolation`). Шаблон ничего не настраивает руками, кроме `REDIS_URL` (через cachekit `Config` в `config.py`).
- Если стек заявил кастомные TTL/префиксы за пределами дефолтов kit'а — это PR в `tgbotkit`, не wiring.
- Проверь: `storage` НЕ Memory (Memory теряет диалоги при рестарте/мультиинстансе). Если в форке где-то Memory — баг.

### 3. backends → `docs/stack/backends.md`
- `BACKEND_*_BASE_URL`, таймауты, breaker — через httpclient `Config` в `config.py`.
- несколько бэкендов = именованные клиенты/провайдеры в `platform/backend/provider.py`.
- доменный маппинг ошибок (`BackendNotFound`/`BackendUnavailable`) — в `platform/backend/errors.py` (общий), уточняется в `gateway.py` каждой фичи.

### 4. dialogs → `docs/stack/dialogs.md`
- `RouterBundle` в `extensions.py` (`routers`) — список `Dialog`'ов своих фич.
- корневой `LaunchMode.ROOT` — ровно один (карта флоу из артефакта). `/start`=RESET_STACK — в команд-хендлере корневой фичи.
- `ErrorUX` (`error_ux` в `extensions.py` → `AppErrorUX` в `platform/dialogs/errors.py`): тексты на `UnknownIntent`/`UnknownState`. Регистрация error-handlers — в kit'е.
- StatesGroup-инвентарь → `platform/dialogs/states.py`.

### 5. messaging → `docs/stack/messaging.md`
- `NotifierBundle` в `extensions.py` (`notifiers`) — `build_router(...)` своей notifications-фичи: какие stream/subject/durable.
- `NATS_URL` + JetStream-настройки через natskit `Config` в `config.py`.
- `OptionalStreamBus` отдаётся только при включённом JetStream (иначе None → runner пропускает notifications).
- если push не нужен — убери notifications-фичу (`references/prune.md`) и `NotifierBundle`/`NatsProvider`.

### 6. auth → `docs/stack/auth.md`
- identity-link tg↔backend — в `platform/identity/` (`IdentityProvider`, REQUEST-scope).
- admin-allowlist — `APP_ADMIN_IDS` в `config.py` (`AppConfig.admin_id_set()`).
- WebApp initData — `platform/webapp/init_data.py` (`validate_init_data`); убери, если без Mini App.

### 7. observability → `docs/stack/observability.md`
- `OTEL_*` через telemetry `Config` в `config.py`; `service_name` из `service.md` (дефолт + env `OTEL_SERVICE_NAME`).
- метрики `tg_*` эмитит kit; бизнес-метрики `biz_tg_*` — в usecase через bizmetric (если стек их объявил).
- health/ready — httpkit (поднимается kit'ом при webhook/health-режиме).

### 8. runtime → `docs/stack/runtime.md` (последним)
- `BOT_MODE` (polling/webhook), webhook-секрет, инстансы — через tgbotkit `Config` в `config.py`. Сам выбор runner'а (polling/webhook) — внутри `BotRunner`, шаблон лишь задаёт `Config`.
- i18n-каталоги: `config.py` строит `I18nConfig(default_locale, locales_dir, resources)` — синхронизируй `_I18N_RESOURCES`/`_DEFAULT_LOCALE` с фактическими фичами и локалями.
- graceful shutdown (drain → `container.close()` → `bot.session.close()`) — в kit'е; `app.run()` лишь резолвит `BotRunner` и зовёт `.run()`.

## Принцип

Не сочиняй wiring «по памяти» — `Generates`-секция артефакта это source of truth. `TBD`/пусто → артефакт не `stable`, движок не должен был стартовать (см. Gate в `SKILL.md`): вернись в `stack-deep-dive`.

После каждого kind — `uv run pytest -k collision` (контейнер собирается, `setup_dialogs` без коллизий) зелёный, прежде чем переходить к следующему. `runtime` закрывает композицию — после него `make check` целиком.
