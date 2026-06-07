---
title: "telegram-bot-template — архитектурный дизайн"
description: "Авторитетный дизайн: вся инфраструктура бота скрыта в pylibinfra (новый kit tgbotkit), шаблон — чистая бизнес-логика на aiogram_dialog поверх dishka-провайдеров. Двух-репозиторная модель, анатомия фичи, точки расширения, composition root, жизненный цикл, встроенные подсистемы (i18n/notifications/payments/webapp)."
status: design
lang: ru
based_on: design/_research/01..18
---

# Архитектурный дизайн telegram-bot-template

Авторитетный синтез 18 исследовательских артефактов (`design/_research/01..18`). Детализация по
каждой теме — в соответствующем артефакте (ссылки по тексту).

---

## 1. Видение и сквозной принцип

**Бот — это фронтенд.** Вся бизнес-логика живёт на бэкендах (HTTP API / события NATS). Единственное,
чем владеет бот, — **его собственный state** (FSM/диалоги, кэши, дедуп, identity-link).

**Вся инфраструктура бота скрыта в `pylibinfra`.** Это директива, определяющая всю структуру:
bootstrap бота, `Dispatcher`, проводка `RedisStorage`, цепочка middleware, приём вебхуков,
dishka-интеграция, observability апдейтов, error-handlers, graceful shutdown и generic-механика
i18n/notifications/payments/webapp — **не в шаблоне**, а в новом kit'е `tgbotkit` библиотеки
`pylibinfra` (см. `_research/18`). В **шаблоне остаётся только бизнес-логика**: фичи (диалоги,
usecase, gateway, policy, state), контент (тексты/переводы), маппинг событий → действия и тонкая
регистрация в рантайм kit'а.

```
┌─────────────────────────────────────┐        ┌──────────────────────────────────────┐
│  pylibinfra  (ИНФРАСТРУКТУРА)        │        │  telegram-bot-template (БИЗНЕС)       │
│                                     │        │                                      │
│  tgbotkit:  Bot/Dispatcher/Storage,   │  ◄───  │  features/<feature>/  (диалоги,      │
│           middleware-цепочка,       │ depends│       usecase, gateway, policy, state)│
│           webhook/polling runner,   │        │  locales/  (тексты .ftl)             │
│           dishka-setup, error-UX,   │        │  app.py (~30 строк): провайдеры →    │
│           tg_updates_* метрики,     │        │       BotRunner; точки расширения    │
│           i18n/notify/pay механика  │        │  config.py (значения конфига)        │
│  + httpkit/cachekit/natskit/...     │        │                                      │
└─────────────────────────────────────┘        └──────────────────────────────────────┘
```

Принцип «framework ≠ продукт»: `tgbotkit` знает про `aiogram` (transport/framework), но **не знает**
про конкретные диалоги/команды/бизнес-флоу — ровно как `httpkit` знает FastAPI, `pgkit` — asyncpg.
`aiogram`/`aiogram_dialog` входят в **опциональную extra** `pylibinfra[tgbotkit]`, чтобы небот-консьюмеры
их не тянули.

**Зеркалим `go-backend-template`:** доменно-гексагональная раскладка фичи, `.claude`-система,
`make`-гейты, Conventional Commits, forward-only, INFRA-HANDOFF.

---

## 2. Двух-репозиторная модель и зависимость

Дизайн охватывает **два репозитория**:

| Репо | Что | Изменение |
|---|---|---|
| **`pylibinfra`** | новый kit `tgbotkit` (+ доработка `httpkit`) — вся инфра бота | **2 PR** (см. §16, оформляются как INFRA-HANDOFF) |
| **`telegram-bot-template`** | чистая бизнес-логика, зависит от `pylibinfra[tgbotkit]` | сам шаблон |

Шаблон **не может быть собран до** мержа `tgbotkit` (либо временно несёт инфру локально и выносит её
PR'ом — см. ROADMAP). Зависимость: `pylibinfra[tgbotkit] @ git+…@vX.Y.Z`.

Граница «что в kit / что в шаблоне» — полностью в `_research/18`; для подсистем — `_research/15`
(webhook→httpkit), `_research/16` (payments/webapp), `_research/17` (i18n/notifications).

---

## 3. Технологический стек

Версии и источники — `_research/07`. Ядро: `aiogram` 3.28.2, `aiogram-dialog` 2.6.0, `dishka`
1.10.1, `pydantic-settings` 2.14, Redis 8.x, `fluent.runtime` (i18n). **Весь инфра-слой
(dishka/redis/httpx/otel/fastapi/structlog) приходит транзитивом `pylibinfra`;** `aiogram`/
`aiogram-dialog`/`fluent.runtime` живут в extra `pylibinfra[tgbotkit]`. Шаблон в своём `pyproject.toml`
зависит только от `pylibinfra[tgbotkit]` — **ноль прямых инфра-пинов**.

---

## 4. `tgbotkit` — что скрыто в pylibinfra

Полная поверхность — `_research/18`. `tgbotkit` (имя по конвенции `*kit`; `bot`=aiogram-bootstrap, не
Telegram-продукт) предоставляет один `BotProvider` + `tgbotkit.Config` (`BOT_*`) и прячет:

| Скрытая инфра | Деталь |
|---|---|
| `Bot`-фабрика | session, `DefaultBotProperties(parse_mode)`, ретраи `TelegramRetryAfter` |
| `Dispatcher`-фабрика | сборка, `resolve_used_update_types()` для `allowed_updates` |
| `RedisStorage`-проводка | key-builder `with_bot_id`+`with_destiny`, `RedisEventIsolation` поверх cachekit-redis |
| **Outer-middleware-цепочка** | request-id bind → dedup `update_id` (cachekit) → throttle → RED+span → recovery; навешивается и на `DIALOG_EVENT_NAME` |
| Error-handlers | `UnknownIntent`/`UnknownState`/`OutdatedIntent` → reset (UX через `ErrorUX`-Protocol шаблона) |
| dishka-интеграция | `setup_dishka(container, dp)` (REQUEST-scope на Update) |
| aiogram_dialog | `setup_dialogs(dp, events_isolation=…)` — **последним**; `BgManagerFactory` для notifications |
| **Runner** | `BotRunner.run()`: polling **и** webhook (webhook поверх httpkit из `_research/15`) |
| Graceful shutdown | drain in-flight → `container.close()` → `bot.session.close()` |
| Observability апдейта | `tg_updates_total{type,result}`, `tg_update_duration_seconds`, span `tg.update` |
| Generic-механика подсистем | i18n (`I18NFormat`+middleware), notifications (`NotificationRunner`+`Notifier`), payments (pre_checkout helper+dedup), webapp (initData-валидатор) — §11–12 |

**Точки расширения** (идиома dishka — type-wrapper-бандлы, как `timerkit.list[PeriodicJob]`),
которыми шаблон подключает бизнес-логику, не трогая инфру:

| Бандл/Protocol | Что регистрирует шаблон |
|---|---|
| `RouterBundle` | фиче-роутеры/диалоги (`aiogram_dialog.Dialog` = `Router`) |
| `CommandBundle` / `CommandSpec` | команды и dispatcher-level хендлеры (вкл. `pre_checkout`/`successful_payment`) |
| `NotifierBundle` / `Notifier` | NATS→Telegram подписчики (получают `BgManagerFactory`) |
| `list[PeriodicJob]` | периодические джобы (через существующий `timerkit`) |
| `ErrorUX` (Protocol) | тексты/поведение пользовательских ошибок |
| `I18nConfig` / каталоги | подключение `.ftl`-каталогов шаблона |

---

## 5. Карта китов pylibinfra (что бот потребляет)

`tgbotkit` сам стоит на других китах (kit-on-kit — прецедент `bruteforcekit`→`pgkit`). API китов —
`_research/04`/`05`.

| Кит | Роль | Статус |
|---|---|---|
| **`tgbotkit`** (новый) | вся bot-инфра (см. §4) | **всегда** |
| `telemetry` | OTel bootstrap | всегда (через tgbotkit) |
| `logkit` | structlog + trace-id + PII-redact | всегда |
| `config` | env + Vault (BOT_TOKEN/secret) | всегда |
| `httpclient` | **backend-gateway** (retry/breaker/OTel/X-Request-ID) | всегда |
| `cachekit` | Redis: FSM-коннект, dedup, кэши, identity-link | всегда |
| `httpkit` | FastAPI: health + приём вебхуков (consume'ится `tgbotkit`) | webhook + health |
| `natskit` | подписка на события бэкенда → push | встроено (notifications) |
| `bizmetric` | `biz_tg_*` / `tg_*` метрики | всегда |
| `timerkit` | джобы | опц. |
| `storagekit` | медиа в S3 | опц. |
| `authnkit` | identity-link JWT (HS256) | опц. |
| `clockkit`/`flagkit` | тест-время / фичефлаги | dev/опц. |
| `pgkit` | Postgres | **не нужен** |

---

## 6. Каноническая раскладка репозитория (тонкий шаблон)

Шаблон ужимается: вся проводка рантайма уехала в `tgbotkit`. Полностью — `_research/18` (§3) и
`_research/14` (анатомия фичи). `platform/` теряет `webhook/`, `middlewares/`, bootstrap; остаются
бизнес-блоки.

```
telegram-bot-template/
├── pyproject.toml              # dependency: pylibinfra[tgbotkit] @ git+…  (ноль прямых инфра-пинов)
├── importlinter.toml           # контракты границ фич/слоёв
├── Makefile · Dockerfile · .gitea/workflows/ci.yml · compose.dev.yml
├── src/bot/
│   ├── __main__.py             # ~3 строки: asyncio.run(app.run())
│   ├── app.py                  # ~30 строк: список kit+фиче-провайдеров → BotRunner.run (§7)
│   ├── config.py               # AppConfig (значения) + AppConfigProvider (все *Config, asymmetry note)
│   ├── platform/               # ОБЩЕЕ бизнес-проектное (без инфра-проводки!)
│   │   ├── identity/           # Update → BotIdentity (REQUEST-scope провайдер)
│   │   ├── backend/            # общий клиент бэкенда поверх httpclient + общие транспорт-ошибки
│   │   ├── dialogs/            # states.py (ВСЕ StatesGroup), common.py (виджеты), errors.py (ErrorUX)
│   │   └── webapp/             # валидатор initData + identity-link (бизнес-glue; см. §12)
│   ├── features/               # ФИЧИ (вертикальные срезы)
│   │   ├── start/              # reference: онбординг (pure)
│   │   ├── profile/            # reference: данные из бэкенда (полный гексагон + cross-feature)
│   │   ├── payments/           # reference: оплата (Stars/XTR) — бизнес поверх tgbotkit-механики
│   │   └── notifications/      # reference: deliver_* (event→сообщение/диалог) + register(router)
│   ├── locales/                # .ftl-переводы (контент i18n): <lang>/<feature>.ftl
│   └── shared/                 # pure-утилиты (decision.py, result.py, types.py)
├── tests/                      # unit/ flows/ backend/ integration/ e2e/ _fakes/
├── docs/                       # reference/ + stack/ (8+ артефактов)
└── .claude/                    # skills/ rules/ agents/ + CLAUDE.md + plans/roadmap.md
```

---

## 7. Composition root — тонкий `app.py`

`app.py` больше **не** собирает Dispatcher/middleware/storage/webhook — это в `tgbotkit`. Он лишь
собирает контейнер из провайдеров и отдаёт точки расширения в `BotRunner`. Полный псевдокод —
`_research/18` (§3).

```python
# src/bot/app.py — ВСЯ инфра в tgbotkit; здесь только список провайдеров и расширений
from dishka import make_async_container
from pylibinfra.tgbotkit import BotProvider, BotRunner, RouterBundle, CommandBundle, NotifierBundle
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpclient import HttpClientProvider
from pylibinfra.cachekit import CacheProvider
from pylibinfra.natskit import NatsProvider

from bot.config import AppConfig, AppConfigProvider, load_config
from bot.platform.backend.provider import BackendProvider
from bot.platform.identity.provider import IdentityProvider
from bot.features import start, profile, payments, notifications   # каждая отдаёт Provider + bundle

async def run() -> None:
    cfg = load_config()
    container = make_async_container(
        # ── инфра (pylibinfra) ──
        TelemetryProvider(), LogkitProvider(), HttpClientProvider(),
        CacheProvider(), NatsProvider(), BotProvider(),
        AppConfigProvider(cfg),                      # все *Config (asymmetry note)
        # ── платформа (бизнес-общее) ──
        BackendProvider(), IdentityProvider(),
        # ── фичи (бизнес) ──
        start.Provider(), profile.Provider(), payments.Provider(), notifications.Provider(),
    )
    # точки расширения: шаблон ДЕКЛАРИРУЕТ, что подключить; рантайм — в tgbotkit
    await BotRunner(container).run(
        routers=[start.dialog, profile.dialog, payments.dialog],   # RouterBundle
        commands=[start.cmd, payments.pre_checkout, payments.on_paid],  # CommandBundle
        notifiers=[notifications.on_order_paid],                   # NotifierBundle
        # i18n-каталоги, jobs, ErrorUX — тоже сюда/через провайдеры
    )
    # BotRunner внутри: storage+isolation, middleware-цепочка, setup_dishka, setup_dialogs (последним),
    # emit_startup (smoke), polling|webhook, graceful shutdown (container.close()).
```

### Жизненный цикл апдейта (end-to-end) — реализован в tgbotkit

```
Update ─(webhook: httpkit FastAPI валидирует secret_token → dp.feed_update | polling)→
  tgbotkit outer-middleware: request_id("tg-<id>") → dedup(SET NX EX) → throttle → span"tg.update" → log-bind
  → dishka REQUEST-scope → IdentityProvider: Update→BotIdentity
  → aiogram router → Dialog → getter(**kwargs) ──FromDishka──► Usecase
        → policy(...) [чистое] → BackendGateway(Protocol) → HttpGateway → httpclient → backend (X-Request-ID, retry, breaker, child-span)
        → anti-corruption DTO → views → текст/клавиатура → MessageManager send/edit/delete
  → FSM/dialog state в Redis → span закрыт, RED-метрика, лог с trace_id
```

Корреляция/идемпотентность/деградация — `_research/09`; observability — `_research/11`;
state/Redis — `_research/10`.

---

## 8. Анатомия фичи (бизнес-логика шаблона)

Не меняется директивой — это и есть «чистая бизнес-логика». Фича = вертикальный срез (зеркало
go-домена). Полная таблица и примеры — `_research/14`.

| Файл | Ответственность | ⟂ Go-слой |
|---|---|---|
| `state.py` | FSM `StatesGroup` (из `platform/dialogs/states.py`) + pydantic-модели данных диалога. **Только JSON-примитивы.** | `entity.go` |
| `dto.py` | Доменные anti-corruption DTO | `dto.go` |
| `errors.py` | Sentinel-ошибки фичи | `errors.go` |
| `policy.py` | Чистые решения → `Decision` | `policy.go` |
| `ports.py` | `Protocol`-порты (`BackendGateway`, cross-feature) — узкие | интерфейсы usecase |
| `usecase.py` | Оркестрация: зовёт порты, applies policy, span. Не знает про httpx/aiogram. | `usecase.go` |
| `gateway.py` | Реализация порта поверх `platform/backend` → DTO | `infra/.../repository.go` |
| `dialogs.py`/`getters.py`/`handlers.py`/`views.py` | Presentation: Window/Dialog; getter=данные; handler=реакции; views=маппинг | `delivery/http/*` |
| `provider.py`/`adapters.py` | dishka Provider фичи (порт→адаптер, регистрация) + cross-feature адаптеры | `module/*` |

**SOLID:** DIP (presentation→usecase→Protocol→gateway), ISP (узкие порты), SRP (getter=данные,
handler=реакции, policy=решения, usecase=оркестрация). Cross-feature только через `adapters.py`.
Enforce: **import-linter** (3 контракта) + **mypy strict** (Protocol структурно). Инвариант «I/O в
usecase, чистое в policy/state».

---

## 9. Интеграция с бэкендом

Полностью — `_research/09`. **Порт `BackendGateway` (`Protocol`)** в фиче, узкий, возвращает
локальные DTO; адаптер `HttpXxxGateway` поверх `platform/backend` (он — поверх `httpclient`).
Маппинг ошибок (`BreakerOpenError`/5xx → `BackendUnavailable`; 404/409 → sentinel фичи) → user-текст
в `views.py`. Корреляция `X-Request-ID` (ставит tgbotkit-middleware, прокидывает httpclient).
Идемпотентность мутаций — `Idempotency-Key` (sha256 payload). Несколько бэкендов = именованные
`Client`/провайдеры. Деградация при open-breaker → заранее заданный UX-текст.

---

## 10. Состояние и данные

Полностью — `_research/10`. **Один Redis, три потребителя по префиксам:** aiogram `RedisStorage`
(`fsm:*`, key-builder `with_destiny=True` — обязателен), aiogram_dialog (`aiogd:*`), `cachekit`
(`cache:*`/`tg:update:*`/`link:*`). Все эти ключи и проводку настраивает **tgbotkit**. Сериализация —
только JSON-примитивы (pydantic `model_dump(mode="json")`); тесты на `JsonMemoryStorage` ловят
несериализуемое. Dedup — атомарный `SET NX EX` в tgbotkit-middleware. Мультиинстанс —
`RedisEventIsolation` (tgbotkit). TTL обязательны (контексты пишут `{}`, не удаляются).

---

## 11. Встроенные подсистемы: i18n и notifications

Решение архитектора: в скелете из коробки. Граница generic↔контент — `_research/17`.

**i18n** (движок — `fluent.runtime`, `.ftl`):
- **в tgbotkit:** `I18NFormat`-виджет (рендерит ключ перевода), `I18nMiddleware`/`install_i18n` (на
  `message`+`callback_query`+`DIALOG_EVENT_NAME`), `LocaleResolver` (Protocol: `FromUserLanguage`/
  `FromCachePref`/`ChainResolver`), `CatalogLoader`, `LocalePrefStore`. Движок за Protocol
  `Translator` — подменяем без правки виджета.
- **в шаблоне:** переводы `locales/<lang>/<feature>.ftl`, список ключей (префикс=фича), дефолт-локаль,
  фича смены языка.

**notifications** (транспорт — **JetStream durable + explicit ack**, core — для эфемерных):
- **в tgbotkit:** `NotificationRunner` (long-running + `drain()` на shutdown), `NotificationRouter.on(
  subject, handler)` (точка расширения), `Notifier` — единственная обёртка над `BgManager`, где
  закрыты ВСЕ грабли (`load=True`, пустой стек→safe, EDIT не гарантирован, throttle, фон вне
  middleware → `request_id`/локаль руками), `DeliveryDedup`, метрики доставки.
- **в шаблоне:** `features/notifications/` — какие subject'ы, `deliver_*` (event→сообщение/диалог),
  `register(router)`, заполнение `link:acct→chat_id` при онбординге.

---

## 12. Встроенные подсистемы: payments и WebApp

Граница — `_research/16`.

**Платежи** (фиат + **Telegram Stars/XTR**: `currency="XTR"`, пустой `provider_token`):
- **в tgbotkit:** регистрация dispatcher-level `pre_checkout`/`successful_payment` как точка
  расширения; helper `answer_pre_checkout(query, decide, deadline≈9s)` с timeout-гардом (**дедлайн
  10 сек**, fail-closed); дедуп платёжных апдейтов + `guard_charge` по `charge_id` (cachekit);
  метрики `tg_payments_*`; опц. `build_invoice` (XTR-нормализация).
- **в шаблоне:** `features/payments/` — `policy` (pure-сверка сумм), `usecase` (проверка/
  подтверждение на бэкенде через gateway), `gateway` (confirm/refund, `Idempotency-Key=charge_id`),
  `dialogs` (кнопка «Купить» → `send_invoice`, `invoice_payload=order_id`), `handlers`
  (dialog-level `on_buy` + dispatcher-level pre_checkout/on_paid).
- **Подводные камни:** pre_checkout/successful_payment — апдейты диспетчера, не dialog-callback
  (связь через `invoice_payload`); цену/состав брать **с бэкенда**, не из callback; дедуп
  `successful_payment` (at-least-once) по `telegram_payment_charge_id`.

**WebApp/Mini App:**
- **валидатор initData** (HMAC-SHA256, секрет=`HMAC(key="WebAppData", data=bot_token)`, проверка
  хеша + `auth_date ≤ 5 мин`, constant-time) — pure-функция; живёт в `platform/webapp/init_data.py`
  (Telegram-vendor-специфика; кандидат на подъём в `tgbotkit.webapp`).
- **в шаблоне:** `platform/webapp/` — валидатор + identity-link + gateway-передача проверенных данных
  на бэкенд. Канал доставки: путь B (свой бэкенд-эндпоинт + initData) — основной; путь A
  (`web_app_data` через `sendData`) — только из reply-keyboard-кнопки.

---

## 13. Observability и эксплуатация

Полностью — `_research/11`. Метрики апдейтов (`tg_updates_*`, span `tg.update`), отправки
(`tg_api_calls_*`, `tg_flood_wait_total`), доставки notifications, payments (`tg_payments_*`) —
эмитит **tgbotkit**; бизнес-метрики `biz_tg_*` (команды/конверсии) — через `bizmetric` в usecase.
Backend RED — бесплатно из `http_client_*`. Трейс: корень `tg.update` (tgbotkit-middleware),
`X-Request-ID=tg-<update_id>` сшивает вызов бэкенда. Логи — `logkit` (PII-redact). Health — httpkit
`/health`+`/ready` (+ probes). Resource-attrs: только `service.name/version/environment`;
`tenant`/`service.namespace` **не ставить** (корп otel-collector). Graceful shutdown (tgbotkit):
drain → `container.close()` (telemetry-flush) → `bot.session.close()`.

---

## 14. Конфиг, секреты, деплой

Полностью — `_research/12`. Поверхность конфига (pydantic-settings): `BOT_TOKEN` (Vault), `BOT_MODE`
(polling|webhook), `WEBHOOK_*` (secret — Vault), `REDIS_URL`, `NATS_URL`, OTLP, `BACKEND_*_BASE_URL`,
tenant/env/service. На проде секреты рендерит vault-agent в env. **Dockerfile** — multi-stage uv,
приватный `pylibinfra[tgbotkit] @ git+ssh` через `--mount=type=ssh`, один образ. **Топологии:** polling —
1 инстанс; webhook — за ingress/TLS, ≥2 инстанса (RedisEventIsolation в tgbotkit), single-flight
`set_webhook`. Release — STOP на image-in-registry; handoff = `vault kv patch …bot_tag` + infra
`make ship`.

---

## 15. Тестирование

Полностью — `_research/13`. Пирамида: **unit** (policy/маппинг/валидаторы) → **flows**
(`BotClient`+`MockMessageManager`+`JsonMemoryStorage`, gateway замокан) → **backend** (`respx` +
`FakeBackendGateway`) → **integration** (testkit redis/nats). Мокаем **порт, не транспорт**;
локаторы кнопок по `callback_data`. Gate: `make check` = ruff+mypy+import-linter+pytest(`not
integration`); CI гоняет integration. RED-first. tgbotkit тестируется отдельно в pylibinfra
(`/add-kit` + testkit-сабпакет).

---

## 16. Зависимость от pylibinfra: два PR (INFRA-HANDOFF)

Шаблон требует доработки `pylibinfra` (оформляется как INFRA-HANDOFF, `_research/18` §INFRA-HANDOFF):

- **PR-A — новый kit `tgbotkit`** (через skill `/add-kit`): `BotProvider`+`Config`, middleware-цепочка,
  runner (polling/webhook), error-handlers, observability, точки расширения (`RouterBundle`/
  `CommandBundle`/`NotifierBundle`/`ErrorUX`/i18n/notifications/payments-механика), testkit-сабпакет;
  **новая extra `pylibinfra[tgbotkit]`** с `aiogram`/`aiogram-dialog`/`fluent.runtime` (новые deps —
  согласовать; обоснование «framework не продукт»).
- **PR-B — доработка `httpkit`** (`_research/15` §4): `build_app(lifespan=)`, `Server(autostart=)` +
  `dishka_lifespan(container)`, `shared_secret_guard()` (generic 403-guard для входящих вебхуков).
  `tgbotkit.runner.webhook` его консьюмит.

Оба аддитивные/back-compat. До их мержа шаблон может временно нести инфру локально и вынести её PR'ом
(ROADMAP, Фаза -1).

---

## 17. Что осталось обсудить

Сведено в [ROADMAP.md](ROADMAP.md). Главное: имя kit'а (`tgbotkit` vs `tgkit`), согласование новых
deps в `pylibinfra` (aiogram/aiogram_dialog/fluent в extra), глубина reference-фич, последовательность
PR-A/PR-B vs локальный bootstrap на старте.
