---
title: "telegram-bot-template — устройство фичи (file-by-file blueprint)"
description: "Конкретные скелеты всех файлов внутри фичи: state/dto/errors/policy/ports/gateway/usecase/views/dialogs/getters/handlers/adapters/provider на примере reference-фичи profile (полный гексагон), плюс минимальная start и особый случай payments."
status: design
lang: ru
based_on: design/_research/14, design/ARCHITECTURE.md
---

# Устройство фичи — file-by-file

Этот документ показывает **как реально выглядят файлы внутри фичи** и как они строятся. Каркас и
ответственность каждого файла зафиксированы в [ARCHITECTURE.md §8](ARCHITECTURE.md) и `_research/14`;
здесь — рабочие скелеты кода.

Фича = **вертикальный срез одного пользовательского сценария** (bounded context), зеркало go-домена.
Внутри — слои с однонаправленными зависимостями. Берём эталон `features/profile/` (просмотр и
редактирование профиля, данные — с бэкенда) — он задействует все слои.

---

## 1. Дерево фичи

```
src/bot/features/profile/
├── __init__.py        # публичный фасад фичи: Provider, dialog (что собирает app.py)
├── state.py           # FSM StatesGroup (из platform) + pydantic-модели данных диалога  [PURE]
├── dto.py             # доменные DTO сценария (anti-corruption, не схемы бэкенда)        [PURE]
├── errors.py          # sentinel-ошибки фичи                                            [PURE]
├── policy.py          # чистые решения «можно ли / что показать» → Decision             [PURE]
├── ports.py           # Protocol-порты (BackendGateway, cross-feature) — узкие          [PURE]
├── usecase.py         # оркестрация: зовёт порты, applies policy. Не знает про httpx/aiogram
├── gateway.py         # реализация BackendGateway поверх platform/backend → DTO         [I/O]
├── views.py           # маппинг результат/ошибка usecase → presentation (текст/dict)    [PURE]
├── dialogs.py         # aiogram_dialog Dialog(Window…) — UI как разметка                [PRESENTATION]
├── getters.py         # async getter(**kwargs) — только данные в окно (дёргает usecase) [PRESENTATION]
├── handlers.py        # on_click / on_success — реакции/навигация (дёргают usecase)     [PRESENTATION]
├── adapters.py        # cross-feature anti-corruption адаптеры (единственный импорт др. фичи)
└── provider.py        # dishka Provider фичи: порт→адаптер, provide usecase
```

### Направление зависимостей (DIP) — стрелка внутрь, к абстракциям

```
        dialogs.py ─┐
        getters.py ─┼─► usecase.py ─► ports.py (Protocol) ◄─ gateway.py ──► platform/backend ──► httpclient
        handlers.py ┘        │                    ▲                                                  │
            │                ▼                    │ (структурно удовлетворяет)                       ▼
         views.py        policy.py            adapters.py ──► (cross-feature usecase)            backend API
            │            (PURE)                    ▲
            └─► dto.py / state.py / errors.py ─────┘
                         (PURE — ничего не импортят из aiogram/httpx/redis)

   provider.py — единственное место, где всё связывается (порт → конкретный адаптер).
```

**Инвариант:** `state/dto/errors/policy/ports` — чистые, **не импортят** `aiogram`/`httpx`/`redis`/
`gateway`. Это enforce'ит `import-linter` ([STACK-AND-TOOLING.md §3](STACK-AND-TOOLING.md)).

---

## 2. Файлы фичи `profile/` — полные скелеты

### `state.py` — FSM-состояния и данные диалога (единственное «своё» у бота)

```python
"""state.py — FSM-состояния и данные диалога фичи profile.

PURE: только описание состояний и pydantic-моделей; никакого I/O.
Всё, что уезжает в FSM storage (dialog_data), обязано быть JSON-сериализуемым.
"""
from pydantic import BaseModel

from bot.platform.dialogs import states

# StatesGroup живёт централизованно (разрыв циклов импорта между диалогами),
# тут — локальный re-export для читаемости фичи.
ProfileSG = states.Profile


class ProfileDialogData(BaseModel):
    """Рабочие данные диалога. Кладутся в manager.dialog_data — только JSON-примитивы.

    Контракт: храним черновик ввода, не доменную сущность (она за gateway).
    datetime/Decimal/ORM сюда класть нельзя — упадёт при сохранении в Redis.
    """

    draft_name: str | None = None

    def has_unsaved(self) -> bool:  # pure-метод (аналог метода агрегата)
        return self.draft_name is not None
```

```python
# bot/platform/dialogs/states.py — ЕДИНЫЙ каталог StatesGroup всех фич
from aiogram.fsm.state import State, StatesGroup


class Start(StatesGroup):
    MENU = State()


class Profile(StatesGroup):
    VIEW = State()
    EDIT_NAME = State()
```

### `dto.py` — доменные DTO сценария (anti-corruption)

```python
"""dto.py — что сценарий принимает/отдаёт. Локальные имена фичи, НЕ схемы бэкенда.

PURE. Это «язык» фичи: gateway мапит сырой JSON бэкенда → сюда, presentation читает отсюда.
Меняется контракт бэкенда — правится только gateway.py, а не вся фича.
"""
from pydantic import BaseModel


class ProfileView(BaseModel):
    name: str
    email: str
    is_premium: bool = False
```

### `errors.py` — sentinel-ошибки фичи

```python
"""errors.py — доменные ошибки фичи profile (sentinel). PURE.

Транспорт (gateway) мапит сетевые сбои в эти типы; presentation (views) — эти типы в текст.
Базовый FeatureError — в shared/, чтобы middleware/ErrorUX узнавал «доменную» ошибку.
"""
from bot.shared.errors import FeatureError


class ProfileError(FeatureError):
    """Базовая ошибка фичи."""


class ProfileNotFound(ProfileError):
    """Бэкенд не знает такого профиля."""


class ProfileForbidden(ProfileError):
    """Политика запретила операцию (роль/доступ)."""


class NameRejected(ProfileError):
    """Имя не прошло валидацию (для on_error ввода)."""
```

### `policy.py` — чистые решения (без I/O)

```python
"""policy.py — чистые решения «можно ли / что показать». PURE: на вход уже загруженные данные.

Никаких портов/сети — только бизнес-правила, которые легко юнит-тестировать.
Возвращает Decision (общий тип из shared) — единообразно во всех фичах.
"""
from bot.shared.decision import Decision, allow, deny

MAX_NAME_LEN = 64


def can_view_profile(role: str) -> Decision:
    if role == "banned":
        return deny("Профиль недоступен")
    return allow()


def validate_name(raw: str) -> Decision:
    name = raw.strip()
    if not name:
        return deny("Имя не может быть пустым")
    if len(name) > MAX_NAME_LEN:
        return deny(f"Не длиннее {MAX_NAME_LEN} символов")
    return allow()
```

### `ports.py` — объявление Protocol-портов (узкие, владелец — потребитель)

```python
"""ports.py — порты фичи (Protocol). PURE.

Сужены до методов ЭТОГО сценария (ISP). Возвращают локальные DTO фичи (anti-corruption).
Реализации (gateway/adapter) объявляются отдельно и связываются в provider.py (DIP).
"""
from typing import Protocol

from bot.features.profile.dto import ProfileView


class BackendGateway(Protocol):
    """Доступ к данным профиля на бэкенде. Узкий — только то, что нужно фиче."""

    async def load_profile(self, backend_user_id: str) -> ProfileView: ...

    async def update_name(self, backend_user_id: str, name: str) -> ProfileView: ...


class OnboardingReader(Protocol):
    """Cross-feature порт: профилю нужен флаг онбординга из фичи start.

    Объявлен ЗДЕСЬ (в потребителе), а не в start — anti-corruption.
    """

    async def is_onboarded(self, tg_id: int) -> bool: ...
```

### `gateway.py` — реализация порта поверх общего клиента бэкенда (I/O)

```python
"""gateway.py — HTTP-реализация BackendGateway. Единственная точка маппинга транспорт→домен.

I/O живёт тут (аналог infra/postgres/repository.go у бэкенда). Структурно удовлетворяет
ports.BackendGateway — связывается в provider.py. httpx скрыт за platform/backend.
"""
from bot.features.profile import errors
from bot.features.profile.dto import ProfileView
from bot.platform.backend.client import BackendClient
from bot.platform.backend.errors import BackendNotFound, BackendUnavailable


class HttpProfileGateway:  # реализует ports.BackendGateway структурно (mypy проверит)
    def __init__(self, http: BackendClient) -> None:
        self._http = http

    async def load_profile(self, backend_user_id: str) -> ProfileView:
        try:
            raw = await self._http.get(f"/v1/users/{backend_user_id}")
        except BackendNotFound as e:
            raise errors.ProfileNotFound(str(e)) from e
        except BackendUnavailable as e:  # breaker open / timeout / 5xx
            raise errors.ProfileError("Сервис временно недоступен") from e
        return ProfileView(name=raw["name"], email=raw["email"], is_premium=raw.get("premium", False))

    async def update_name(self, backend_user_id: str, name: str) -> ProfileView:
        # Idempotency-Key защищает от двойных кликов/ретраев httpclient (см. _research/09)
        raw = await self._http.patch(
            f"/v1/users/{backend_user_id}",
            json={"name": name},
            idempotency_key=f"profile-rename:{backend_user_id}:{name}",
        )
        return ProfileView(name=raw["name"], email=raw["email"], is_premium=raw.get("premium", False))
```

### `usecase.py` — оркестрация сценария (зависит только от Protocol-ов)

```python
"""usecase.py — оркестрация. Знает ТОЛЬКО про порты (Protocol) и policy; не про httpx/aiogram/redis.

Тут собирается сценарий: проверка политики → вызов порта. Это «логика без деталей».
Конструктор принимает порты — их подставляет dishka (provider.py).
"""
import structlog  # WHY: только logkit/structlog, не print/logging (forbidigo-аналог)

from bot.features.profile import errors, policy
from bot.features.profile.dto import ProfileView
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.platform.identity import BotIdentity

_log = structlog.get_logger()


class ProfileUsecase:
    def __init__(self, gateway: BackendGateway, onboarding: OnboardingReader) -> None:
        self._gateway = gateway
        self._onboarding = onboarding

    async def view(self, identity: BotIdentity) -> ProfileView:
        decision = policy.can_view_profile(identity.role)
        if not decision.allowed:
            raise errors.ProfileForbidden(decision.reason)
        return await self._gateway.load_profile(identity.backend_user_id)

    async def rename(self, identity: BotIdentity, raw_name: str) -> ProfileView:
        decision = policy.validate_name(raw_name)
        if not decision.allowed:
            raise errors.NameRejected(decision.reason)
        view = await self._gateway.update_name(identity.backend_user_id, raw_name.strip())
        _log.info("profile.renamed", tg_id=identity.tg_id)  # biz-метрику см. metrics.py (опц.)
        return view

    async def is_first_time(self, tg_id: int) -> bool:
        return not await self._onboarding.is_onboarded(tg_id)
```

### `views.py` — маппинг результата/ошибки usecase → presentation (PURE)

```python
"""views.py — результат/ошибка usecase → данные для виджетов и user-facing текст. PURE.

Аналог delivery/http/view.go (FromEntity + mapErr). Тут — единственное место,
где доменная ошибка превращается в человеческое сообщение.
"""
from bot.features.profile import errors
from bot.features.profile.dto import ProfileView


def to_window(view: ProfileView) -> dict:
    return {
        "name": view.name,
        "email": view.email,
        "badge": "⭐ premium" if view.is_premium else "",
    }


def error_text(err: Exception) -> str:
    match err:
        case errors.ProfileNotFound():
            return "Профиль не найден. Попробуйте /start."
        case errors.ProfileForbidden(reason) | errors.NameRejected(reason):
            return str(reason) or "Действие недоступно."
        case errors.ProfileError():
            return "Сервис временно недоступен, попробуйте позже."
        case _:
            raise err  # не наша доменная ошибка — пусть всплывёт в recovery-middleware tgbotkit
```

### `dialogs.py` — декларация UI (читается как разметка)

```python
"""dialogs.py — aiogram_dialog Dialog/Window. Presentation: ЧТО рендерим и как реагируем.

Один Dialog ⇄ одна StatesGroup. getter даёт данные, on_click/on_success — реакции (handlers.py).
Dialog является Router — отдаётся в tgbotkit как RouterBundle (см. __init__.py).
"""
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import TextInput
from aiogram_dialog.widgets.kbd import Back, Cancel, Row, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from bot.features.profile import getters, handlers
from bot.features.profile.state import ProfileSG

view_window = Window(
    Format("👤 <b>{name}</b> {badge}\n✉️ {email}"),
    Row(
        SwitchTo(Const("✏️ Имя"), id="edit_name", state=ProfileSG.EDIT_NAME),
        Cancel(Const("⬅️ Меню")),
    ),
    state=ProfileSG.VIEW,
    getter=getters.profile_getter,
)

edit_name_window = Window(
    Const("Введите новое имя:"),
    TextInput(
        id="name_input",
        type_factory=str,
        on_success=handlers.on_save_name,
        on_error=handlers.on_name_error,
    ),
    Back(Const("⬅️ Отмена")),
    state=ProfileSG.EDIT_NAME,
)

profile_dialog = Dialog(view_window, edit_name_window)
```

### `getters.py` — только данные в окно (дёргает usecase)

```python
"""getters.py — async getter: ТОЛЬКО чтение данных в окно. Дёргает usecase, не gateway/httpx.

@inject из dishka.integrations.aiogram_dialog: getter — не обычный event-handler диспетчера,
поэтому инъекция идёт через интеграцию aiogram_dialog (а не общий aiogram-middleware).
ОБЯЗАТЕЛЕН **kwargs (getter зовут со всем middleware_data) и дефолты для всех ключей Format.
"""
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from bot.features.profile import views
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity


@inject
async def profile_getter(
    uc: FromDishka[ProfileUsecase],
    identity: FromDishka[BotIdentity],
    **kwargs,
) -> dict:
    view = await uc.view(identity)        # usecase, не gateway
    return views.to_window(view)          # dict для Format-виджетов
```

### `handlers.py` — реакции на ввод/клики (дёргают usecase, ведут навигацию)

```python
"""handlers.py — on_click/on_success/on_error: реакции и навигация. Дёргают usecase (мутации).

Данные берём из manager.* (не из getter). Навигацию ведём manager.switch_to/next/done.
Ошибки usecase превращаем в текст через views.error_text и показываем без падения окна.
"""
from aiogram.types import Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import ManagedTextInput
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from bot.features.profile import errors, views
from bot.features.profile.state import ProfileSG
from bot.features.profile.usecase import ProfileUsecase
from bot.platform.identity import BotIdentity


@inject
async def on_save_name(
    message: Message,
    widget: ManagedTextInput,
    manager: DialogManager,
    value: str,
    *,
    uc: FromDishka[ProfileUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    try:
        await uc.rename(identity, value)
    except errors.ProfileError as e:
        await message.answer(views.error_text(e))
        return
    await manager.switch_to(ProfileSG.VIEW)   # успех → назад к просмотру (перерисует getter)


async def on_name_error(
    message: Message,
    widget: ManagedTextInput,
    manager: DialogManager,
    error: ValueError,
) -> None:
    # сюда попадаем, если type_factory кинул ValueError (для str не бывает; задел под typed-input)
    await message.answer("Некорректный ввод, попробуйте ещё раз.")
```

### `adapters.py` — cross-feature anti-corruption (единственный импорт другой фичи)

```python
"""adapters.py — реализация cross-feature порта. ЕДИНСТВЕННОЕ место, где импортим другую фичу.

import-linter разрешает `features.profile.adapters -> features.start` как исключение.
Адаптер мапит результат чужого usecase в наш порт-контракт (OnboardingReader).
"""
from bot.features.start.usecase import StartUsecase  # допустимо ТОЛЬКО здесь и в provider.py


class OnboardingReaderAdapter:  # реализует ports.OnboardingReader структурно
    def __init__(self, start_uc: StartUsecase) -> None:
        self._start = start_uc

    async def is_onboarded(self, tg_id: int) -> bool:
        status = await self._start.status(tg_id)
        return status.completed
```

### `provider.py` — dishka Provider фичи (связывает порт → адаптер)

```python
"""provider.py — dishka Provider: composition точки фичи. Связывает порты с реализациями (DIP).

Здесь — и только здесь — конкретные классы (gateway/adapter) подставляются под Protocol-порты.
Scope.REQUEST: усечается на каждый Update (как и identity/per-update контекст).
"""
from dishka import Provider, Scope, provide

from bot.features.profile.adapters import OnboardingReaderAdapter
from bot.features.profile.gateway import HttpProfileGateway
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.features.profile.usecase import ProfileUsecase
from bot.features.start.usecase import StartUsecase
from bot.platform.backend.client import BackendClient


class ProfileProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def gateway(self, http: BackendClient) -> BackendGateway:      # порт → http-адаптер
        return HttpProfileGateway(http)

    @provide
    def onboarding(self, start_uc: StartUsecase) -> OnboardingReader:  # cross-feature адаптер
        return OnboardingReaderAdapter(start_uc)

    @provide
    def usecase(self, gw: BackendGateway, onb: OnboardingReader) -> ProfileUsecase:
        return ProfileUsecase(gw, onb)
```

### `__init__.py` — публичный фасад фичи (что видит app.py)

```python
"""__init__.py — фасад фичи: ровно то, что собирает composition root (app.py).

app.py импортит ИЗ фичи только Provider и dialog (Router) — внутренности не торчат наружу.
"""
from bot.features.profile.dialogs import profile_dialog as dialog
from bot.features.profile.provider import ProfileProvider as Provider

__all__ = ["Provider", "dialog"]
```

---

## 3. Минимальная фича `start/` — без бэкенда (pure-сценарий)

Не каждой фиче нужен `gateway`/`ports`. `start` — онбординг: только `state` + `policy` + лёгкий
`usecase` (хранит флаг онбординга в своём state/cachekit). Набор файлов **сокращается**:

```
src/bot/features/start/
├── __init__.py        # Provider, dialog, cmd (хендлер команды /start)
├── state.py           # StatesGroup Start + OnboardingStatus(BaseModel)
├── policy.py          # нужно ли показывать соглашение
├── usecase.py         # status(tg_id) / mark_onboarded(tg_id) — БЕЗ gateway (или cachekit-порт)
├── dialogs.py         # корневой Dialog (LaunchMode.ROOT)
├── getters.py         # данные приветствия (event_from_user.full_name)
├── handlers.py        # on_start_command: manager.start(MENU, mode=RESET_STACK)
└── provider.py        # provide StartUsecase (без cross-feature)
```

Ключевые отличия:

```python
# features/start/dialogs.py — корневой диалог
from aiogram_dialog import Dialog, Window, LaunchMode
from aiogram_dialog.widgets.kbd import Start as StartBtn, Column
from aiogram_dialog.widgets.text import Const, Format
from bot.platform.dialogs import states

menu_window = Window(
    Format("👋 Привет, {username}! Выберите раздел:"),
    Column(
        StartBtn(Const("👤 Профиль"), id="to_profile", state=states.Profile.VIEW),
    ),
    state=states.Start.MENU,
    getter=...,  # getters.menu_getter
)
start_dialog = Dialog(menu_window, launch_mode=LaunchMode.ROOT)
```

```python
# features/start/handlers.py — точка входа /start (dispatcher-level, не диалоговый on_click)
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from dishka import FromDishka
from dishka.integrations.aiogram import inject
from bot.platform.dialogs import states

@inject
async def on_start_command(message: Message, dialog_manager: FromDishka[DialogManager]) -> None:
    # /start ВСЕГДА RESET_STACK (иначе стек копится до лимита 100 → DialogStackOverflow)
    await dialog_manager.start(states.Start.MENU, mode=StartMode.RESET_STACK)
```

`start.__init__` экспортит и `cmd = on_start_command` — его app.py отдаёт в `CommandBundle`.

---

## 4. Особый случай `payments/` — хендлеры уровня диспетчера

Платёжные апдейты (`pre_checkout_query`, `successful_payment`) приходят **не как dialog-callback**, а
как апдейты диспетчера. Поэтому у фичи `payments` в `handlers.py` — два сорта обработчиков, и фасад
экспортит их в `CommandBundle` (механику регистрации и timeout-guard 10с даёт tgbotkit, см.
`_research/16`):

```python
# features/payments/handlers.py (фрагмент)
from aiogram.types import PreCheckoutQuery, Message
from dishka import FromDishka
from dishka.integrations.aiogram import inject
from bot.features.payments.usecase import PaymentsUsecase

@inject
async def on_pre_checkout(q: PreCheckoutQuery, *, uc: FromDishka[PaymentsUsecase]) -> bool:
    # вернуть решение БЫСТРО (дедлайн Telegram 10с); цену проверяем на бэкенде, не из payload
    return await uc.confirm_order(q.invoice_payload, q.total_amount, q.currency)

@inject
async def on_successful_payment(msg: Message, *, uc: FromDishka[PaymentsUsecase]) -> None:
    sp = msg.successful_payment
    # дедуп по telegram_payment_charge_id (at-least-once), подтверждение на бэкенде
    await uc.fulfill(sp.invoice_payload, sp.telegram_payment_charge_id)
```

```python
# features/payments/__init__.py
from bot.features.payments.provider import PaymentsProvider as Provider
from bot.features.payments.dialogs import buy_dialog as dialog
from bot.features.payments.handlers import on_pre_checkout, on_successful_payment

# CommandSpec — описание dispatcher-level хендлера для tgbotkit.CommandBundle
from pylibinfra.tgbotkit import CommandSpec
commands = [
    CommandSpec(on_pre_checkout, kind="pre_checkout"),
    CommandSpec(on_successful_payment, kind="successful_payment"),
]
__all__ = ["Provider", "dialog", "commands"]
```

---

## 5. Общие зависимости, на которые опирается фича

Скелеты `platform/`/`shared/`, к которым обращаются файлы фичи (живут вне фич, переиспользуются):

```python
# bot/shared/decision.py — общий тип решений policy всех фич
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""

def allow() -> Decision: return Decision(True)
def deny(reason: str) -> Decision: return Decision(False, reason)
```

```python
# bot/platform/identity/identity.py — кто пользователь (REQUEST-scope, провайдится из Update)
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class BotIdentity:
    tg_id: int
    backend_user_id: str
    role: str           # "user" | "admin" | "banned" | ...
```

```python
# bot/platform/backend/client.py — общий клиент бэкенда поверх pylibinfra.httpclient
from pylibinfra.httpclient import Client

class BackendClient:
    """Тонкий фасад: добавляет auth-заголовок и доменный маппинг ошибок поверх httpclient.

    X-Request-ID/retry/breaker/OTel уже внутри pylibinfra.httpclient.Client.
    """
    def __init__(self, http: Client) -> None:
        self._http = http

    async def get(self, path: str) -> dict: ...
    async def patch(self, path: str, *, json: dict, idempotency_key: str | None = None) -> dict: ...
```

`BackendClient` (APP-scope) и `BotIdentity` (REQUEST-scope) провайдятся в `platform/*/provider.py`
и инжектятся в фиче-провайдеры — фича не знает про httpx/redis.

---

## 6. Как фича подключается (composition root + tgbotkit)

`app.py` собирает фиче-провайдеры в контейнер и отдаёт `dialog`/`commands` в точки расширения
tgbotkit ([ARCHITECTURE.md §7](ARCHITECTURE.md)):

```python
# src/bot/app.py (фрагмент)
from bot.features import start, profile, payments

container = make_async_container(
    TelemetryProvider(), LogkitProvider(), HttpClientProvider(), CacheProvider(), NatsProvider(),
    TgBotProvider(), AppConfigProvider(cfg),
    BackendProvider(), IdentityProvider(),
    start.Provider(), profile.Provider(), payments.Provider(),   # ← фиче-провайдеры
)
await BotRunner(container).run(
    routers=[start.dialog, profile.dialog, payments.dialog],     # ← RouterBundle
    commands=[start.cmd, *payments.commands],                    # ← CommandBundle (вкл. pre_checkout)
)
```

**Что enforce'ит границы** (см. [STACK-AND-TOOLING.md §3](STACK-AND-TOOLING.md)):

```toml
# importlinter.toml (ключевые контракты)
[[contract]]                              # 1. слоистость ВНУТРИ фичи (DIP)
type = "layers"
layers = ["dialogs | getters | handlers", "views", "usecase", "policy", "ports", "dto | state"]
containers = ["bot.features.profile", "bot.features.start", "bot.features.payments"]

[[contract]]                              # 2. фичи независимы (кроме adapters/provider)
type = "independence"
modules = ["bot.features.start", "bot.features.profile", "bot.features.payments"]
ignore_imports = ["bot.features.*.adapters -> bot.features.*", "bot.features.*.provider -> bot.features.*"]

[[contract]]                              # 3. чистое ядро не знает про инфра-детали
type = "forbidden"
source_modules = ["bot.features.*.usecase", "bot.features.*.policy", "bot.features.*.state", "bot.features.*.dto"]
forbidden_modules = ["httpx", "aiogram", "aiogram_dialog", "redis", "bot.features.*.gateway"]
```

---

## Сухой остаток

- Фича — вертикальный срез; внутри слои с однонаправленными зависимостями (DIP).
- **PURE-ядро** (`state/dto/errors/policy/ports`) не импортит инфру — проверяет import-linter+mypy.
- **`usecase`** оркеструет через Protocol-порты; **`gateway`** — единственный I/O (за `platform/backend`);
  **`provider`** связывает порт→адаптер.
- **Presentation** (`dialogs/getters/handlers/views`): getter=данные, handler=реакции, views=маппинг.
- **Фасад `__init__.py`** отдаёт `Provider` + `dialog` (+ `cmd`/`commands`) — это всё, что видит `app.py`.
- Минимальная фича может опускать `gateway/ports/adapters` (pure, как `start`); платёжная добавляет
  dispatcher-level хендлеры через `CommandBundle`. Вся инфра-механика — в `tgbotkit`.
```
