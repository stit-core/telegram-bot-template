# Зона D — core/runtime-киты pylibinfra (для Telegram-бота)

> Источник: `/root/git/sftbmb/sftbmb-core/pylibinfra/src/pylibinfra`. Все API прочитаны из кода (не по памяти). Пути ниже относительны корня репо pylibinfra.
>
> **Сквозные инварианты pylibinfra**, важные для бота:
> - Каждый кит — `dishka.Provider`, `scope = Scope.APP`. Подключается независимо.
> - **Asymmetry note** (повторяется в каждом `module.py`): Provider **НЕ** provide'ит свой `*Config` — его регистрирует caller сам (свой `Provider`, отдающий все `*Config`). Дешёвая альтернатива DI — фабрики `new_config()` / `new_*_config()`.
> - `Config` всех китов — `pydantic-settings BaseSettings` с `extra="ignore", populate_by_name=True`. Каждое поле читает ENV через `validation_alias`. Это **public API** (менять env-alias = breaking, см. README:191-199).
> - Таймауты/интервалы везде в **секундах** (float).
> - OTel-инструменты middleware/logkit берут **глобальный** `metrics.get_meter("app")` — он no-op без `telemetry.init`, поэтому telemetry должна инициализироваться первой.

---

## 1. config — env + Vault (Source-композиция)

Файлы: `src/pylibinfra/config/__init__.py`, `loader.py`, `vault.py`, `module.py`.

Модель: env читается **нативно** pydantic-settings (базовый слой). Поверх накладываются `Source`'ы как init-kwargs (типично Vault) — а init-kwargs в pydantic-settings приоритетнее env, поэтому **Vault перезатирает env-defaults** (`loader.py:1-7`).

### Публичный API

| Символ | Сигнатура / поля | Путь |
|---|---|---|
| `Source` (Protocol) | `apply(self, dst: dict[str, Any]) -> None` | `config/loader.py:14` |
| `load[T: BaseModel]` | `load(model_cls: type[T], *sources: Source) -> T` — прогоняет sources в `overrides`, затем `model_cls(**overrides)` | `config/loader.py:18` |
| `VaultClientConfig` | `addr` (`VAULT_ADDR`=""), `token` (`VAULT_TOKEN`=""), `namespace` (`VAULT_NAMESPACE`="") | `config/vault.py:8` |
| `new_vault_client` | `(cfg: VaultClientConfig) -> hvac.Client \| None` — None если `addr` пуст | `config/vault.py:16` |
| `VaultSource` | `__init__(client: hvac.Client\|None, path: "<mount>/<key>", *, mapping: dict[str,str]\|None=None)`; `apply()` читает KV v2, кладёт значения по env-именам | `config/vault.py:26` |
| `new_vault_client_config` | `() -> VaultClientConfig` | `config/module.py:17` |

### Provider

`ConfigProvider(Provider)`, `Scope.APP` (`config/module.py:9`):
- provide `vault_client(cfg: VaultClientConfig) -> hvac.Client | None` — может вернуть **None** (VAULT_ADDR пуст), потребитель обязан проверять.
- **Не** provide'ит `VaultClientConfig` — caller регистрирует сам.

### Пример wiring

```python
from pylibinfra.config import load, VaultClientConfig, VaultSource, new_vault_client
from pylibinfra.config import ConfigProvider

vc = new_vault_client(VaultClientConfig())  # None в local-dev
class BotSecrets(BaseModel):
    bot_token: str

# env-default'ы + override из Vault KV v2 (mount/key); mapping: ключ_секрета -> env-имя
secrets = load(BotSecrets, VaultSource(vc, "kv/telegram-bot",
                                       mapping={"telegram_token": "BOT_TOKEN"}))
```

**Для бота:** токен бота — кандидат на Vault (`VaultSource`), но в local-dev `vault_client=None` → секрет берётся из ENV. `config` кит опционален: если секреты только в ENV, бот может вообще не подключать `ConfigProvider`, а грузить свой `BaseSettings` напрямую.

---

## 2. telemetry — bootstrap OTel (trace/meter/log)

Файлы: `telemetry/__init__.py`, `config.py`, `init.py`, `module.py`, `decorator.py`.

### Config (`telemetry/config.py:5`) — все поля = public API

| Поле | env-alias | default |
|---|---|---|
| `service_name` | `OTEL_SERVICE_NAME` | **обязательно** (нет default) |
| `service_version` | `OTEL_SERVICE_VERSION` | `"dev"` |
| `environment` | `APP_ENV` | `"dev"` |
| `otlp_endpoint` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `"localhost:4318"` |
| `otlp_insecure` | `OTEL_EXPORTER_OTLP_INSECURE` | `True` |
| `sample_ratio` | `OTEL_TRACES_SAMPLER_ARG` | `1.0` |
| `export_timeout` | `OTEL_EXPORT_TIMEOUT` | `10.0` (сек) |
| `tenant` | `OTEL_TENANT` | `""` (ставит только local-dev; в проде force-сетит корп collector) |
| `otlp_bearer_token` | `OTEL_TOKEN` | `""` → `Authorization: Bearer` к OTLP |
| `stdout_only` | `OTEL_STDOUT_ONLY` | `False` → dev: всё в stdout |

### Публичный API

| Символ | Описание | Путь |
|---|---|---|
| `init(cfg: Config) -> Providers` | поднимает Tracer/Meter/LoggerProvider, ставит их глобально, ставит W3C-propagators, включает `SystemMetricsInstrumentor` (system_* метрики) | `telemetry/init.py:59` |
| `Providers` (dataclass) | `.tracer_provider/.meter_provider/.logger_provider`, метод `.shutdown()` (logs→meter→trace) | `telemetry/init.py:47` |
| `span(name, **attrs)` (contextmanager) | обёртка над `tracer.start_as_current_span`; авто `record_exception`+`Status(ERROR)` на исключении | `telemetry/decorator.py:13` |
| `new_config() -> Config` | `telemetry/module.py:37` |

Resource attrs (`init.py:77`): `service.name`, `service.version`, `deployment.environment.name`; `service.namespace`+`tenant` — только если `cfg.tenant` задан. Экспорт: OTLP **HTTP** (`v1/traces`, `v1/metrics`, `v1/logs`), batch для traces/logs, periodic для metrics; либо stdout console-exporters при `stdout_only`.

### Provider (`telemetry/module.py:15`)

`TelemetryProvider(Provider)`, `Scope.APP`:
- `providers(cfg: Config) -> AsyncIterator[Providers]` — **async-generator**: `init(cfg)` на старте, `p.shutdown()` на `container.close()` (lifecycle!).
- `tracer(_: Providers) -> Tracer` = `trace.get_tracer("app")`
- `meter(_: Providers) -> Meter` = `metrics.get_meter("app")`
- `logger_provider(p) -> LoggerProvider`
- **Не** provide'ит `Config`.

### Пример wiring

```python
from pylibinfra.telemetry import TelemetryProvider, Config as TelConfig
class AppConfig(Provider):
    scope = Scope.APP
    @provide
    def tel(self) -> TelConfig: return TelConfig()   # OTEL_SERVICE_NAME из env
container = make_async_container(TelemetryProvider(), AppConfig())
tracer = await container.get(Tracer)   # триггерит init → выставляет globals
```

**Важно:** резолв `Tracer`/`Meter`/`Logger` лениво триггерит `init()`. logkit и httpkit-метрики работают только если telemetry уже инициализирован (они читают глобальные providers).

---

## 3. logkit — structlog + OTel-bridge + PII-redact

Файлы: `logkit/__init__.py`, `config.py`, `logger.py`, `service.py`, `structlog_impl.py`, `redact.py`, `module.py`.

Каждый record → stdout (JSON) **и** в OTel LoggerProvider (→ corp Loki). `trace_id`/`span_id` инжектятся автоматически из текущего span'а через **contextvars** (ctx в сигнатуру НЕ пробрасывается, `logger.py:1-8`). Эмитит `log_messages_total{level}`.

### Публичный API

| Символ | Сигнатура | Путь |
|---|---|---|
| `Logger` (Protocol) | `debug/info/warn/error(msg: str, **kv)`, `with_(**kv) -> Logger` | `logkit/logger.py:13` |
| `nop() -> Logger` | no-op логгер (дефолт в httpkit) | `logkit/logger.py:21` |
| `Config` | `level` (`LOG_LEVEL`="info") | `logkit/config.py:5` |
| `RedactConfig` | `enabled` (`LOG_REDACT_ENABLED`=False), `patterns` (`LOG_REDACT_PATTERNS`="", запятая-разделённые regex) | `logkit/redact.py:23` |
| `ServiceConfig` | `service_name`/`service_version`/`environment` (`OTEL_*`/`APP_ENV`) — для test/не-OTel вывода, модулем как record-attrs **не** инжектится | `logkit/service.py:8` |
| `configure(cfg, *, redact_cfg=None, use_otel=True)` | настраивает structlog + stdlib logging + OTel LoggingHandler | `logkit/structlog_impl.py:71` |
| `new_logger() -> Logger` | `logkit/structlog_impl.py:130` |
| `build_redactor(cfg) -> Processor\|None` | встроенные паттерны: email + 13-19-значные цифры → `[REDACTED]` | `logkit/redact.py:35` |
| `new_config/new_service_config/new_redact_config` | фабрики | `logkit/module.py:24-33` |

### Provider (`logkit/module.py:15`)

`LogkitProvider(Provider)`, `Scope.APP`:
- `logger(cfg: Config, redact_cfg: RedactConfig) -> Logger` — вызывает `configure()` и `new_logger()`.
- **Не** provide'ит `Config`/`ServiceConfig`/`RedactConfig`.
- Работает **и без telemetry** в DI (тогда OTel-handler no-op, вывод только в stdout) — `module.py:10-14`.

`register_attr` как такового нет — аналог реализован через **structlog contextvars**: `RequestIDMiddleware` делает `bind_contextvars(request_id=...)`, и `merge_contextvars` (первый processor, `structlog_impl.py:81`) подмешивает их в каждый запись. Для бота можно так же биндить `tg_user_id`/`chat_id`/`update_id`.

### Пример wiring

```python
from pylibinfra.logkit import LogkitProvider, Config as LogConfig, RedactConfig, Logger
class AppConfig(Provider):
    scope = Scope.APP
    @provide
    def log(self) -> LogConfig: return LogConfig()
    @provide
    def redact(self) -> RedactConfig: return RedactConfig()
container = make_async_container(TelemetryProvider(), LogkitProvider(), AppConfig())
log = await container.get(Logger)
log.info("bot started", mode="polling")
```

---

## 4. clockkit — Clock-port + фейки

Файлы: `clockkit/__init__.py`, `clock.py`, `fakes.py`, `module.py`.

| Символ | Сигнатура | Путь |
|---|---|---|
| `Clock` (runtime Protocol) | `now() -> datetime` | `clockkit/clock.py:11` |
| `Real` | `now()` = `datetime.now(UTC)` | `clockkit/clock.py:16` |
| `Fixed(t)` | всегда возвращает `t` (тест) | `clockkit/fakes.py:6` |
| `Tickable(start)` | `now()` + `advance(delta: timedelta)` (тест) | `clockkit/fakes.py:16` |

**Provider** `ClockProvider(Provider)`, `Scope.APP`: `clock = provide(Real, provides=Clock)` (`clockkit/module.py:6`). **Без Config**, без lifecycle.

**Для бота:** инжектить `Clock` вместо `datetime.now()` — детерминизм в тестах напоминаний/расписаний (подмена на `Tickable`).

---

## 5. flagkit — feature flags из ENV

Файлы: `flagkit/__init__.py`, `flag.py`, `module.py`.

`FEATURE_FLAGS=foo=true,bar=baz` → `Store`. Без remote-источников и динамического refresh — kill-switch на рестарт (`flag.py:1-6`).

| Символ | Сигнатура | Путь |
|---|---|---|
| `Config` | `definitions` (`FEATURE_FLAGS`="") | `flagkit/flag.py:14` |
| `Store` (Protocol) | `bool(name) -> bool`, `str(name) -> str` | `flagkit/flag.py:20` |
| `EnvStore(cfg)` | парсит CSV `key=val`; `bool` true для `"true"`/`"1"`; неизвестный флаг → `False`/`""` | `flagkit/flag.py:25` |
| `new_config()` | `flagkit/module.py:16` |

**Provider** `FlagkitProvider`, `Scope.APP`: `store(cfg: Config) -> EnvStore` provides `Store` (`flagkit/module.py:8`). **Не** provide'ит Config.

**Для бота:** опционально — гейтить новые хэндлеры/диалоги (`store.bool("new_onboarding")`).

---

## 6. timerkit — периодические джобы (asyncio, lifecycle-aware)

Файлы: `timerkit/__init__.py`, `timerkit.py`, `module.py`. **Ключевой кит для напоминаний/расписаний бота.**

| Символ | Сигнатура | Путь |
|---|---|---|
| `PeriodicJob` (frozen dataclass) | `name: str`, `interval: float` (сек), `handler: Callable[[], Awaitable[None]]` | `timerkit/timerkit.py:13` |
| `Runner(jobs, log)` | `start()` — по `asyncio.Task` на job; `async stop()` — cancel + `gather(return_exceptions=True)` | `timerkit/timerkit.py:20` |

Цикл `_loop` (`timerkit.py:37`): `await handler()` → на исключении (кроме `CancelledError`) логирует `timerkit: job error` и **продолжает** (recover, процесс не падает) → `await asyncio.sleep(interval)`. Семантика: **handler сначала, потом sleep** (первый прогон сразу на старте, не после интервала).

### Provider (`timerkit/module.py:12`)

`TimerkitProvider(Provider)`, `Scope.APP`:
- `runner(jobs: list[PeriodicJob], log: Logger) -> AsyncIterator[Runner]` — **async-generator**: `r.start()` на резолве, `await r.stop()` на `container.close()`.
- **Не** provide'ит `list[PeriodicJob]` — caller собирает джобы из своих сервисов и регистрирует список сам.
- Зависит от `logkit.Logger` (нужен в контейнере).

### Пример wiring

```python
from pylibinfra.timerkit import TimerkitProvider, PeriodicJob, Runner
class BotJobs(Provider):
    scope = Scope.APP
    @provide
    def jobs(self, reminders: ReminderService) -> list[PeriodicJob]:
        return [PeriodicJob(name="reminders", interval=60.0, handler=reminders.tick)]
container = make_async_container(LogkitProvider(), TimerkitProvider(), BotJobs(), AppConfig())
await container.get(Runner)   # запускает джобы; container.close() их гасит
```

**Предостережения для бота:**
- timerkit — это **fixed-interval poller**, НЕ cron (нет «в 09:00»). Для расписаний «к конкретному времени» handler сам проверяет `clock.now()` и решает, пора ли (часто `interval`≈60s + проверка дедлайнов в БД).
- Джобы крутятся **в том же процессе/event-loop**, что и бот. Тяжёлый handler блокирует loop — выноси I/O в await.
- Состояние (напоминания) должно жить в БД/бэкенде, не в памяти Runner'а — он не персистентный и стартует «с нуля» при рестарте.

---

## 7. bizmetric — бизнес-метрики (конвенция `biz_<domain>_<event>_*`)

Файлы: `bizmetric/__init__.py`, `bizmetric.py`. Имена форсятся в `biz_<domain>_<name>_<suffix>`; невалидные (не `^[a-z][a-z0-9_]*$`) → `ValueError`.

| Функция | Имя метрики | Тип OTel | Путь |
|---|---|---|---|
| `counter(meter, domain, name, *, description="")` | `biz_<domain>_<name>_total` | `Counter` | `bizmetric/bizmetric.py:23` |
| `histogram(meter, domain, name, *, description="")` | `biz_<domain>_<name>_seconds` (unit="s") | `Histogram` | `bizmetric/bizmetric.py:28` |
| `gauge(meter, domain, name, *, description="")` | `biz_<domain>_<name>` (без суффикса) | `UpDownCounter` | `bizmetric/bizmetric.py:33` |
| `must_name(domain, name) -> str` | валидация + сборка имени | — | `bizmetric/bizmetric.py:42` |

**Нет Provider** — это голые функции над `Meter` (взять `await container.get(Meter)` или `metrics.get_meter("app")`). Resource-attrs добавляет SDK; в labels их класть не нужно (`bizmetric.py:8`). Дашборд `Apps · Business` автодискаверит `{__name__=~"biz_.*"}`.

```python
from pylibinfra.bizmetric import counter
sent = counter(meter, "tg", "messages_sent")   # biz_tg_messages_sent_total
sent.add(1, {"kind": "reminder"})
```

**Для бота:** `biz_tg_updates_total`, `biz_tg_commands_total{command}`, `biz_tg_dialog_completed_total{flow}` и т.п.

---

## 8. httpkit — FastAPI bootstrap + middleware (только webhook-режим)

Файлы: `httpkit/__init__.py`, `config.py`, `server.py`, `module.py`, `health.py`, `error.py`, `context.py`, `metrics.py`, `cors.py`, `auth.py`, `ratelimit.py`, `maxbody.py`, `security.py`, `idempotency.py`, `middleware/*`.

### Config (`httpkit/config.py:18`) — все = public API

| Поле | env-alias | default |
|---|---|---|
| `addr` | `HTTP_ADDR` | `":8080"` (bind-all) |
| `read_timeout` | `HTTP_READ_TIMEOUT` | `15.0` |
| `write_timeout` | `HTTP_WRITE_TIMEOUT` | `30.0` |
| `idle_timeout` | `HTTP_IDLE_TIMEOUT` | `60.0` → uvicorn `timeout_keep_alive` |
| `shutdown_timeout` | `HTTP_SHUTDOWN_TIMEOUT` | `15.0` |
| `api_title` / `api_version` | `HTTP_API_TITLE` / `HTTP_API_VERSION` | `"API"` / `"0.1.0"` |
| `cors` | вложенный `CORSConfig` | factory |
| `rate_limit` | вложенный `RateLimitConfig` | factory |
| `max_body` | вложенный `MaxBodyConfig` | factory |
| `security` | вложенный `SecurityHeadersConfig` | factory |
| `idempotency` | вложенный `IdempotencyConfig` | factory |

Вложенные конфиги (свои env-alias'ы):
- `CORSConfig` (`cors.py:16`): `HTTP_CORS_ORIGINS`(""→CORS off), `HTTP_CORS_METHODS`, `HTTP_CORS_HEADERS`, `HTTP_CORS_MAX_AGE`(600).
- `RateLimitConfig` (`ratelimit.py:17`): `HTTP_RATE_LIMIT_RPS`(100; 0→off), `HTTP_RATE_LIMIT_BURST`(200). Token-bucket **per-IP**, превышение → 429.
- `MaxBodyConfig` (`maxbody.py:19`): `HTTP_MAX_BODY_BYTES`(1 MiB; 0→off) → 413.
- `SecurityHeadersConfig` (`security.py:13`): `HTTP_HSTS`, `content_type_options`(nosniff), `frame_options`(DENY), `referrer_policy`, `HTTP_CSP`(""). Пустое поле → заголовок не ставится.
- `IdempotencyConfig` (`idempotency.py:22`): `HTTP_IDEMPOTENCY_HEADER`(Idempotency-Key), `HTTP_IDEMPOTENCY_TTL`(86400), `HTTP_IDEMPOTENCY_MAX_BODY_BYTES`(65536).

### Сборка app (`httpkit/server.py`)

`build_app(cfg, log, *, instruments=None, store=None, auth=None, probes=()) -> FastAPI` (`server.py:40`):
- регистрирует error-handlers (`register_error_handlers`) и health (`register_health`);
- навешивает middleware-цепочку (порядок выполнения снаружи→внутрь): **CORS → Auth(opt) → RateLimit → MaxBody → RequestID → Recovery → SecurityHeaders → AccessLog → Metrics → Idempotency(opt)**;
- `FastAPIInstrumentor.instrument_app(app)` — серверные спаны/trace-context (идемпотентно).

`Server(cfg, log=None, *, store=None, auth=None, probes=(), instruments=None)` (`server.py:80`): держит `uvicorn.Server`; `async start()` запускает `serve()` отдельной задачей; `async stop()` ставит `should_exit` и ждёт с `shutdown_timeout`. `.app` — собранный FastAPI.

`_addr_host_port` (`server.py:34`): `":8080"` → host `0.0.0.0`, port 8080.

### Health (`httpkit/health.py`)

- `Probe` (runtime Protocol): `async __call__() -> None` (`health.py:15`).
- `register_health(app, *probes)` (`health.py:19`): `GET /health` → `{"status":"ok"}` (liveness); `GET /ready` гоняет probes, любая ошибка → 503 `UNHEALTHY` (readiness).

### Error-модель (`httpkit/error.py`)

- `APIError(Exception)` — RFC 7807 Problem+JSON (`{code,status,title,detail,type,instance}`), `to_body()` с omit-empty (`error.py:20`).
- Хелперы: `error(code,status,detail)`, `bad_request/unauthorized/forbidden/not_found/conflict/internal(code,detail)` (`error.py:89-114`).
- `map_err(err, *ErrorMapping)`, `map_sentinel(err, target, code, status, detail)` (`error.py:131/140`) — маппинг доменных ошибок → APIError.
- `register_error_handlers(app)` (`error.py:169`) — рендерит APIError → `application/problem+json`.

### Request-context (`httpkit/context.py`)

`HEADER_REQUEST_ID = "X-Request-ID"`, `request_id() -> str` (из contextvar). `RequestIDMiddleware` читает/генерит uuid4, кладёт в contextvar + `structlog.bind_contextvars(request_id=...)`, возвращает заголовком (`middleware/request_id.py`).

### Метрики (`httpkit/metrics.py`)

`HTTPInstruments(meter)` / `new_instruments()` (глоб. meter): `http_requests_total`, `http_request_duration_seconds`, `http_panics_total`, `http_max_body_rejections_total`, `http_idempotency_total`. `MetricsMiddleware` использует **route-шаблон** (`route.path_format`), а не сырой URL — против взрыва кардинальности (`middleware/metrics.py:45`).

### Provider (`httpkit/module.py`)

`HttpProvider(Provider)`, `Scope.APP` (`module.py:28`):
- defaults: `default_logger -> Logger = nop()`, `default_store -> OptionalStore = None`, `default_auth -> OptionalAuth = None`, `default_probes -> ProbeBundle = ()`.
- `server(cfg, logger, store, auth, probes) -> AsyncIterator[Server]` — **async-generator**: `await srv.start()` / `await srv.stop()` (lifecycle).
- `app(server) -> FastAPI`.
- **Не** provide'ит `Config`.
- **Опциональные зависимости** (Store/Auth/Probes) выражены типами-обёртками `OptionalStore`/`OptionalAuth`/`ProbeBundle` — dishka не умеет optional по `X | None`, поэтому consumer регистрирует свой Provider **после** HttpProvider, чтобы переопределить дефолт (last-wins, `module.py:15-22`).

`setup(app, container)` (`module.py:66`) — обёртка над `dishka.integrations.fastapi.setup_dishka` для `FromDishka` в роутах.

### Пример wiring (webhook-режим бота)

```python
from pylibinfra.httpkit import HttpProvider, Config as HttpConfig, Server, setup
from dishka.integrations.fastapi import FromDishka, inject

class AppConfig(Provider):
    scope = Scope.APP
    @provide
    def http(self) -> HttpConfig: return HttpConfig()   # HTTP_ADDR из env

container = make_async_container(
    TelemetryProvider(), LogkitProvider(), HttpProvider(), AppConfig(),
)
server = await container.get(Server)   # стартует uvicorn
app = server.app
setup(app, container)                  # FromDishka в роутах

@app.post("/webhook/{token}")
@inject
async def tg_webhook(token: str, update: dict, dp: FromDishka[Dispatcher]):
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}
```

Бот регистрирует webhook-роут на `server.app` **до** или после `setup()`; aiogram-`Dispatcher`/`Bot` инжектятся через `FromDishka`. Health `/health` и `/ready` уже есть из коробки.

---

## Как бот это потребляет

### Базовый observability-набор (включается ВСЕГДА, оба режима)

| Provider | Зачем | Lifecycle |
|---|---|---|
| `TelemetryProvider` | OTLP traces/metrics/logs + `system_*`; ставит глобальные OTel-providers (от них зависят logkit и httpkit-метрики) | async-gen, `shutdown()` на close |
| `LogkitProvider` | structlog JSON + OTel-bridge, `trace_id`/`span_id` авто, `log_messages_total` | APP, без shutdown |
| `AppConfigProvider` (свой) | **обязателен** из-за asymmetry note — отдаёт все `*Config` (`telemetry.Config`, `logkit.Config`, `logkit.RedactConfig`, и т.д.) | — |

Минимум по README:121-143 — telemetry+logkit дают RED+logs+traces сразу на дашборды `Apps`.

### Включается по необходимости

| Provider/кит | Когда |
|---|---|
| `TimerkitProvider` (+ свой `list[PeriodicJob]` provider) | напоминания, периодические синки расписаний; зависит от `Logger` |
| `ClockProvider` | если нужна тестируемость времени в джобах/дедлайнах (`Fixed`/`Tickable`) |
| `FlagkitProvider` | kill-switch новых хэндлеров/диалогов (`FEATURE_FLAGS`) |
| `config.ConfigProvider` + `VaultSource`/`load` | если `BOT_TOKEN`/секреты бэкендов идут через Vault (иначе — голый ENV) |
| `bizmetric.*` (функции, не Provider) | бизнес-метрики `biz_tg_*` |

### Webhook-режим vs polling-режим

- **polling** (`bot.get_updates` / `Dispatcher.start_polling`): httpkit **НЕ нужен** — нет входящего HTTP. Долгоживущий процесс: telemetry+logkit(+timerkit) поднимаются через `make_async_container`, бот крутится в том же event-loop. Если нужны k8s-пробы/`/metrics` без вебхуков — можно добавить минимальный httpkit с `RateLimitConfig.rps=0` или вообще без бизнес-роутов (только `/health`,`/ready`).
- **webhook**: `HttpProvider` поднимает uvicorn-сервер; Telegram POST'ит на роут, бот скармливает `update` диспетчеру. Готовы health, error-модель (Problem+JSON), RequestID, метрики RED, security-headers. Telegram secret-token валидируется в самом роуте/через `AuthExtractor`.

### Порядок старта (оба режима)

1. `make_async_container(...)` со всеми Provider'ами.
2. Первый резолв `Tracer`/`Meter`/`Logger` лениво триггерит `telemetry.init()` → выставляет глобальные OTel-providers.
3. Резолв `Runner` (timerkit) / `Server` (httpkit) запускает фоновые задачи/сервер.
4. На завершении — `await container.close()`: async-generator-провайдеры гасят сервер, джобы и flush'ат telemetry в обратном порядке.

### Предупреждения (4)

1. **Порядок инициализации telemetry первичен.** logkit OTel-bridge и все httpkit/biz-метрики читают **глобальный** `metrics.get_meter("app")` / LoggerProvider. Без `telemetry.init` (т.е. без резолва из `TelemetryProvider`) они тихо становятся no-op — метрики/логи в OTLP не уйдут. Резолвь telemetry-объекты до бизнес-логики.
2. **asymmetry note: Config'и регистрирует caller.** Ни один Provider не отдаёт свой `*Config`. Без собственного `AppConfigProvider` (или `new_config()`-фабрик) контейнер не соберётся — `dishka` упадёт на нерезолвимой зависимости.
3. **timerkit — fixed-interval poller, не cron и не персистентный.** Нет «в 09:00»; handler сам сверяется с `clock.now()`/БД. Джобы живут в общем event-loop (тяжёлый handler блокирует бота) и стартуют «с нуля» при рестарте — состояние напоминаний держать в БД/бэкенде. Семантика цикла: handler выполняется **до** первого sleep (прогон сразу на старте).
4. **httpkit ≠ polling.** В polling-режиме httpkit не нужен; не тащить его ради «галочки». Если webhook — учесть, что `RateLimitMiddleware` лимитит **per client-IP** (rps=100/burst=200 по умолчанию): Telegram шлёт вебхуки с ограниченного пула IP, при высоком трафике поднять лимиты или ставить `rps=0`, иначе апдейты будут получать 429. Также `MaxBodyMiddleware` (1 MiB) — норм для Telegram-update, но учитывать при медиа.
