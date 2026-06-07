# Стресс-тест s-multi-api — три независимых клиента к разным внешним API

## Сценарий

Бот, которому нужны **ТРИ** независимых HTTP-клиента к **РАЗНЫМ** внешним API: CRM-API,
платёжный провайдер, LLM-API. У каждого свой `base_url`, своя авторизация, своя политика
ретраев/таймаутов, свой circuit breaker и свой маппинг ошибок. Прохожу путь «как я это сделаю
шаг за шагом» по реальному коду (`platform/backend/{client,provider,errors}.py`;
`httpclient/{module,client,config,breaker}.py`; `extensions.py`; `app.py`; dishka-проводка) +
эмпирически воспроизвожу dishka-проводку. Это прямая проверка тревоги заказчика №3.

## Что смотрел

- kit: `pylibinfra/src/pylibinfra/httpclient/{client.py,config.py,breaker.py,module.py}` —
  механика клиента, env-namespace, breaker-имя, `HttpClientProvider`.
- kit-контрпример: `pylibinfra/src/pylibinfra/pgkit/module.py` — `ReplicaPool = NewType(...)`
  как рабочий паттерн «N клиентов одного типа в одном контейнере».
- шаблон: `src/bot/platform/backend/{client.py,provider.py,errors.py,__init__.py}`,
  `src/bot/app.py`, `src/bot/config.py`, `src/bot/extensions.py`.
- потребители: `features/profile/{gateway.py,provider.py}`, `features/payments/gateway.py`.
- гайды роста: `.claude/skills/scaffold/references/backend-port.md`,
  `.claude/skills/de-template/references/wiring.md`.
- grep по обоим репо: `NewType` (1 файл — pgkit), `component=` (0 файлов).
- **эмпирически прогнал** (через `uv run python` в pylibinfra): env-коллизию `Config()`,
  рабочесть `NewType`-проводки трёх `Client` в одном dishka-контейнере, last-wins при наивном
  пути. Доказательства ниже.

## Путь «шаг за шагом» — что реально придётся сделать

### Шаг 0. Как устроено сейчас (single-tenant по всей цепочке)

Цепочка разрешается dishka **по типу**, и тип ровно один на каждом звене:

1. `HttpClientProvider.client(cfg: Config) -> Client` (`httpclient/module.py:16-24`) — один
   `Client`, APP-scope, `base_url` из единственного env `HTTPCLIENT_BASE_URL`
   (`config.py:15`), таймаут/ретраи/breaker-пороги — из единственного namespace `HTTPCLIENT_*`.
2. `BackendProvider.client(http: Client, log) -> BackendClient` (`platform/backend/provider.py:16`)
   — один `BackendClient` по типу, поверх того единственного `Client`.
3. `BackendClient.__init__(self, http: Client, log)` (`platform/backend/client.py:21`) — **не**
   принимает ни имени, ни `base_url`: жёстко привязан к одному `Client`.
4. Все gateway фич просят `BackendClient` по типу (`profile/gateway.py:17`, `profile/provider.py:24`,
   `payments/gateway.py:17`). Различения «какой именно бэкенд» нет — он один.

То есть весь слой `platform/backend` + `httpclient` спроектирован под **ровно один апстрим**.

### Шаг 1. Наивная попытка — второй `-> Client` провайдер → тихая ловушка

Первое, что сделает не-питонист (или питонист по аналогии): добавить ещё один провайдер,
отдающий `Client` с другим `base_url`. **Эмпирически воспроизвёл** — это last-wins, без ошибки:

```
class P(Provider):
    @provide async def crm(self) -> Client: ...(base_url=crm)
    @provide async def llm(self) -> Client: ...(base_url=llm)
=> await ct.get(Client).base_url == "https://llm.example"   # crm молча недостижим
```

dishka **не бросает** на старте — просто один провайдер перезатирает другой. CRM-клиент
исчезает беззвучно, бот «работает», но половина запросов уходит не туда. Это худший вид
негибкости — не блок, а тихая порча. Workaround наивного пути нет, нужен другой ключ.

### Шаг 2. Рабочий путь — `NewType`-маркеры (паттерн `ReplicaPool`)

Контрпример из p-store/d-flex: pgkit держит реплику отдельным DI-ключом
`ReplicaPool = NewType("ReplicaPool", object)` (`pgkit/module.py:16,42-58`). Тот же приём
применим к HTTP. **Эмпирически воспроизвёл, что он работает:**

```
CrmClient = NewType("CrmClient", Client); LlmClient = NewType("LlmClient", Client)
class MultiHttpProvider(Provider):
    @provide async def crm(self) -> CrmClient: cfg=Config(base_url="https://crm.example"); ...
    @provide async def llm(self) -> LlmClient: cfg=Config(base_url="https://llm.example", max_retries=0); ...
=> crm.base_url == crm.example, llm.base_url == llm.example   # РАЗНЫЕ инстансы
=> crm._breaker is not llm._breaker                            # независимые breaker'ы
=> crm._cfg.max_retries==3, llm._cfg.max_retries==0           # независимые политики
```

**Вывод по механике:** потолка нет. dishka различает три `Client` одного типа через NewType-ключи;
инстансы, breaker-state и политики независимы. Это и есть ответ на «как dishka различит три Client
одного типа» — **NewType-маркеры (или `component=`), как pgkit.ReplicaPool**.

**Но обратите внимание, какой ценой** это получено в моём прогоне: я написал `MultiHttpProvider`
**целиком вручную**, обойдя `HttpClientProvider`, и **захардкодил `base_url` в коде** (см. шаг 3).
Это не использование точки расширения kit'а — это её замена самописным проводником.

### Шаг 3. Env-конфиг трёх API — из коробки НЕ разводится

Каждому из трёх API нужен свой `base_url`/таймаут/ретраи/breaker-пороги **из env** (прод подаёт
их через vault-agent, `config.py:6`). **Эмпирически воспроизвёл коллизию namespace:**

```
HTTPCLIENT_BASE_URL=https://only-one.example
a, b = Config(), Config()
=> a.base_url == b.base_url == "https://only-one.example"     # оба читают ОДИН env-ключ
HTTPCLIENT_BREAKER_FAILURE_THRESHOLD=7
=> BreakerConfig().failure_threshold == 7 для ОБОИХ           # тот же namespace и у breaker
```

`Config`/`BreakerConfig` читают **фиксированные** `validation_alias` (`config.py:11-15`,
`breaker.py:21-29`): `HTTPCLIENT_BASE_URL`, `HTTPCLIENT_TIMEOUT`, `HTTPCLIENT_BREAKER_*` — без
параметризации префиксом. Развести три API из env **нельзя**: либо все три читают один
`HTTPCLIENT_BASE_URL`, либо `base_url` хардкодится в Python-коде (теряется env-driven конфиг,
ради которого config.py и собран). Для трёх внешних сервисов с авторизацией/URL'ами,
различающимися по средам (dev/stage/prod), хардкод в коде — неприемлемо.

### Шаг 4. Авторизация per-API — точки приложения нет

У трёх API три разных схемы авторизации (Bearer LLM-ключ, API-key CRM, signature платёжного).
Сейчас auth-заголовок негде вставить системно: `Client.request` (`client.py:82-89`) прокидывает
только `X-Request-ID` из contextvar; `BackendClient._request` (`client.py:46-48`) умеет добавить
только `Idempotency-Key`. Статический Bearer можно зашить в `httpx.AsyncClient(headers=...)` при
ручной сборке (шаг 2), но динамический per-request токен/подпись (refresh, HMAC тела) точки
расширения не имеют — это либо ещё один слой обёрток на каждый API, либо PR в kit (auth-hook).

### Шаг 5. Маппинг ошибок per-API — придётся дублировать `platform/backend`

`BackendClient._decode` (`client.py:59-70`) и `errors.py` — **один** набор транспорт-ошибок
(`BackendNotFound`/`BackendConflict`/`BackendUnavailable`) с **зашитой** семантикой статусов
(404→NotFound, 409→Conflict, прочее→Unavailable). Для трёх API с разными контрактами ошибок
(LLM: 429-rate-limit как retryable; платёжный: свои коды; CRM: свои) этого мало. Поскольку
`BackendClient` без параметра, на практике придётся **скопировать `platform/backend/` в три
папки** (`platform/crm/`, `platform/payments_api/`, `platform/llm/`), каждая со своим фасадом,
своим NewType-ключом и своим `errors.py`. Это прямое дублирование слоя — анти-паттерн «не
городить велосипеды» из CLAUDE.md, но обойти его в текущем дизайне нечем.

### Шаг 6. Проводка фич — каждая фича должна попросить «свой» клиент

`features/profile/gateway.py:17` и `features/payments/gateway.py:17` берут `BackendClient` по
типу. С тремя клиентами фича CRM должна получить именно CRM-клиент. Значит и на стороне фич надо
заменить тип-ключ на NewType-маркер (`CrmBackend`/`PaymentsBackend`/`LlmBackend`) в сигнатурах
`gateway.__init__`/`provider.gateway`. Терпимо (локальная правка фичи), но это ещё одна точка,
которую гайд `backend-port.md` не описывает — он знает только один `platform/backend.BackendClient`.

## Объём работы и куда это падает

Чистый сценарий «три API» требует **обоих** уровней правок:

**PR в kit (`httpclient`) — практически обязателен:**
- параметризуемый env-префикс: `Config`/`BreakerConfig` должны уметь читать `CRM_*`/`PAYMENTS_API_*`/
  `LLM_*` (фабрика `new_config(prefix=...)` вместо фиксированных алиасов) — иначе env-driven
  конфиг для трёх API невозможен (шаг 3).
- `breaker_name` параметром в `Client`/`_execute` вместо константы `BREAKER_NAME="httpclient"`
  (`breaker.py:12`, `client.py:117`) — иначе breaker-метрики трёх API сливаются под одним label
  `name="httpclient"` (`breaker.py:51-55`), нельзя сказать, какой апстрим «открылся».
- желательно: `HttpClientProvider`, умеющий отдавать N именованных `Client` (по
  `component`/именованной конфигурации) — иначе ручная сборка `httpx.AsyncClient`+`Client`
  мимо kit'а на каждый API.
- желательно: auth-hook (per-request заголовок) для динамической авторизации (шаг 4).

**Обход в шаблоне — неизбежен даже после PR:**
- NewType-маркеры (`CrmClient`/`PaymentsClient`/`LlmClient`) + провайдер-фабрика на каждый API
  (паттерн `ReplicaPool`). Это **новая локальная DI-механика в `platform/`** — ровно зона,
  которую CLAUDE.md велит выносить PR'ом в kit, но точки расширения под неё нет.
- дублирование `platform/backend/` ×3 (фасад + errors на каждый API), либо параметризация
  `BackendClient` именем/ключом (тоже отсутствует в коде).
- правка сигнатур gateway/provider всех затронутых фич на NewType-ключи.

**Симптом негибкости — реальный, но не архитектурный тупик.** Механика (dishka + класс `Client`)
тянет мульти-клиент: проверено эмпирически, что три `Client` живут в одном контейнере независимо.
Проблема в «последней миле»: в `platform/backend`/`httpclient` паттерн `ReplicaPool`/`NewType`
**не перенесён**, env-namespace монолитный, фасад без параметра, гайды знают один бэкенд. Это
«не предусмотрено», а не «нельзя».

## Расхождение «обещание дока ↔ код»

`de-template/references/wiring.md:20` прямо пишет: «несколько бэкендов = именованные
клиенты/провайдеры в `platform/backend/provider.py`». **Механизма именованных клиентов в коде
нет** (подтверждаю находку d-flex): `BackendProvider` отдаёт один `BackendClient` по типу,
конструктор без имени/`base_url`, `NewType`/`component` в `platform/backend` не применены
(grep: `NewType` — только pgkit, `component=` — нигде). Заказчик, дошедший до де-темплейтизации с
тремя API, прочитает «путь есть» и упрётся в его отсутствие. Это разрыв forward-only-дока
(описывает несуществующую точку расширения). `scaffold/references/backend-port.md` усугубляет:
знает только один `platform/backend.BackendClient`, кейса «второй/третий API» в гайдах нет.

## Сильные стороны (что НЕ придётся форкать)

- Сам класс `httpclient.Client` — **гибкий и не синглтон**: каждый `__init__` создаёт собственную
  breaker-фабрику (`client.py:65`), N клиентов изолированы по breaker-state/httpx-pool/политикам
  (проверено эмпирически — `crm._breaker is not llm._breaker`, независимый `max_retries`).
- dishka **умеет** мульти-ключ — `ReplicaPool` это доказывает в pgkit, и я воспроизвёл то же для
  трёх `Client`. Потолок DI отсутствует.
- Анти-коррупционная граница (`BackendClient` → sentinel-ошибки → gateway) — правильной формы;
  расширяется именно туда, куда нужно (просто сегодня не параметризована).

## Ответ на тревогу заказчика №3 (три клиента к разным API)

**VERDICT: awkward** (не blocked, но и не supported из коробки).

- **«BackendClient захардкожен на один Client?»** — Да. `BackendClient.__init__(http: Client, log)`
  (`client.py:21`) принимает ровно один `Client`, без имени/`base_url`. Для трёх API — дублировать
  фасад или параметризовать (в коде нет ни того, ни другого).
- **«BackendProvider даёт один инстанс по типу?»** — Да. `provider.py:16` отдаёт один `BackendClient`
  по типу `BackendClient`; второй такой же провайдер = last-wins (тихая порча, воспроизведено).
- **«Как dishka различит три Client одного типа?»** — Через `NewType`-маркеры (паттерн
  `pgkit.ReplicaPool`) или dishka-`component`. **Работает** (воспроизведено), но в шаблоне/ките
  для HTTP **не применено** — заказчику писать самому.
- **«Форкать platform/backend, дублировать на каждый API, или дописывать httpclient?»** — **Всё
  три сразу.** Дублировать `platform/backend` ×3 (или параметризовать — кода нет), писать
  NewType-проводку в шаблоне руками, и PR в `httpclient` за env-префикс + `breaker_name` (без него
  три API не сконфигурировать из env и не различить в метриках). Это **и** «PR в kit», **и** «обход
  в шаблоне» — не одно из двух.
- **Объём:** для одного-двух API с хардкод-конфигом — несколько часов самописной проводки. Для
  трёх API с env-driven конфигом, per-API breaker-метриками и динамической авторизацией —
  аддитивный PR в kit (env-префикс + breaker_name + опц. auth-hook + N-client provider) плюс
  reference-паттерн именованных бэкендов в шаблоне. Не фатально, но это **проектная работа**, а не
  «дописал провайдер».
