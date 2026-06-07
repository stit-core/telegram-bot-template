# Architecture

Слои, гексагон фичи, composition root, жизненный цикл апдейта, state/Redis, граница
tgbotkit↔шаблон. Авторитетный дизайн — `design/ARCHITECTURE.md`; здесь — сжатая выжимка под
текущий код. Path-scoped правила (`.claude/rules/*`) держат terse-инварианты и ссылаются сюда.

## Сквозной принцип: бот — это фронтенд

Бизнес-логика живёт на бэкендах (HTTP API / события NATS). Бот владеет **только своим state**
(FSM/диалоги, кэши, дедуп, identity-link). Вся инфраструктура бота скрыта в `pylibinfra[tgbotkit]`;
шаблон — чистая бизнес-логика.

```
┌─────────────────────────────────┐      ┌──────────────────────────────────────┐
│  pylibinfra (ИНФРАСТРУКТУРА)     │      │  telegram-bot-template (БИЗНЕС)        │
│  tgbotkit: Bot/Dispatcher/      │ ◄─── │  features/<feature>/ (диалоги,        │
│    Storage, middleware-цепочка, │depends│    usecase, gateway, policy, state)   │
│    webhook/polling runner,      │      │  platform/ (identity/backend/dialogs/ │
│    dishka-setup, error-UX,      │      │    webapp — бизнес-общее)             │
│    tg_updates_* метрики,        │      │  locales/ (тексты .ftl)               │
│    i18n/notify/pay механика     │      │  app.py / extensions.py / config.py   │
│  + httpclient/cachekit/natskit  │      │  (~тонкая регистрация)                │
└─────────────────────────────────┘      └──────────────────────────────────────┘
```

«Framework ≠ продукт»: `tgbotkit` знает про `aiogram` (transport), но **не знает** про конкретные
диалоги/команды/флоу. `aiogram`/`aiogram_dialog`/`fluent.runtime` — в extra `pylibinfra[tgbotkit]`;
шаблон зависит **только** от неё (ноль прямых инфра-пинов, см. `pyproject.toml`).

## Анатомия фичи (вертикальный гексагон)

Фича = вертикальный срез одного сценария (bounded context, зеркало go-домена). Эталон полного
гексагона — `features/profile/`:

```
features/profile/
├── __init__.py    фасад: Provider + dialog (что видит app.py/extensions.py)
├── state.py       FSM StatesGroup (из platform) + pydantic-данные диалога  [PURE]
├── dto.py         доменные anti-corruption DTO (не схемы бэкенда)          [PURE]
├── errors.py      sentinel-ошибки фичи                                     [PURE]
├── policy.py      чистые решения → shared.decision.Decision                [PURE]
├── ports.py       Protocol-порты (BackendGateway, cross-feature) — узкие   [PURE]
├── usecase.py     оркестрация: зовёт порты, applies policy; не знает httpx/aiogram
├── gateway.py     реализация порта поверх platform/backend → DTO           [I/O]
├── views.py       результат/ошибка usecase → текст/dict для виджетов       [PURE]
├── dialogs.py     aiogram_dialog Dialog(Window…) — UI как разметка         [PRESENTATION]
├── getters.py     async getter(**kwargs) — ТОЛЬКО данные в окно (usecase)  [PRESENTATION]
├── handlers.py    on_click/on_success — реакции/навигация (usecase)        [PRESENTATION]
├── adapters.py    cross-feature anti-corruption (единственный импорт др. фичи)
└── provider.py    dishka Provider: порт→адаптер, provide usecase
```

Направление зависимостей — стрелка «вниз», к абстракциям (DIP):

```
dialogs → getters | handlers → views → usecase → policy → ports → dto | state
                                          │                  ▲
                                          ▼          gateway ─┘ (структурно удовлетворяет порту)
                                       policy        adapters ─► (cross-feature usecase)
                                       (PURE)
provider.py — единственное место, где порт связывается с конкретной реализацией.
```

**Инварианты** (enforce'ят import-linter + mypy strict):

- **PURE-ядро** (`state`/`dto`/`errors`/`policy`/`ports`) не импортит `aiogram`/`aiogram_dialog`/
  `httpx`/`redis`/свой `gateway`. `state.py` тянет `aiogram.StatesGroup` **только** транзитом
  через `platform/dialogs/states` (архитектура, не утечка).
- **I/O — это usecase**, не метод модели. Чистое правило → `policy.py` (`Decision`).
- **`usecase`** знает только Protocol-порты и policy. **`gateway`** — единственный I/O, поверх
  `platform/backend`. **`views`** — единственное место превращения доменной ошибки в user-текст.
- **Cross-feature** — только через `adapters.py`/`provider.py` (`profile` читает онбординг из
  `start` через порт `OnboardingReader`, объявленный в потребителе).

Сокращённые фичи опускают слои: `start`/`lang` — без `gateway/ports/dto/views` (pure, без
бэкенда); `notifications` — не диалог-гексагон (NATS-router + `deliver_*`). Скелеты файлов —
`design/FEATURE-BLUEPRINT.md`; инварианты — `.claude/rules/feature-architecture.md`.

### Архетипы reference-фич

| Фича | Архетип |
|---|---|
| `start` | pure-онбординг: `LaunchMode.ROOT`, `/start`=`RESET_STACK`, пишет identity/chat-link |
| `profile` | полный гексагон: данные с бэкенда, cross-feature к `start`, ввод+валидация |
| `payments` | оплата Telegram Stars (XTR): dialog-`on_buy` + dispatcher-level pre_checkout/on_paid |
| `lang` | i18n: смена локали, резолвер подхватит из cachekit на следующем рендере |
| `notifications` | NATS→Telegram: `NotificationRouter` + `deliver_*` через `Delivery` (обёртка BgManager) |

## Composition root — тонкий `app.py` + `extensions.py`

`app.py` **не** собирает Dispatcher/middleware/storage/webhook — это в `tgbotkit`. Он собирает
контейнер из провайдеров; `extensions.py` декларирует, что подключить в точки расширения.

```python
# src/bot/app.py — порядок провайдеров значим (last-wins для дефолтов BotProvider)
container = make_async_container(
    # инфра (pylibinfra)
    TelemetryProvider(), CachekitProvider(), HttpClientProvider(), NatsProvider(),
    AiogramProvider(),          # ОБЯЗАТЕЛЕН: REQUEST-контекст (Update/middleware-data)
    BotProvider(),              # даёт ДЕФОЛТЫ (Logger=nop, bundles, ErrorUX, Optional*)
    LogkitProvider(),           # реальный Logger — ПОСЛЕ BotProvider (иначе nop победит)
    AppConfigProvider(),        # все *Config в одном месте (dishka-асимметрия)
    # платформа (бизнес-общее)
    BackendProvider(), IdentityProvider(),
    # фичи (бизнес)
    start.Provider(), profile.Provider(), payments.Provider(), lang.Provider(),
    # точки расширения tgbotkit (override дефолтов BotProvider) — РЕГИСТРИРУЕТСЯ ПОСЛЕДНИМ
    ExtensionProvider(),
)
await container.get(Tracer)              # триггерит telemetry.init (глобальные OTel-providers)
runner = await container.get(BotRunner)  # вся проводка рантайма внутри
await runner.run()
```

`ExtensionProvider` (`extensions.py`) отдаёт kit'у бизнес-точки:

| Бандл/Protocol | Что регистрирует шаблон |
|---|---|
| `RouterBundle` | фиче-диалоги (`Dialog` = `Router`): `start.dialog`, `profile.dialog`, … |
| `CommandBundle` (`CommandSpec`) | команды и dispatcher-level хендлеры: `/start`, `pre_checkout`, `successful_payment`, `/language` |
| `NotifierBundle` | NATS→Telegram подписчики (`notifications.build_router`) |
| `ErrorUX` | тексты/поведение пользовательских ошибок (`AppErrorUX`) |
| `OptionalLocaleResolver` | цепочка резолва локали (`FromCachePref` → `FromUserLanguage`) |
| `OptionalStreamBus` | JetStream-шина для notifications (None при выключенном JetStream → runner пропустит) |

**Асимметрия config:** kit-провайдеры НЕ provide'ят свои `Config` (чтобы не навязывать источник)
— их все собирает `AppConfigProvider` (`config.py`): telemetry/logkit/cachekit/httpclient/natskit/
tgbotkit + `AppConfig`. i18n включается из коробки (`locales_dir` = пакет, дефолт-локаль `ru`).

## Жизненный цикл апдейта (end-to-end) — реализован в tgbotkit

```
Update ─(webhook: httpkit FastAPI валидирует secret_token → dp.feed_update | polling)→
  tgbotkit outer-middleware: request_id("tg-<update_id>") → dedup(SET NX EX, cachekit) →
    throttle → span "tg.update" → log-bind  (навешано и на DIALOG_EVENT_NAME для фоновых)
  → dishka REQUEST-scope → IdentityProvider: Update→BotIdentity (из event_from_user + link)
  → aiogram router → Dialog → getter(**kwargs) ──@inject──► Usecase
        → policy(...) [PURE] → BackendGateway(Protocol) → HttpGateway → BackendClient →
          httpclient → backend (X-Request-ID, retry, breaker, child-span)
        → anti-corruption DTO → views → текст/клавиатура → MessageManager send/edit/delete
  → FSM/dialog state в Redis → span закрыт, RED-метрика, лог с trace_id
```

DI на разных входах: dialog-getter/handler → `@inject` из `dishka.integrations.aiogram_dialog`;
dispatcher-level (`/start`, `pre_checkout`, `successful_payment`) → `@inject` из
`dishka.integrations.aiogram`. `dialog_manager` в dispatcher-хендлере — обычный kwarg из
middleware_data (не `FromDishka`).

## Состояние и Redis

**Один Redis, три потребителя по префиксам** (всё настраивает tgbotkit):

- aiogram `RedisStorage` (`fsm:*`, key-builder `with_destiny=True` — обязателен);
- aiogram_dialog (`aiogd:*`);
- `cachekit` (`cache:*` / `tg:update:*` дедуп / `link:tg:*` / `onboard:tg:*` / `link:chat:*`).

Ключи identity-link шаблона — в `platform/links.py` (общие для identity-резолва, start-онбординга,
notifications-доставки; вынесены, чтобы фичи не импортили друг друга ради формата ключа):

| Ключ | Назначение | Кто пишет |
|---|---|---|
| `link:tg:<id>` | tg_id → backend_user_id (identity-резолв) | при линковке аккаунта |
| `onboard:tg:<id>` | флаг пройденного онбординга | `start.usecase` |
| `link:chat:<ref>` | user_ref → chat_id (куда слать фон) | `start` при онбординге; читает `notifications` |

**Инварианты** (rule `storage-serialization`): в `dialog_data`/`start_data`/`widget_data` —
только JSON-примитивы (`datetime`→ISO, pydantic `model_dump(mode="json")`); несериализуемое падает
в Redis. Dedup — атомарный `SET NX EX` (tgbotkit-middleware). Мультиинстанс (webhook) —
`RedisEventIsolation`. TTL обязательны.

## Граница tgbotkit ↔ шаблон

| В `tgbotkit` (инфра) | В шаблоне (бизнес) |
|---|---|
| `Bot`/`Dispatcher`/`RedisStorage`-фабрики, key-builder, `RedisEventIsolation` | `app.py` список провайдеров; `config.py` значения |
| Outer-middleware (request-id/dedup/throttle/RED+span/recovery) | — |
| Error-handlers `Unknown*`→reset (механика) | тексты/поведение через `ErrorUX` (`AppErrorUX`) |
| `setup_dishka` + `setup_dialogs` (последним) + `emit_startup` | регистрация диалогов через `RouterBundle` |
| `BotRunner.run()`: polling/webhook + graceful shutdown | `runner.run()` вызов в `app.run()` |
| i18n: `I18NFormat`, `install_i18n`, `LocaleResolver`, `FluentTranslator` | `.ftl`-переводы, резолвер-цепочка, фича `lang` |
| notifications: `NotificationRunner`, `Notifier`/`Delivery`, `DeliveryDedup` | `NotificationRouter` + `deliver_*` (event→сообщение) |
| payments: `answer_pre_checkout` (timeout-guard ≤10с), `build_invoice`, `guard_charge` | policy (сверка сумм), usecase (confirm/complete на бэкенде) |
| webapp: `validate_init_data` (HMAC) | `platform/webapp/` — парсинг проверенного user + identity-link |

**Что НЕ делать в шаблоне:** новая инфра-механика (middleware/runtime/error-handler-механика) —
PR в `tgbotkit` через `infra-handoff` (rule `tgbotkit-boundary`), не правка шаблона. См.
[ecosystem.md](ecosystem.md) § INFRA-HANDOFF.

## Non-goals

- **Postgres** — боту не нужен (state в Redis, бизнес-данные на бэкенде).
- **Worker-процесс** — notifications/jobs крутятся в том же процессе через `BotRunner`.
- **Прямые инфра-пины** в `pyproject.toml` — вся инфра транзитивом `pylibinfra[tgbotkit]`.
- **Инфра в шаблоне** — Bot/Dispatcher/middleware/storage не пишутся здесь (директива).
