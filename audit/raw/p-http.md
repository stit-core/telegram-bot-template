# Аудит p-http — httpclient (исходящий) + httpkit (серверный)

## Что смотрел

- **httpclient** (317 LOC, 7 файлов): `client.py` (148), `breaker.py` (58), `config.py` (17),
  `module.py` (32), `metrics.py` (35), `reqid.py` (7), `__init__.py` (20). Исходящий HTTP-клиент
  поверх httpx: retry (tenacity), circuit breaker (purgatory), OTel-span на запрос,
  авто-прокидывание `X-Request-ID` из contextvar, таймауты, поведение 4xx vs 5xx.
- **httpkit** (1346 LOC, ~20 файлов): серверный стек на FastAPI/uvicorn — `server.py`,
  middleware-цепочка (CORS/RateLimit/MaxBody/RequestID/Recovery/Security/AccessLog/Metrics/
  Auth/Idempotency), error-модель `APIError` (RFC 7807 Problem+JSON), health-probes,
  `shared_secret_guard` для вебхука.
- Потребление в шаблоне: `src/bot/platform/backend/` (`BackendClient`/`BackendProvider`),
  `app.py`, `config.py`. Потребление httpkit: `tgbotkit/runner/webhook.py`,
  `platform/webapp/init_data.py`, `testkit`.
- **Эмпирически проверил** (через `uv run python`) ключевой вопрос заказчика — изоляцию N
  клиентов и брейкеров, host-label, backoff. Доказательства ниже.

## Чем httpclient и httpkit отличаются (НЕ дублируют друг друга)

Это **две стороны одной медали**, а не дубль:

- **httpclient = OUTBOUND.** Бот → внешний API (бэкенд). Клиентская устойчивость: retry,
  breaker, исходящий `X-Request-ID`, клиентские спаны (`HTTPXClientInstrumentor`).
- **httpkit = INBOUND.** Внешний мир → бот (вебхук Telegram, webapp). Серверная защита:
  rate-limit, max-body, CORS, security-headers, recovery-from-panic, серверная error-модель,
  health, идемпотентность входящих POST, shared-secret guard.

Они **зеркальны** и осознанно расходятся даже в мелочах: оба определяют `HEADER_REQUEST_ID`/
`request_id`, но httpclient **читает** contextvar (исходящий запрос несёт rid наружу,
`client.py:84-88`), а httpkit **пишет** его (входящий запрос заполняет contextvar,
`middleware/request_id.py`). httpclient намеренно держит свой `reqid.py` (7 LOC), «чтобы не
зависеть от httpkit» (`reqid.py:5-7`) — корректная развязка, не копипаста.

`tgbotkit.WebhookRunner` строит вебхук-приём **на** httpkit (`webhook.py:16,39`), а исходящие
вызовы бэкенда из бота идут через httpclient. Это правильное разделение слоёв.

## Сильные стороны

1. **httpclient — компактный и грамотный.** 317 LOC дают полноценную клиентскую устойчивость:
   exponential backoff с джиттером (`_Wait`, `client.py:46-56`), breaker оборачивает **всю**
   retry-последовательность (открытый breaker фейлит до transport, `client.py:113-119`), span на
   запрос с `record_exception`/`set_status` (`client.py:93-106`), duration-гистограмма с label
   `host`. Чистый, читаемый, без велосипедов (tenacity + purgatory + OTel).

2. **Поведение 4xx vs 5xx — продумано и явно задокументировано.** `client.py:137-147`: только
   `>= 500` поднимает `_RetryableStatus` → ретраится → после исчерпания превращается в
   `HTTPStatusError` (чтобы breaker засчитал фейл). 4xx **возвращается как `Response` без
   исключения** — то есть breaker НЕ открывается на клиентских ошибках (правильно: 404/422 — не
   повод гасить весь апстрим). Это явно описано в `BackendClient` docstring
   (`platform/backend/client.py:5-6`) и корректно разобрано в `_decode` (404→NotFound,
   409→Conflict, прочие 4xx→Unavailable, `client.py:65-70`).

3. **host-label фолбэк работает для относительных path.** Проверено эмпирически:
   `httpx.URL("/users").host == ""` → фолбэк на `base_url.host` (`client.py:91,122`). Значит при
   вызове `BackendClient.get("/users")` метрика всё равно получит осмысленный `host`.

4. **httpkit — оправданный размер, не bloat.** 1346 LOC размазаны по ~20 single-responsibility
   файлам (крупнейший `error.py` — 175 LOC); каждый middleware — отдельная маленькая ASGI-обёртка.
   Это не один распухший модуль, а полноценный production HTTP-сервер (rate-limit, idempotency,
   recovery, Problem+JSON, health). Размер соответствует функциональности; дублирования внутри нет.

5. **OTel-инструментирование идемпотентно.** `_instrument_once` (`client.py:25-33`) и
   `FastAPIInstrumentor.instrument_app` идемпотентны — повторная сборка не падает.

6. **Граница «чистое ядро» соблюдена.** httpx/breaker заперты в `platform/backend`, фичи
   (`profile/gateway.py`, `payments/gateway.py`) видят только `BackendClient` + sentinel-ошибки —
   import-linter-контракт «чистое ядро без httpx/gateway» держится.

## Находки

### [HIGH | flexibility] N клиентов к разным API: класс `Client` изолирован, но DI/Config — нет (KEY)

**Перепроверка тревоги смежного агента — подтверждаю частично, но точнее.**

`BREAKER_NAME = "httpclient"` (`breaker.py:12`) действительно фиксирован, и `_execute` всегда зовёт
`self._breaker.get_breaker(BREAKER_NAME)` (`client.py:117`). **Однако** это НЕ глобальный синглтон:
каждый `Client.__init__` создаёт **собственную** `AsyncCircuitBreakerFactory`
(`new_breaker`, `breaker.py:33` ← `client.py:65`). Эмпирически подтверждено:

```
cfg_a = Config(base_url="https://api-a", breaker=BreakerConfig(failure_threshold=2))
cfg_b = Config(base_url="https://api-b", breaker=BreakerConfig(failure_threshold=99))
a, b = Client(cfg_a, ...), Client(cfg_b, ...)
=> a._breaker is not b._breaker        # разные фабрики
=> brk_a.context.threshold == 2,  brk_b.context.threshold == 99   # независимое состояние
```

**Вывод по сути класса:** поднять N независимых `httpclient.Client` с разными
`base_url`/таймаутами/breaker-порогами на уровне Python — **тривиально** и работает корректно
(независимый breaker-state, независимый httpx-pool). Тревога «всё завязано на синглтон с фикс.
именем» — **преувеличена**: фикс. имя — это ключ ВНУТРИ per-Client фабрики, а не межклиентский
бутылочный горлышко.

**Реальная проблема — на двух смежных уровнях:**

1. **DI-коллизия типов (dishka).** `HttpClientProvider.client` (`module.py:13-24`) и
   `BackendProvider.client` (`platform/backend/provider.py:16`) провайдят ровно ОДИН `Client` /
   ОДИН `BackendClient` по типу в APP-scope. Зарегистрировать второй провайдер той же сигнатуры
   `-> Client` → коллизия (last-wins перезатрёт первый). Для второго API нужно: либо обходной
   `component=`-namespace dishka (поддерживается, но ни один kit его не использует и
   `HttpClientProvider` под это не заточен), либо собственный wrapper-тип (`BackendClient2`) с
   ручной сборкой `httpx.AsyncClient` + `Client` мимо `HttpClientProvider`. Ни одной готовой
   конвенции «N бэкендов» в шаблоне нет — `platform/backend` жёстко single-tenant.

2. **Единый env-namespace `HTTPCLIENT_*`.** `Config` (`config.py:11-17`) и `BreakerConfig`
   (`breaker.py:18-30`) читают **фиксированные** `validation_alias`: `HTTPCLIENT_BASE_URL`,
   `HTTPCLIENT_TIMEOUT`, `HTTPCLIENT_MAX_RETRIES`, `HTTPCLIENT_BREAKER_*`. Для второго клиента из
   env эти алиасы **не параметризуются префиксом** — два `Config()` прочитают один и тот же
   `HTTPCLIENT_BASE_URL`. Чтобы развести, придётся конструировать `Config(base_url=..., ...)`
   руками в коде (env-driven для второго API не работает из коробки).

**Итог severity:** HIGH по гибкости. Механика клиента — гибкая; «последняя миля» (DI-конвенция +
env-неймспейсинг под несколько бэкендов) **отсутствует**. Это не «негибкость by design» в смысле
«нельзя», а «не предусмотрено» — заказчику с несколькими API придётся либо принять конвенцию
samому, либо это PR в kit. Симптом: `platform/backend` спроектирован под ровно один апстрим.

**fix:** в kit — параметризовать `Config`/`BreakerConfig` env-префиксом (фабрика
`new_config(prefix="BACKEND_A_")`) и принимать `breaker_name` в `Client`/`_execute` (вместо
константы); в шаблоне — сделать `BackendProvider` фабрикой по `base_url`-ключу либо документировать
конвенцию «один `platform/backend/<name>/` на апстрим». Оформляется как INFRA-HANDOFF/PR в tgbotkit,
не правка шаблона.

### [MEDIUM | observability] breaker-метрики всех клиентов сливаются под `name="httpclient"`

Следствие фикс. `BREAKER_NAME`. `on_event` эмитит `breaker_transitions`/`breaker_open` с label
`{"name": name}`, где `name` == `"httpclient"` для **любого** клиента (`breaker.py:51-55`,
подтверждено в коде). Если поднять 2+ клиента, их breaker-переходы и gauge `breaker_open`
**неразличимы в метриках** — нельзя сказать, какой именно апстрим «открылся». `request_duration`
при этом различается по label `host` (`client.py:110`), так что латентность развести можно, а
состояние breaker — нет. Низкое по severity пока клиент один (норм), растёт до проблемы ровно в
сценарии «несколько API» из тревоги заказчика.

**fix:** прокинуть `breaker_name` из `Config`/`base_url.host` в label вместо константы.

### [LOW | performance] `RateLimitMiddleware._buckets` растёт без вытеснения (httpkit)

`ratelimit.py:41,55-58`: per-IP token-bucket кладётся в `dict`, который **никогда не чистится**.
При вебхуке Telegram источник IP узок (Telegram-CIDR), так что в реальном профиле бота не
выстрелит; но как generic-серверный middleware это потенциальная медленная утечка памяти под
широким клиентским множеством. Тангенциально к боту, фиксирую для полноты.

**fix:** TTL-вытеснение idle-бакетов или LRU-кап.

### [INFO | correctness] backoff стартует с `attempt_number=1` → первая пауза `2*base`, не `base`

`_Wait.__call__` (`client.py:52-56`): `exp = base * 2**attempt`, а tenacity нумерует попытки с 1 →
первая пауза = `base*2 + jitter` (при `base=0.2` → ~0.4–0.6с), а не `base`. Сходится с заявленной в
комментарии формулой `base * 2**attempt` и не баг (просто чуть агрессивнее, чем «начать с base»);
с дефолтным `max_retries=3` суммарный backoff-бюджет ~0.4+0.8+1.6 ≈ 2.8с разумен. Фиксирую как
нюанс, не дефект. CONF=high.

### [INFO | architecture] httpkit не дублирует httpclient — подтверждено

Проверено: ноль пересечения функциональности. Единственное «совпадение» —
`HEADER_REQUEST_ID`/`request_id` определены в обоих, но с противоположным направлением (read vs
write) и осознанной развязкой зависимостей (`reqid.py:5-7`). Не находка, а подтверждение чистоты
границы.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. httpclient даёт всё для надёжного общения с
бэкендом (retry+breaker+таймауты+трейс), httpkit — production-grade приём вебхука. Поведение 4xx/5xx
корректное, ошибки маппятся в доменные sentinel'ы, фичи не видят httpx. Для типового бота
«один бэкенд» — полностью готово и качественно.

**2. Насколько гибкая система?** Сам `httpclient.Client` — гибкий: N независимых клиентов с разными
`base_url`/политиками/breaker поднимаются тривиально и изолированы по состоянию (проверено
эмпирически). Гибкость теряется на «последней миле» интеграции: DI-конвенция и env-неймспейсинг
заточены под **один** апстрим. httpkit гибок (всё конфигурируемо через `HTTP_*`, middleware
опциональны).

**3. Тревога про один `BackendClient`/`BackendProvider`/единственный `httpclient.Client` —
негибкость или by design?** Это **by design под single-backend, и для нескольких API — реальная
(но не фатальная) негибкость**. Опровергаю самую страшную часть тревоги: `BREAKER_NAME="httpclient"`
и single `HTTPCLIENT_BASE_URL` **не** делают клиент глобальным синглтоном — несколько `Client` с
независимыми breaker'ами работают. Но: (а) `platform/backend` — жёстко single-tenant, второй
апстрим требует своего wrapper-типа из-за dishka-коллизии по типу `Client`; (б) env-конфиг
(`HTTPCLIENT_*`) не префиксуется под второй клиент; (в) breaker-метрики сольются под одним label.
Это не «нельзя», а «не предусмотрено конвенцией» — для бота с несколькими бэкендами нужен либо
аккуратный самодельный wiring, либо аддитивный PR в kit (параметризуемый env-префикс +
`breaker_name` в `Client`). На «нормального» бота с одним бэкендом тревога не влияет.
