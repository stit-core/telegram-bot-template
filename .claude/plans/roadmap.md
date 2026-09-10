# Roadmap

Единственный артефакт планирования проекта — этот файл. Подпапок, `<slug>.md`, архивов и
changelog'ов нет: они расходятся с правдой и мешают.

**Planning-first.** Изменение идёт через план — секцию в `## Active` ниже. Прямая правка без
плана допустима только для truly-atomic (опечатка, один очевидный файл) и багфиксов (→ skill
`/triage-failure`, RED-first). Отклонение от плана — осознанное и проговаривается с юзером.

**Жизненный цикл.** `planning → in-progress → blocked? → done`. По `done` секция задачи удаляется
целиком — история остаётся в `git log`. Незакрытый follow-up переезжает в `## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `CLAUDE.md`.

**Current focus:** migrate-pylibinfra-v1

## Active

### migrate-pylibinfra-v1 — миграция шаблона на pylibinfra v1.0.0
**Создан:** 2026-09-10 · **Статус:** blocked (blocked by: передача INFRA-HANDOFF инфра-админу — секция закрывается по `make release`, который агрегирует **Infra impact.**)

**Контекст.** pylibinfra ушёл с `v0.6.0` на `v1.0.0` (`git tag -l --format='%(contents)' v1.0.0`
в `../pylibinfra`) — паритет с golibinfra v1.1.0, breaking по всем китам шаблона: `BotProvider`
не даёт `Logger`, требует `clockkit.Clock` и `httpkit.Server` (`HttpProvider(autostart=False)`),
пробы — `healthkit.Probes` от консьюмера; конфиги frozen и читаются только `new_config()`
(`cfg.i18n = …` в `config.py` падает), `OptionalRedactConfig`, `LOG_STDOUT → LOG_SILENT`;
`cachekit.Cache.get → bytes | None`, TTL — секунды `float`; `DeliveryDedup`/`ChargeGuard`/
`RefundGuard` — резерв с токеном (`reserve → token | None`, `commit/release(key, token)`);
`BreakerConfig.success_threshold` удалён; `httpclient.Client(cfg, *, transport=)`;
`answer_pre_checkout(log=)`; `StreamBus.drain()` → `Subscription.drain()`;
`testkit.start_nats(jetstream=True)`. Карта работ — атомы ниже.

**Не входит в скоуп.** Кит `telemetry` (OTLP-экспорт; шаблон logs-only — метрики/спаны китов
остаются no-op), TOTP/RBAC-фичи authnkit, дизайн диалогов, prune reference-фич, джобы `timerkit`
в каноне шаблона (только актуализация `scaffold job`), правка `pylibinfra`.

**Открытые вопросы.**
- [x] Q1: i18n-каталог из пакета при frozen `tgbotkit.Config` → `tgbotkit.new_config()`
  (fail-fast `BOT_*`) + `model_copy(update={"i18n": I18nConfig(...)})`; `BOT_I18N_*` из ENV
  приоритетнее дефолтов шаблона (каталог в пакете, локаль `ru`).
- [x] Q2: `AppConfig` — fail-fast как у китов: `APP_ADMIN_IDS` парсится в `frozenset[int]` на
  валидации (мусор валит старт), загрузка `pylibinfra.config.load` → `config.ConfigError`.
- [x] Q3: NATS остаётся обязательной runtime-зависимостью канона (как сейчас — соединение на
  старте); `natskit.probe(conn)` в `/ready`; notifications по-прежнему только при JetStream.
- [x] Q4: composition-smoke офлайн → `REDIS_PING_ON_START=false` + стаб `BOT_TOKEN` в тесте
  (граф прода без подмен провайдеров).

**Атомы.**

#### Phase 1 — пин и composition root
- [x] **A1:** `[tool.uv.sources]` rev `v0.6.0` → `v1.0.0`; `uv lock && uv sync`; из pyproject
  убран purgatory-`filterwarnings`, комментарии без structlog.
  - Verify: `uv lock --check && uv run python -c "import pylibinfra.tgbotkit"` → OK · Зависит от: —
  - **Done:** rev `v1.0.0` (f96ddd20), `uv lock`/`uv sync` — purgatory/structlog/tenacity/setuptools-пин ушли из lock; `uv lock --check` → OK.
- [x] **A2:** `config.py`: все `*Config` через `<kit>.new_config()`, `logkit.OptionalRedactConfig`,
  `httpkit.Config`, `BackendsConfig` без `success_threshold` (+ fail-fast на пустой
  `HTTPCLIENT_BASE_URL`), i18n через `model_copy`, `AppConfig` fail-fast (`admin_ids`,
  `version`/`commit`).
  - Verify: `uv run pytest tests/unit/test_config.py -q` → PASS · Зависит от: A1
  - **Done:** `config.py`: `<kit>.new_config()` для logkit/cachekit/httpkit/natskit/tgbotkit, `OptionalRedactConfig`, `BackendsConfig` = `HTTPCLIENT_BACKENDS` ∪ «core» (fail-fast `HTTPCLIENT_BASE_URL is required`), i18n через `model_copy`, `AppConfig` (`frozenset[int]` admin_ids, `version`/`commit`, `case_sensitive`); `tests/unit/test_config.py` → 5 passed.
- [x] **A3:** `app.py`: `ClockProvider`, `HttpProvider(autostart=False)`, порядок провайдеров
  (`AppConfigProvider` после `LogkitProvider`, `ExtensionProvider` после `HttpProvider`),
  `healthkit.Probes` (tgbotkit + redis + natskit), `notifiers` с `Logger`, стартовый лог
  `starting` с `version`/`commit`; `run()` закрывает контейнер при сорванном старте.
  - Verify: `uv run pytest tests/flows/test_composition.py -q` → PASS · Зависит от: A2
  - **Done:** `app.py`: `LogkitProvider`/`ClockProvider`/`CachekitProvider`/`ApiClientsProvider`/`NatsProvider`/`HttpProvider(autostart=False)`/`BotProvider`/`AiogramProvider` → `AppConfigProvider` → pkg/platform/фичи → `ExtensionProvider` (+ `probes`, `notifiers(log)`); `run()` — лог `starting`, close на сорванном старте; `tests/flows/test_composition.py` → 4 passed.

#### Phase 2 — платформа и фичи
- [x] **A4:** cachekit-контракт: `platform/links.LINK_TTL` в секундах, `IdentityProvider`,
  `start/infra/store.py`, `lang/provider.py` на `bytes | None` и `float`-TTL;
  `platform/webapp` принимает `SecretStr | str`.
  - Verify: `uv run pytest tests/unit/test_link_ttl.py tests/flows -q` → PASS · Зависит от: A1
  - **Done:** `LINK_TTL = 180*24*3600.0`, `IdentityProvider`/`CacheOnboardingStore` на `bytes | None`, `validate_webapp_user(bot_token: SecretStr | str)`; flows + `test_link_ttl` (Tickable) → PASS.
- [x] **A5:** notifications: `DeliveryDedup` с токеном (`release`/`commit(key, token)`,
  `commit=False` → warn в лог), `build_router(cache, redis, log)`.
  - Verify: `uv run pytest tests/unit/test_notifications.py -q` → PASS · Зависит от: A1
  - **Done:** `OrderDeliverer(cache, dedup, locales, log)`: `reserve → token`, `release/commit(key, token)`, `notifications.reservation_lost` warn; `build_router(cache, redis, log)`; `test_notifications.py` → 5 passed (вкл. истёкший резерв на `Tickable`).
- [x] **A6:** payments: `ChargeGuard`/`RefundGuard` из DI (APP-scope в `provider.py`), токенный
  резерв, `answer_pre_checkout(..., log=)`.
  - Verify: `uv run pytest tests/unit/test_payments_handlers.py -q` → PASS · Зависит от: A1
  - **Done:** `PaymentsProvider`: `ChargeGuard`/`RefundGuard` APP-scope; хендлеры на токенах + `payments.reservation_lost`; `answer_pre_checkout(..., log=log)`; `test_payments_handlers.py` → 15 passed.

#### Phase 3 — тесты
- [x] **A7:** фейки: `tests/_fakes/{cache,redis}.py` → `cachekit.MemoryCache` /
  `testkit.bottest.MemoryRedis`; harness провайдит `redis.Redis`.
  - Verify: `uv run pytest tests/flows -q` → PASS · Зависит от: A4, A6
  - **Done:** `tests/_fakes/{cache,redis}.py` удалены; harness — `cachekit.MemoryCache` + `bottest.MemoryRedis` (`redis.Redis`); flows → 6 passed.
- [x] **A8:** unit/pkg: `tests/pkg/conftest.py` на `Client(cfg)`, `test_error_taxonomy` без
  реальных пауз; composition-smoke офлайн (Q4); `test_link_ttl` на `Tickable`.
  - Verify: `make test` → PASS · Зависит от: A7
  - **Done:** `tests/pkg/conftest.py`/`test_error_taxonomy.py` — `Client(Config.model_validate({...}))`, ретраи с backoff 1 ms; composition-smoke — `BOT_TOKEN`-стаб + `REDIS_PING_ON_START=false` + тест «без BOT_TOKEN — старт падает»; `make test` → 114 passed.
- [x] **A9:** integration: `test_dedup_ttl` на токенах; `test_notification_redelivery` на
  `testkit.start_nats(jetstream=True)` + `Subscription.drain`.
  - Verify: `make test-integration` → PASS (Docker) · Зависит от: A5
  - **Done:** `test_dedup_ttl` — токены (+ чужой токен не снимает/не фиксирует), `test_notification_redelivery` — `start_nats(jetstream=True)`/`ns.stream_bus(...)`/`Subscription.drain`; `make test-integration` → 4 passed (Docker 29.7).

#### Phase 4 — env, доки, гейт
- [x] **A10:** `.env.example` (`LOG_FORMAT`/`LOG_SILENT`/`LOG_REDACT_*`, `HTTP_ADDR`, новые
  `BOT_*`/`NATS_*`/`REDIS_*`/`HTTPCLIENT_*`), `Makefile` (`run`), `Dockerfile`
  (`SERVICE_VERSION` в ENV).
  - Verify: `grep -rn 'LOG_STDOUT\|success_threshold\|purgatory' --exclude-dir=.git --exclude-dir=.venv --exclude=uv.lock .` → пусто · Зависит от: A3
  - **Done:** `.env.example` переписан (LOG_FORMAT/LOG_SILENT/LOG_REDACT_*, HTTP_ADDR/HTTP_READY_PROBE_TIMEOUT, BOT_*/NATS_*/REDIS_*/HTTPCLIENT_* v1), `Makefile run`, Dockerfile `ENV SERVICE_VERSION`; grep старых идентификаторов (вне roadmap) → пусто.
- [x] **A11:** доки/rules/skills синк (forward-only): `docs/reference/{architecture,observability,
  release}.md`, `docs/stack/_templates/*`, rules `tgbotkit-boundary`/`comments`/
  `background-updates`, refs `de-template/wiring`, `scaffold/{job,notification,feature}`,
  `agents/explorer`.
  - Verify: `make plan-check && make validate-stack-docs` → OK · Зависит от: A10
  - **Done:** architecture/observability/release, stack-шаблоны (observability/runtime/config/dependencies/service), rules tgbotkit-boundary/comments/background-updates/infra-impact/tests-pipeline, refs de-template wiring+SKILL, scaffold job/notification/feature/backend-port, release SKILL, explorer, README; `make plan-check && make validate-stack-docs` → OK.
- [x] **A12:** `make check` + `make test-integration` зелёные; INFRA-HANDOFF предъявлен.
  - Verify: `make check` → ✓ check clean · Зависит от: A8, A9, A11
  - **Done:** `make check` → ✓ check clean (ruff, import-linter 7/7, mypy src+tests, lock-check, 114 passed, cover 89.9 %); `make test-integration` → 4 passed; попутно снят флейк flow-тестов (`UnknownIntent` от коллизии intent-id aiogram_dialog в одну секунду) — autouse-счётчик в `tests/conftest.py` + `test_intent_ids.py`, 0/40 падений.

**Infra impact.**
- **Runtime-dep.** WHAT: пин `pylibinfra` v0.6.0 → v1.0.0 (`[tool.uv.sources]`, lock без purgatory/
  structlog/tenacity) · WHY: первый стабильный мажор инфры, breaking по всем китам бота · ACTION:
  пересборка образа в ближайший релиз (`make release`) · WHO: проектная инфра · RISK: образ на
  v0.6.0 не совместим с обновлённым env ниже.
- **ENV (переименования/новые обязательные).** WHAT: `LOG_STDOUT` → `LOG_SILENT` (инверсия; дефолт
  прежний — stdout) + новые `LOG_FORMAT`/`LOG_SOURCE`/`LOG_REDACT_REPLACE_WITH`;
  `HTTPCLIENT_BREAKER_SUCCESS_THRESHOLD` удалён (breaker — на каждый upstream-хост);
  `BOT_TOKEN` обязателен и проверяется на формат `<id>:<secret>`; в `BOT_MODE=webhook` обязательны
  `BOT_WEBHOOK_BASE_URL` (`https://`) и `BOT_WEBHOOK_SECRET` (`A-Za-z0-9_-`, 1..256);
  `APP_ADMIN_IDS` — только целые (не-число валит старт); заданная пустая переменная = дефолт кита.
  Новые опциональные с дефолтами: `BOT_API_TIMEOUT` (60), `BOT_SHUTDOWN_TIMEOUT` (10),
  `BOT_RATE_MAX_WAIT` (60), `BOT_DROP_PENDING`, `HTTP_READY_PROBE_TIMEOUT` (5), `HTTP_DOCS_ENABLED`,
  `HTTP_QUIET_PATHS`, `HTTPCLIENT_RETRY_MAX_WAIT`/`RETRY_NON_IDEMPOTENT`/`MAX_REDIRECTS`/
  `ALLOW_CROSS_HOST_REDIRECTS`, `NATS_DRAIN_TIMEOUT` (10), `NATS_JS_HANDLER_TIMEOUT`,
  `NATS_JS_STREAM_MANAGED` (true), `REDIS_KEY_PREFIX`/`REDIS_MAX_RETRIES`/`REDIS_PING_ON_START`/
  `REDIS_SKIP_VERSION_CHECK`. Дефолты сменились: `NATS_MAX_RECONNECTS` -1, `NATS_JS_MAX_DELIVER` 10,
  `NATS_JS_NAK_BACKOFF` 1 с. WHO: проектная инфра (compose env). DECIDE: `HTTP_DOCS_ENABLED=false`
  на health-порту в проде?
- **Health-порт и Redis.** WHAT: `HTTP_ADDR` (дефолт `:8080`) биндится и в polling — `/health`
  (liveness) и `/ready` (пробы Bot API `getMe`, Redis `PING`, статус NATS; 503 при любой упавшей);
  Redis обязан быть ≥ 7.0 (`PING` + проверка версии на старте; `REDIS_SKIP_VERSION_CHECK=true` для
  совместимых серверов без `redis_version`); NATS-соединение поднимается на старте всегда (при
  `NATS_JETSTREAM_ENABLED=false` подписки просто не открываются). ACTION: healthcheck/probe
  контейнера на `/ready`, порт в compose, версия Redis. WHO: проектная инфра. RISK: без Redis ≥ 7
  или недоступном NATS старт падает (задуманный fail-fast).
- **Образ.** WHAT: build-args `SERVICE_VERSION`/`GIT_COMMIT` теперь и в ENV образа — лог
  `"starting" service=bot version=… commit=…` (verify-шаг релиза). WHO: проектная инфра (без действий,
  если релиз идёт через `make release`).
- **Redis-ключи резервов.** WHAT: `tg:notify:*`/`tg:charge:*`/`tg:refund:*` хранят токен владельца
  вместо `1`; старые ключи (`1`) остаются дедупом до истечения TTL, снять их токеном нельзя (это
  `False` + warn `*.reservation_lost`, не сбой). WHO: — (информационно). ACTION: нет.

**Чекпоинты.**
- **2026-09-10 · код готов.**
  - Закрыто: A1–A12 ✓ (`make check` clean, `make test-integration` 4 passed).
  - Обнаружено: flow-тесты с вложенным диалогом флейкали и на v0.6.0 (1/15) — intent-id
    aiogram_dialog из секунд времени + `random(0..99)`; снято autouse-счётчиком в
    `tests/conftest.py` (кандидат в `pylibinfra/testkit/bottest.bind_dialogs` → Backlog).
    `BackendsConfig` теперь объединяет `HTTPCLIENT_BACKENDS` из ENV с «core» из кода (запись из
    ENV перекрывает код).
  - Следующий шаг: юзер передаёт INFRA-HANDOFF, коммит (Conventional Commits, `feat(deps)!`),
    `make release` агрегирует handoff → секция удаляется.
- **2026-09-10 · старт.** API v1.0.0 изучен по аннотации тега, README/docs китов и коду
  (`tgbotkit`, `cachekit`, `httpclient`, `natskit`, `logkit`, `healthkit`, `clockkit`,
  `httpkit`, `testkit/bottest`); карта поломок снята чтением шаблона целиком.

## Backlog

- `pylibinfra/testkit/bottest`: детерминированные intent-id для flow-тестов (перенести
  autouse-счётчик из `tests/conftest.py` шаблона в `bind_dialogs`/фикстуру кита) — PR в pylibinfra
  через `infra-handoff`; upstream-причина — `aiogram_dialog.new_int_id` (секунды + `random(0..99)`).
- INFRA-HANDOFF (не сдан — агрегировать в ближайший `make release`): (1) runtime-dep пин
  `pylibinfra` v0.3.0 → v0.6.0 — пересборка образа; natskit v0.4 сменил env-ручки:
  `NATS_JS_DLQ_ENABLED`/`NATS_JS_FLOW_CONTROL`/`NATS_JS_IDLE_HEARTBEAT` удалены, DLQ теперь
  `NATS_JS_DLQ_SUBJECT`, backoff — `NATS_JS_NAK_BACKOFF` (сек). (2) `HTTPCLIENT_BREAKER_NAME`
  удалён (имя breaker'а = имя бэкенда, только код); `HTTPCLIENT_BASE_URL` обязателен — пустой
  валит старт (задуманный fail-fast); `HTTPCLIENT_BACKENDS` требует per-backend `base_url`.
- Двойные HTTP-спаны httpclient (ручной span + `HTTPXClientInstrumentor`) — проверить на живом
  стеке, при подтверждении убрать ручной.
- Auth-hook httpclient сверх статических per-backend `headers` (токен-провайдер per-call).
