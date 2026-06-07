# 14 · Каноническая слоистая архитектура и SOLID-интерфейсы шаблона бота (зона N)

> **Спинной хребет дизайна.** Этот артефакт фиксирует каноническую раскладку репозитория
> Telegram-бота (aiogram 3.28 + aiogram_dialog 2.6 + dishka 1.10 + pylibinfra), слои фичи как
> зеркало доменно-гексагональной раскладки `go-backend-template`, набор SOLID-интерфейсов
> (Protocol-портов), composition root на dishka и enforcement границ.
>
> Источники-якоря: `design/_research/01` (раскладка go-template + «маппинг на бот» §6),
> `design/_research/06` (dishka↔aiogram DI), `design/_research/07` (стек/версии),
> `go-backend-template/.claude/rules/domain-architecture.md`,
> `aiogram-dialog-docs/guides/{building-a-template,architecture}.md`.
>
> **Сквозной принцип.** Бот — «фронтенд»: бизнес-логика на бэкендах (через API/события), у бота
> своё — **только его state** (FSM/диалоги). Инвариант go-template **«I/O — в usecase, чистое — в
> policy/state»** переносится 1:1; «домен данных» заменяется на «фича-сценарий», а `delivery` —
> на aiogram-входы (роутеры/диалоги). `infra/` бота — это **исходящий клиент к бэкенду**, не
> хранилище.

---

## 1. Каноническая раскладка репозитория (src-layout)

`src/bot/` — три яруса как `cmd/api` go-template (`infra` / `platform` / `features`), плюс
`shared/` (pure-утилиты, аналог `pkg/`). Каждая фича — изолированный пакет-«bounded context»
в `src/bot/features/<feature>/` (зеркало `internal/domain/<name>/`).

```
telegram-bot-template/
├── pyproject.toml                  # deps: aiogram, aiogram-dialog (новые) + pylibinfra-транзитив
├── importlinter.toml               # контракты границ (аналог depguard) — §5
├── .env.example
├── src/
│   └── bot/
│       ├── __init__.py
│       ├── __main__.py             # точка входа `python -m bot`: asyncio.run(run())
│       ├── app.py                  # COMPOSITION ROOT: контейнер, Dispatcher, polling/webhook, lifecycle — §4
│       ├── config.py               # AppConfig (pydantic-settings) + AppConfigProvider (все *Config kit'ов)
│       ├── logging.py              # bootstrap логирования до DI (structlog/pylibinfra logkit)
│       │
│       ├── platform/               # специфично проекту, но не фича (зеркало internal/platform/)
│       │   ├── __init__.py
│       │   ├── identity/           # кто пользователь Telegram → принципал/роль с бэкенда
│       │   │   ├── identity.py     #   BotIdentity(tg_id, backend_user_id, role, token); resolve из Update
│       │   │   └── provider.py     #   REQUEST-scope провайдер: Update → BotIdentity (аналог authgate)
│       │   ├── backend/            # ОБЩИЙ клиент бэкенда поверх pylibinfra.httpclient
│       │   │   ├── client.py       #   BackendHttpClient: базовый http (retry/CB/OTel/X-Request-ID, auth-header)
│       │   │   ├── errors.py       #   транспортные ошибки (BackendUnavailable, BackendUnauthorized, ...)
│       │   │   └── provider.py     #   APP-scope провайдер общего http-клиента бэкенда
│       │   ├── dialogs/            # общая presentation-инфра диалогов
│       │   │   ├── states.py       #   ⚠ ВСЕ StatesGroup в одном модуле (разрыв циклов импорта) — §2.1
│       │   │   ├── common.py       #   переиспользуемые виджеты (кнопка «В меню», About)
│       │   │   ├── errors.py       #   on_unknown_intent / on_unknown_state (обязательны для прода)
│       │   │   └── registry.py     #   сбор dialog_router из роутеров всех фич + порядок include
│       │   └── i18n/               # (опц.) middleware локализации + I18NFormat-виджет
│       │
│       ├── features/               # ФИЧИ (зеркало internal/domain/)
│       │   ├── __init__.py
│       │   ├── start/              # reference-фича: онбординг (см. §6)
│       │   │   └── ...             #   полный набор файлов — §2
│       │   └── profile/            # reference-фича: тянет данные из бэкенда (см. §6)
│       │       └── ...
│       │
│       └── shared/                 # pure-утилиты бота вне фич (аналог pkg/)
│           ├── decision.py         #   Decision(allowed, reason) — аналог pkg/policy
│           ├── result.py           #   мелкие result/option-хелперы
│           └── types.py            #   общие type-алиасы (TgUserId, BackendUserId, ...)
└── tests/
    ├── conftest.py                 # фикстуры dp/client/message_manager (JsonMemoryStorage)
    ├── unit/                       # юниты policy/usecase через моки портов
    │   └── features/<feature>/
    └── flows/                      # BotClient-потоки диалогов (e2e без Telegram)
        └── <feature>/
```

**Решения по раскладке (и отличия от «дефолтного» aiogram_dialog-каркаса из building-a-template):**

- **Вертикальные срезы (фичи), а не горизонтальные слои.** Дефолтный каркас режет по слоям
  (`dialogs/ services/ middlewares/`). Мы режем по **фичам** (как go-домены), внутри фичи —
  слои. Это и даёт зеркало гексагона и cross-feature-границу.
- **`platform/dialogs/states.py` — единый каталог состояний** всех фич (требование
  aiogram_dialog: диалог A стартует диалог B → импорт `states`, а не друг друга, иначе цикл —
  building-a-template §1). Это **единственное** нарушение «всё своё в фиче»: state-группы
  собраны централизованно. Сами Window/getter/handler остаются в фиче.
- **`platform/backend/` — общий http-клиент** (не на фичу): аналог общего kit'а; фиче-специфичный
  gateway оборачивает его за узким портом (anti-corruption).
- **`shared/decision.py`** — аналог `pkg/policy.Decision`, чтобы policy всех фич возвращали один тип.

---

## 2. Слои фичи — зеркало go-домена на язык бота

Полный набор файлов фичи `src/bot/features/<feature>/` и точная ответственность каждого.

### 2.0. Таблица «файл фичи → ответственность → ⟂ go-слой»

| Файл фичи | Ответственность | I/O? | ⟂ Go-слой | Примечание |
|---|---|---|---|---|
| `state.py` | **FSM `StatesGroup`** (импортируются из `platform/dialogs/states.py`) + pydantic/dataclass-модели `DialogData`/`StartData`/`Result`. Pure-валидация state. **Единственное «своё» у бота.** | **Чистый** | `entity.go` | ⚠ только JSON-примитивы в данных, что уедут в FSM storage; `datetime`→ISO-строки |
| `dto.py` | Input/Output use-case (доменные, не транспортные): что сценарий принимает и отдаёт во view. **Локальные anti-corruption DTO**, не сырые JSON-схемы бэкенда. | Чистый | `dto.go` | напр. `ProfileView`, `LoadProfileResult` |
| `errors.py` | Sentinel-ошибки фичи: `class ProfileNotFound(FeatureError)`. Маппинг на user-facing текст — в `views.py` (аналог `mapErr`). | Чистый | `errors.go` | базовый `FeatureError` в `shared/` |
| `policy.py` | Чистые решения «можно ли / что показать»: видимость кнопок по роли, доступность сценария, валидация ввода. Возвращает `Decision`. **Без I/O.** | **Чистый** | `policy.go` | вход — уже загруженные данные, не порт |
| `ports.py` | **Объявление портов** (`typing.Protocol`): `BackendGateway` к бэкенду + cross-feature-порты. **Сужены** до методов сценария; возвращают **локальные DTO фичи**. Владелец контракта — потребитель. | Чистый | интерфейсы в `usecase.go` | вынесено в отдельный файл для читаемости (в go — внутри `usecase.go`) |
| `usecase.py` | **Оркестрация сценария**: зовёт порты (`BackendGateway`, cross-feature), применяет `policy`, ведёт OTel-span. **Не знает про httpx/aiogram/redis.** Зависимости — только Protocol'ы. | I/O-оркестратор (сам чист от деталей) | `usecase.go` | конструктор принимает порты; `bizmetric`-счётчики тут |
| `gateway.py` | **Реализация порта `BackendGateway`** поверх `platform/backend/BackendHttpClient`: мапит фиче-эндпоинты бэкенда → локальные DTO. Аналог `infra/postgres/repository.go`. | I/O (сеть) | `infra/postgres/repository.go` | у бота `infra` = исходящий клиент |
| `dialogs.py` | aiogram_dialog `Dialog(Window(...))` — декларация UI, **читается как разметка**. `LaunchMode`, getter/handler привязаны тут. | I/O (presentation) | `delivery/http/handler.go` (вход) | один `Dialog` ⇄ одна `StatesGroup` |
| `getters.py` | `async def getter(**kwargs) -> dict` — **только данные в окно**. Дёргает `usecase` (через `FromDishka`), мапит результат во view-dict. **Только чтение.** | I/O (через usecase) | `delivery/http/view.go` (+вход) | обязателен `**kwargs`, дефолты, no reserved keys |
| `handlers.py` | `on_click`/`on_success`/`on_process_result` — **реакции на ввод**. Дёргают `usecase` (мутация), управляют навигацией (`manager.next/done/start`). | I/O (через usecase) | `delivery/http/handler.go` (вход) | данные берут из `manager.*`, не из getter |
| `views.py` | Маппинг результата/ошибки usecase → текст/клавиатура/getter-dict; маппинг sentinel-ошибок → user-facing сообщения. | Чистый | `delivery/http/view.go` | аналог `FromEntity` + `mapErr` |
| `provider.py` | **dishka `Provider` фичи**: связывает порт→адаптер (`BackendGateway`→`gateway.py`), provide `usecase`, регистрирует роутер/диалог. | Композиция | `module/module.go` | §3, §4 |
| `adapters.py` | **Cross-feature адаптеры**: оборачивают usecase другой фичи под порт-Protocol этой фичи (anti-corruption). Единственное место, где разрешён импорт другой фичи. | Композиция | `module/adapters.go` | §3 (depguard-граница) |
| `events.py` (опц.) | Payload-типы, если бот публикует в outbox/NATS через pylibinfra. | Чистый | `events.go` | редко нужно боту |
| `metrics.py` (опц.) | `pylibinfra.bizmetric`-счётчики (`biz_<feature>_*`), no-op-safe без DI. | I/O (OTel) | `metrics.go` | можно держать в `usecase.py` |
| `tests/` (рядом или в `tests/unit/`) | Юниты `policy`/`usecase` через **моки портов** (бэкенд не дёргается); flow-тесты на `BotClient`. | — | `*_test.go`, `mocks/` | мокаем порт, не httpx-клиент |

**Главный сдвиг семантики (из 01 §6.1).** У бэкенда «домен» владеет данными (Postgres-агрегат);
у бота «фича» владеет только **состоянием диалога** (`state.py`), а данные — за портом
`BackendGateway`. Pure-ядро бота (`state.py` + `policy.py`) тоньше, но принцип «I/O в usecase,
чистое в policy/state» сохраняется.

### 2.1. Нюанс `state.py` ↔ единый `states.py`

aiogram_dialog требует все `StatesGroup` в одном модуле (`platform/dialogs/states.py`), иначе
циклы импорта между диалогами. Канон шаблона:

```python
# src/bot/platform/dialogs/states.py — ЕДИНЫЙ каталог StatesGroup всех фич
from aiogram.fsm.state import State, StatesGroup

class Start(StatesGroup):           # фича start
    WELCOME = State()
    AGREEMENT = State()

class Profile(StatesGroup):         # фича profile
    VIEW = State()
    EDIT_NAME = State()
```

```python
# src/bot/features/profile/state.py — pydantic-модели данных диалога (pure, JSON-safe)
from pydantic import BaseModel
from bot.platform.dialogs import states

ProfileStates = states.Profile      # re-export для локальной читаемости

class ProfileDialogData(BaseModel):
    draft_name: str | None = None   # только JSON-примитивы; datetime → ISO-строки
    def is_dirty(self) -> bool:     # pure-метод (аналог метода агрегата)
        return self.draft_name is not None
```

---

## 3. Принципы SOLID применительно к боту

| Принцип | Как реализуется в шаблоне |
|---|---|
| **DIP** | `getters/handlers → usecase → port(Protocol) → gateway`. Presentation зависит от `usecase`-абстракции (через `FromDishka`), usecase — от `BackendGateway`-**Protocol** (объявлен в `ports.py`), а concrete `gateway.py`/httpx-клиент **никто из ядра не импортит**. Стрелка зависимости направлена внутрь. |
| **ISP** | Порты **узкие**: `BackendGateway` фичи `profile` имеет только `load_profile`/`update_name`, а не весь API бэкенда. Cross-feature-порт сужен до нужных 1–3 методов (как `auth.UserReader` с `GetByID`, не весь `Repository`). Не копировать «на вырост». |
| **SRP** | Один файл — одна ответственность: `getters.py` **только данные**, `handlers.py` **только реакции/навигация**, `policy.py` **только решения**, `usecase.py` **только оркестрация**, `gateway.py` **только транспорт→DTO**, `views.py` **только маппинг в presentation**. |
| **OCP** | Новая фича = новый пакет + новый `Provider` в composition root; существующие не трогаются. Подмена бэкенда/storage = другой адаптер за тем же портом. |
| **LSP** | Любая реализация `BackendGateway` (боевая `gateway.py`, тестовый fake, mock) взаимозаменяема — usecase не различает. |

**Cross-feature — только через порты + адаптеры (аналог depguard в go):**

1. Фиче A нужны данные фичи B → **порт объявляется в A** (`A/ports.py`), сужен, возвращает
   **локальный DTO A** (не тип B — anti-corruption).
2. **Адаптер — в `A/adapters.py`** — единственное место, где разрешён импорт `bot.features.B`
   (исключение в import-linter). Оборачивает `B.usecase` и мапит его результат в DTO A.
3. Адаптер регистрируется в `A/provider.py` как фабрика порта.
4. **Предпочтительно:** общий ресурс (общий «профиль юзера», identity) выносится в
   `platform/`, тогда cross-feature-связь вообще не нужна.

**Пример Protocol-порта (узкий, anti-corruption):**

```python
# src/bot/features/profile/ports.py
from typing import Protocol
from bot.features.profile.dto import ProfileView   # ЛОКАЛЬНЫЙ DTO, не схема бэкенда

class BackendGateway(Protocol):
    """Порт к бэкенду. Владелец контракта — фича profile. Сужен до её сценария."""
    async def load_profile(self, backend_user_id: str) -> ProfileView: ...
    async def update_name(self, backend_user_id: str, name: str) -> ProfileView: ...

# cross-feature: profile показывает онбординг-флаг из фичи start
class OnboardingReader(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...
```

```python
# src/bot/features/profile/usecase.py — оркестрация, знает только про Protocol'ы
import structlog
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.features.profile.dto import ProfileView
from bot.features.profile import policy, errors
from bot.platform.identity import BotIdentity

class ProfileUsecase:
    def __init__(self, gateway: BackendGateway, onboarding: OnboardingReader) -> None:
        self._gateway = gateway
        self._onboarding = onboarding
        self._log = structlog.get_logger().bind(feature="profile")

    async def view(self, identity: BotIdentity) -> ProfileView:
        # span/telemetry оборачивает pylibinfra; policy — чистое решение
        decision = policy.can_view_profile(identity.role)
        if not decision.allowed:
            raise errors.ProfileForbidden(decision.reason)
        return await self._gateway.load_profile(identity.backend_user_id)
```

```python
# src/bot/features/profile/gateway.py — реализация порта (I/O)
from bot.platform.backend.client import BackendHttpClient
from bot.features.profile.dto import ProfileView

class HttpProfileGateway:                       # удовлетворяет BackendGateway структурно
    def __init__(self, http: BackendHttpClient) -> None:
        self._http = http
    async def load_profile(self, backend_user_id: str) -> ProfileView:
        raw = await self._http.get(f"/v1/users/{backend_user_id}")   # httpx за фасадом
        return ProfileView(name=raw["name"], email=raw["email"])     # anti-corruption mapping
    async def update_name(self, backend_user_id: str, name: str) -> ProfileView:
        raw = await self._http.patch(f"/v1/users/{backend_user_id}", json={"name": name})
        return ProfileView(name=raw["name"], email=raw["email"])
```

**Provider фичи (связывает порт→адаптер, регистрирует presentation):**

```python
# src/bot/features/profile/provider.py
from aiogram import Router
from dishka import Provider, Scope, provide
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.features.profile.gateway import HttpProfileGateway
from bot.features.profile.usecase import ProfileUsecase
from bot.features.profile.adapters import OnboardingReaderAdapter
from bot.features.profile.dialogs import profile_dialog
from bot.platform.backend.client import BackendHttpClient
from bot.features.start.usecase import StartUsecase   # импорт другой фичи — ТОЛЬКО в adapters/provider

class ProfileProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, http: BackendHttpClient) -> BackendGateway:    # порт → адаптер
        return HttpProfileGateway(http)

    @provide
    def onboarding(self, start_uc: StartUsecase) -> OnboardingReader:  # cross-feature адаптер
        return OnboardingReaderAdapter(start_uc)

    @provide
    def usecase(self, gw: BackendGateway, onb: OnboardingReader) -> ProfileUsecase:
        return ProfileUsecase(gw, onb)

# роутер/диалог фичи — собирается в platform/dialogs/registry.py (аналог fx.Invoke(Register))
def router() -> Router:
    return profile_dialog          # Dialog является Router
```

```python
# src/bot/features/profile/adapters.py — cross-feature anti-corruption
from bot.features.start.usecase import StartUsecase

class OnboardingReaderAdapter:                  # удовлетворяет profile.OnboardingReader
    def __init__(self, start_uc: StartUsecase) -> None:
        self._start = start_uc
    async def is_onboarded(self, tg_id: int) -> bool:
        return (await self._start.status(tg_id)).completed   # мапит результат фичи start
```

**getter/handler — presentation-вход, дёргает usecase (из 06 §3.2):**

```python
# src/bot/features/profile/getters.py
from dishka.integrations.aiogram_dialog import FromDishka, inject
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity
from bot.features.profile import views

@inject
async def profile_getter(
    uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity], **kwargs
) -> dict:
    view = await uc.view(identity)              # usecase, не gateway/httpx
    return views.to_window(view)                # маппинг в dict для виджетов

# src/bot/features/profile/handlers.py
from dishka.integrations.aiogram_dialog import FromDishka, inject
from bot.platform.dialogs import states

@inject
async def on_save_name(event, widget, manager, uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity]):
    name = manager.find("name_input").get_value()
    await uc.rename(identity, name)
    await manager.switch_to(states.Profile.VIEW)
```

---

## 4. Composition root (`app.py`) — псевдокод

Три яруса провайдеров (зеркало `infraModules`/`platformModules`/`domainModules` из
`cmd/api/main.go`) + `AppConfigProvider` (asymmetry note: kit'ы не provide'ят свой Config) +
`AiogramProvider`. Регистрация роутеров/диалогов = аналог `fx.Invoke(http.Register)`.
`setup_dishka(dp)` навешивает REQUEST-scope на каждый Update.

```python
# src/bot/app.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, ExceptionTypeFilter
from aiogram.fsm.storage.redis import RedisStorage, RedisEventIsolation
from aiogram_dialog import setup_dialogs
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
from dishka import make_async_container
from dishka.integrations.aiogram import AiogramProvider, setup_dishka

# pylibinfra kit-провайдеры (ярус infra) — из 06 §1
from pylibinfra.telemetry import TelemetryProvider
from pylibinfra.logkit import LogkitProvider
from pylibinfra.httpclient import HttpClientProvider
from pylibinfra.cachekit import CacheProvider          # Redis-фасад для FSM/изоляции
from pylibinfra.natskit import NatsProvider            # опц. (push-уведомления)

from bot.config import AppConfig, AppConfigProvider, load_config
from bot.platform.backend.provider import BackendProvider
from bot.platform.identity.provider import IdentityProvider
from bot.platform.dialogs.registry import build_dialog_router    # собирает роутеры фич
from bot.platform.dialogs.errors import on_unknown_intent, on_unknown_state
from bot.features.start.provider import StartProvider
from bot.features.profile.provider import ProfileProvider
from bot.features.start.handlers import on_start_command


def build_container(cfg: AppConfig):
    return make_async_container(
        # ── ярус infra (pylibinfra) ────────────────────────────────
        TelemetryProvider(), LogkitProvider(), HttpClientProvider(),
        CacheProvider(), NatsProvider(),
        AppConfigProvider(cfg),          # ВСЕ *Config (asymmetry note, 06 §1)
        # ── ярус platform ──────────────────────────────────────────
        BackendProvider(),               # общий http-клиент бэкенда (APP-scope)
        IdentityProvider(),              # Update → BotIdentity (REQUEST-scope)
        # ── ярус features ──────────────────────────────────────────
        StartProvider(),
        ProfileProvider(),
        # ── интеграция ─────────────────────────────────────────────
        AiogramProvider(),               # доступ к TelegramObject / middleware_data (06 §2)
    )


def build_dispatcher(cfg: AppConfig, container) -> tuple[Dispatcher, RedisStorage]:
    storage = RedisStorage.from_url(cfg.redis_dsn)
    dp = Dispatcher(storage=storage)

    # 1) команды-входы (не-диалоговые хендлеры)
    dp.message.register(on_start_command, CommandStart())
    # 2) error-handlers на UnknownIntent/UnknownState (ОБЯЗАТЕЛЬНЫ для прода — building-a-template §5)
    dp.errors.register(on_unknown_intent, ExceptionTypeFilter(UnknownIntent))
    dp.errors.register(on_unknown_state, ExceptionTypeFilter(UnknownState))
    # 3) роутеры/диалоги всех фич (аналог fx.Invoke(Register))
    dp.include_router(build_dialog_router())
    # 4) dishka REQUEST-scope на каждый Update
    setup_dishka(container=container, router=dp)
    # 5) aiogram_dialog — СТРОГО ПОСЛЕДНИМ, после всех include_router
    isolation = RedisEventIsolation(redis=storage.redis)     # распределённая изоляция (≥2 воркера)
    dp["bg_factory"] = setup_dialogs(dp, events_isolation=isolation)
    return dp, storage


async def run() -> None:
    cfg = load_config()
    container = build_container(cfg)
    dp, storage = build_dispatcher(cfg, container)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # smoke-инвариант: ловит коллизии StatesGroup/незарег. диалоги на старте (building-a-template §4)
    await dp.emit_startup()

    if cfg.mode == "webhook":
        await run_webhook(cfg, bot, dp, container)     # FastAPI/httpkit + feed_update (06 §4.2)
    else:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            # graceful shutdown: (1) стоп polling → (2) закрыть контейнер → (3) сессии (06 §5)
            await container.close()     # отрабатывают yield-cleanup'ы (http aclose, telemetry flush)
            await bot.session.close()
            await storage.close()
```

**Lifecycle-решения (из 06 §4–§5):**

- **Polling** (dev/простой прод): `try/finally` вокруг `start_polling`; в `finally` —
  `container.close()` (обязателен — иначе нет telemetry-flush и http-aclose), затем
  `bot.session.close()`. Альтернатива: `dp.shutdown.register(container.close)`.
- **Webhook**: FastAPI/httpkit принимает POST → валидирует секрет → `dp.feed_update(bot, update)`
  (отрабатывает aiogram-middleware dishka). Контейнер закрывается в FastAPI-lifespan после
  `yield`. ⚠ gap httpkit `build_app()` ↔ dishka-lifespan — решается на уровне шаблона (06 §4.2).
- **Фоновые задачи** (push-уведомления, NATS-подписки) — через `pylibinfra.timerkit`/lifespan,
  навешивать middleware и на `DIALOG_EVENT_NAME` (`aiogd_update`), иначе фоновые рендеры не
  увидят DI (architecture.md §6).

---

## 5. Enforcement — как держать границы

| Инструмент | Что enforce'ит | Конфиг |
|---|---|---|
| **import-linter** (аналог depguard) | Границы фич и слоёв: фичи не импортят друг друга (кроме `adapters.py`/`provider.py`); ядро (`state/policy/usecase/dto`) не импортит presentation/gateway/aiogram; presentation не импортит httpx/gateway напрямую. | `importlinter.toml` |
| **ruff** | Lint + format; запрет `print`/прямого `logging` (как forbidigo → только pylibinfra logkit); `TID252` (relative imports), `**kwargs` в getter, ASCII widget-id. | `pyproject.toml [tool.ruff]` |
| **mypy strict** | Строгая типизация; **Protocol-порты** проверяются структурно (адаптер обязан удовлетворять порту); запрет `Any` на границах. | `pyproject.toml [tool.mypy] strict=true` |
| **.claude/rules/** | bot-rules (зеркало go-rules): `feature-architecture.md`, `tests-pipeline.md`, `events-and-messaging.md`, `infra-impact.md` (INFRA-HANDOFF при изменении env/секрета/cross-service-subject). | `.claude/rules/*.md` |
| **CI smoke** | `await dp.emit_startup()` в тесте — ловит коллизии StatesGroup и незарегистрированные диалоги. | `tests/flows/test_startup.py` |

**Контракты import-linter (ключевые):**

```toml
# importlinter.toml
[[contract]]                                   # 1. слоистость ВНУТРИ фичи (DIP)
name = "feature layers"
type = "layers"
layers = ["dialogs | getters | handlers", "views", "usecase", "policy", "ports", "dto | state"]
containers = ["bot.features.start", "bot.features.profile"]

[[contract]]                                   # 2. фичи независимы (depguard-аналог)
name = "features are independent"
type = "independence"
modules = ["bot.features.start", "bot.features.profile"]
# исключение: cross-feature только через adapters/provider
ignore_imports = [
  "bot.features.*.adapters -> bot.features.*",
  "bot.features.*.provider -> bot.features.*",
]

[[contract]]                                   # 3. ядро не знает про инфра-детали (DIP)
name = "pure core forbids infra"
type = "forbidden"
source_modules = ["bot.features.*.usecase", "bot.features.*.policy", "bot.features.*.state"]
forbidden_modules = ["httpx", "aiogram", "aiogram_dialog", "redis", "bot.features.*.gateway"]
```

**Граница с pylibinfra (зеркало architecture.md §73–80, из 01 §6.4):** переиспользуемое/инфра
(http-обвязка, RequestID-проброс, FSM-storage-фасад, OTel) → **кандидат в pylibinfra**, не в бот.
Нет примитива → PR в pylibinfra + backlog. Бот импортит kit-фасады (`httpclient.Client`,
`cachekit.Cache`), не httpx/redis напрямую.

---

## 6. Reference-фичи-примеры (как `auth/user` в go — образец, потом удаляется через de-template)

Две фичи покрывают оба архетипа: pure-онбординг и фича-с-бэкендом + cross-feature.

### 6.1. `features/start/` — онбординг (минимальный pure-сценарий)

- **Демонстрирует:** `state.py` (FSM-флоу WELCOME→AGREEMENT), `policy.py` (нужно ли показывать
  соглашение), `dialogs.py` с `LaunchMode.ROOT` + `StartMode.RESET_STACK` на `/start`,
  getter без бэкенда (`event_from_user.full_name`), минимальный `usecase` со статусом онбординга.
- **Роль:** корневой диалог (главное меню), точка входа `on_start_command`, источник
  cross-feature-данных (`OnboardingReader`) для `profile`.
- **Чему учит:** «фича без бэкенда» — `infra`/`gateway` может отсутствовать; ядро = `state` + `policy`.

### 6.2. `features/profile/` — профиль из бэкенда (полный гексагон + cross-feature)

- **Демонстрирует:** полный набор файлов — `ports.py` (`BackendGateway` + `OnboardingReader`),
  `gateway.py` (httpx за фасадом → DTO), `usecase.py` (оркестрация + policy + span),
  `dialogs.py`/`getters.py`/`handlers.py`/`views.py` (VIEW + EDIT_NAME с `TextInput`),
  `adapters.py` (cross-feature adapter к `start`), `provider.py` (порт→адаптер wiring).
- **Роль:** эталон «бот=фронтенд, данные за портом к бэкенду» + anti-corruption DTO +
  cross-feature через порт+адаптер.
- **Чему учит:** весь канон ports/adapters, DIP, ISP, тестирование через мок `BackendGateway`.

**de-template-аналог.** Разовое развёртывание форка: rewrite-import-path, prune reference-фич
(`start`/`profile`), doc-driven wiring composition root, scaffold-skill `feature`/`dialog`/`port`
для добавления новых фич с фиксированным «ритмом» (подтвердить вход → изменение → gen/моки →
тесты RED→GREEN → check → Conventional Commit).

---

## Сухой остаток

1. **Вертикальные срезы-фичи** (`features/<feature>/`) с внутренней слоистостью — зеркало
   go-доменов; три яруса `infra/platform/features` в composition root.
2. **Каноническая раскладка фичи:** `state · dto · errors · policy · ports · usecase · gateway ·
   dialogs · getters · handlers · views · provider · adapters` (+ опц. `events`/`metrics`).
3. **Инвариант «I/O в usecase, чистое в policy/state»** переносится 1:1; `entity→state`,
   `infra→gateway` (исходящий клиент к бэкенду), `delivery→dialogs/getters/handlers`.
4. **Ports/adapters через dishka с anti-corruption DTO:** порт-`Protocol` в потребителе
   (`ports.py`), адаптер в `provider.py`/`adapters.py`, локальные DTO; cross-feature только так.
5. **SOLID:** DIP (presentation→usecase→Protocol→gateway), ISP (узкие порты), SRP (getter=данные,
   handler=реакции, policy=решения, usecase=оркестрация), enforce'ится import-linter+mypy strict.
6. **Composition root** на dishka: `AppConfigProvider` (asymmetry note) + kit-провайдеры +
   фиче-провайдеры + `AiogramProvider`, `setup_dishka(dp)`, `setup_dialogs` последним,
   polling/webhook, обязательный `container.close()`.
7. **Reference-фичи `start` (pure-онбординг) + `profile` (полный гексагон + cross-feature)** —
   образец, удаляемый через de-template.
