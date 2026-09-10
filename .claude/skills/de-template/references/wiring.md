# de-template › doc-driven wiring

Артефакты, которые движок разворачивает как **reviewable diff поверх скелета** (в отличие от детерминированной механики Phase A). Каждый kind: прочитай его `Generates` в `docs/stack/<kind>.md`, наложи дифф в названном месте, покажи юзеру на ревью. Порядок — фундамент → роллап (зеркалит волны `stack-deep-dive`); `runtime` последним.

Ключевой принцип бота: **инфра-проводки в шаблоне нет** — она в `tgbotkit`. Wiring сводится к тонким файлам: `app.py` (единый composition root: `ExtensionProvider` — точки расширения, `build_container` — список провайдеров), `config.py` (значения `*Config`, включая `BackendsConfig`), `pkg/http_client/provider.py` (клиенты API). Если артефакт требует новой инфра-механики (middleware, runner) — это **не wiring, а PR в `tgbotkit`** (rule `tgbotkit-boundary`, skill `infra-handoff`).

## Порядок и маппинг

### 1. dependencies → `docs/stack/dependencies.md`
- kit-провайдеры в `build_container()` (`app.py`) — **только нужные** киты `pylibinfra`; ядро бота всегда: `LogkitProvider`, `ClockProvider`, `CachekitProvider`, `HttpProvider(autostart=False)`, `BotProvider`, `AiogramProvider`. Если форк без NATS — убери `NatsProvider()`, `OptionalStreamBus`/`notifiers` и `natskit.probe` из `probes`. Local-only бот (без HTTP-бэкенда) — убери `ApiClientsProvider()` + `http_client.Provider()` и весь pkg/портовый HTTP-слой (чеклист — `references/prune.md` › «Local-only бот»); несколько бэкендов — наоборот, записи в `BackendsConfig` (см. п.3).
- порядок провайдеров критичен: kit'ы дают дефолты своих Optional*/кортежей (`LogkitProvider` — redact, `HttpProvider` — пробы, `BotProvider` — bundles/ErrorUX/Optional*), поэтому `AppConfigProvider()` и `ExtensionProvider()` — **после** них (last-wins). `Logger`/`Clock` — от `LogkitProvider`/`ClockProvider`, kit'ы их дефолтами не подменяют. `AiogramProvider()` обязателен (REQUEST-контекст для identity).

### 2. storage → `docs/stack/storage.md`
- Redis-проводка — **в kit'е** (`RedisStorage` с `with_destiny`, `RedisEventIsolation`). Шаблон ничего не настраивает руками, кроме `REDIS_*` (`cachekit.new_config()` в `config.py`; Redis ≥ 7, PING на старте).
- Если стек заявил кастомные TTL/префиксы за пределами дефолтов kit'а — это PR в `tgbotkit`, не wiring.
- Проверь: `storage` НЕ Memory (Memory теряет диалоги при рестарте/мультиинстансе). Если в форке где-то Memory — баг.

### 3. backends → `docs/stack/backends.md`
- Клиенты областей API — `pkg/http_client/` (`internal/` свои, `external/` сторонние), по классу на область (`ProfileAPI`-стиль) поверх `pylibinfra.httpclient.ApiClient`; провайды — `pkg/http_client/provider.py` поверх реестра `ApiClients.get(<имя>)`.
- Имена и base_url бэкендов — `BackendsConfig.backends: dict[имя, Config]` в `config.py` (`AppConfigProvider.backends`): один бэкенд — `{CORE_BACKEND: HttpConfig()}` (env `HTTPCLIENT_BASE_URL`/`HTTPCLIENT_TIMEOUT`/…); несколько — запись на каждого со своим `base_url` (свой `*_BASE_URL` env) либо env-JSON `HTTPCLIENT_BACKENDS`. Дефолтное имя breaker'а = имя бэкенда (per-API метрики) — kit ставит сам.
- Маппинг typed-ошибок (`NotFoundError`/`ConflictError`/`UnavailableError`) в sentinel'ы фичи — в `usecase.py` каждой фичи (единственная точка anti-corruption), не в общем слое.
- Идемпотентность мутаций — `idempotency_key=` в методах pkg-клиента (ASCII-safe).

### 4. dialogs → `docs/stack/dialogs.md`
- `RouterBundle` в `ExtensionProvider.routers` (`app.py`) — список `Dialog`'ов своих фич.
- корневой `LaunchMode.ROOT` — ровно один (карта флоу из артефакта). `/start`=RESET_STACK — в команд-хендлере корневой фичи.
- `ErrorUX` (`ExtensionProvider.error_ux` → `AppErrorUX` в `platform/dialogs/errors.py`): тексты на `UnknownIntent`/`UnknownState`. Регистрация error-handlers — в kit'е.
- StatesGroup-инвентарь → `platform/dialogs/states.py`.

### 5. messaging → `docs/stack/messaging.md`
- `NotifierBundle` в `ExtensionProvider.notifiers` (`app.py`) — `build_router(...)` своей notifications-фичи: какие stream/subject/durable.
- `NATS_URL` + JetStream-настройки через natskit `Config` в `config.py`.
- `OptionalStreamBus` (`ExtensionProvider.stream_bus`) отдаётся только при включённом JetStream (иначе None → runner пропускает notifications).
- если push не нужен — убери notifications-фичу (`references/prune.md`) и `notifiers`/`stream_bus`/`NatsProvider`.

### 6. auth → `docs/stack/auth.md`
- identity-link tg↔backend — в `platform/identity/` (`IdentityProvider`, REQUEST-scope).
- admin-allowlist — `APP_ADMIN_IDS` в `config.py` (`AppConfig.admin_id_set()`).
- WebApp initData — `platform/webapp/init_data.py` (`validate_init_data`); убери, если без Mini App.

### 7. observability → `docs/stack/observability.md`
- health/ready — httpkit: `HttpProvider(autostart=False)` в `build_container()` (порт `HTTP_ADDR` занимает `BotRunner` в любом режиме), `httpkit.new_config()` в `config.py`; пробы `/ready` — `ExtensionProvider.probes` → `healthkit.Probes` (`tgbotkit.probe`/`redis_probe` + пробы подключённых kit'ов: `natskit.probe` при NATS).
- логи — `logkit.new_config()` + `logkit.OptionalRedactConfig` (`new_redact_config()`) в `config.py` (`LOG_*`); лог `starting` с `SERVICE_VERSION`/`GIT_COMMIT` (`AppConfig`) уже в `app.run()`.

### 8. runtime → `docs/stack/runtime.md` (последним)
- `BOT_MODE` (polling/webhook), webhook-секрет, инстансы — через `tgbotkit.new_config()` в `config.py` (fail-fast по `BOT_*`; webhook требует https-базу и секрет). Сам выбор runner'а (polling/webhook) — внутри `BotRunner`, шаблон лишь задаёт `Config`.
- i18n-каталоги: `config.py` подменяет `i18n` копией конфига (`model_copy(update={"i18n": I18nConfig...})`; `Config` frozen) — синхронизируй `_I18N_RESOURCES`/`_DEFAULT_LOCALE` с фактическими фичами и локалями; `BOT_I18N_*` из ENV приоритетнее.
- graceful shutdown (drain → `container.close()` → `bot.session.close()`) — в kit'е; `app.run()` лишь резолвит `BotRunner` и зовёт `.run()`.

## Принцип

Не сочиняй wiring «по памяти» — `Generates`-секция артефакта это source of truth. `TBD`/пусто → артефакт не `stable`, движок не должен был стартовать (см. Gate в `SKILL.md`): вернись в `stack-deep-dive`.

После каждого kind — `uv run pytest -k collision` (контейнер собирается, `setup_dialogs` без коллизий) зелёный, прежде чем переходить к следующему. `runtime` закрывает композицию — после него `make check` целиком.
