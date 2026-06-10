# scaffold › feature — новый вертикальный срез

Создаёт новую фичу (bounded context одного пользовательского сценария) по конвенции шаблона. Эталоны полного гексагона — `features/profile/`, `booking/`, `payments/`; полные скелеты файлов — `design/FEATURE-BLUEPRINT.md`. Соответствует rule `feature-architecture` (открой, если не загружено).

**Gate (soft).** Флоу диалога проектируется **до** кода (`/dialog-deep-dive`): окна, переходы, getter-данные, состояния виджетов. Если флоу ещё не зафиксирован — сначала dialog-deep-dive, потом сюда. Жёсткого хука нет — дисциплина.

## Когда применять

- «Добавь фичу `referral`», «новый раздел бота со своим меню/данными».
- «Scaffold a `subscription` feature».

## Когда НЕ применять

- Новый диалог/окно **внутри** существующей фичи → `references/dialog.md` / `references/window.md`.
- Только поход на бэкенд из существующей фичи → `references/backend-port.md`.

## 1. Подтвердить вход

- Имя фичи `snake_case` (`referral`, `subscription`).
- Полный гексагон (есть бэкенд-данные/мутации) или **сокращённый** (pure-сценарий без бэкенда, как `start`/`lang`)?
- Сколько окон, какие переходы, какие данные в каждое окно (из dialog-deep-dive)?
- Есть dispatcher-level вход (команда `/foo`)? Cross-feature зависимости?
- Какой pkg-клиент даёт данные: метод существующего (`ProfileAPI`/`BookingAPI`/`PaymentsAPI`) или новый модуль в `pkg/http_client/internal/` (`references/backend-port.md` §A)?

## 2. Дерево фичи

Полный гексагон (`profile`-образец):

```
src/bot/features/<name>/
├── __init__.py        # фасад: Provider, dialog (+ cmd_spec/command_specs)
├── state.py           # re-export StatesGroup + pydantic-данные диалога  [PURE, нижний слой]
├── dto.py             # доменные DTO / результаты шагов wizard'а (опц.)  [PURE]
├── errors.py          # sentinel-ошибки (от shared.errors.FeatureError)   [PURE]
├── policy.py          # чистые решения → shared.decision.Decision         [PURE]
├── ports.py           # Protocol-порты, типизированы wire-моделями pkg    [PURE]
├── usecase.py         # оркестрация: порты + policy; anti-corruption (typed-ошибки → sentinel'ы)
├── views.py           # результат/ошибка usecase → данные виджетов/текст  [PURE]
├── dialogs.py         # Dialog(Window…)                                   [PRESENTATION]
├── getters.py         # @inject(aiogram_dialog) getter — данные в окно
├── handlers.py        # @inject — реакции/навигация (без policy!)
├── adapters.py        # cross-feature anti-corruption (если есть)
├── infra/             # не-HTTP реализации портов (cachekit-store…), если есть
└── provider.py        # dishka Provider: порт → pkg-клиент / infra / адаптер
```

HTTP-клиента **в фиче нет**: он в `src/bot/pkg/http_client/` (wire-модели + методы поверх `ApiClient`), порт фичи байндится на него напрямую в `provider.py`. `dto.py` — только для доменных типов поверх wire (payments: `Order(Money)`) и результатов шагов wizard'а (booking: `GuestsStep`); просмотровой фиче он не нужен (profile живёт на wire-`User`).

**Сокращённый** (pure, как `start`/`lang`) опускает `dto`/`errors`/`views`, а вместо pkg-клиента держит реализацию порта в `infra/` (cachekit-store, образец — `start/infra/store.py`). import-linter это допускает — слои `(views)`/`(ports)`/`(dto)`/`(policy)` опциональны.

## 3. StatesGroup — в центральный каталог

В `src/bot/platform/dialogs/states.py` добавь класс (НЕ объявляй `State()` по месту):

```python
class Referral(StatesGroup):
    VIEW = State()
    INVITE = State()
```

## 4. pkg-клиент + PURE-ядро (скелеты)

Wire-модель и метод клиента — в `pkg/http_client/internal/` (процедура и respx-тест — `references/backend-port.md` §A):

```python
# pkg/http_client/internal/referral.py
from pydantic import BaseModel
from pylibinfra.httpclient import ApiClient
from bot.pkg.http_client.internal.codec import parse

class Referral(BaseModel):
    code: str
    invited: int = 0

class ReferralAPI:
    def __init__(self, api: ApiClient) -> None:
        self._api = api
    async def get_referral(self, user_id: str) -> Referral:
        return parse(Referral, await self._api.get(f"/v1/referrals/{user_id}"))
```

(+ `@provide def referral(self, clients: ApiClients) -> ReferralAPI` в `pkg/http_client/provider.py` поверх `clients.get(CORE_BACKEND)`.)

```python
# state.py
from __future__ import annotations
from pydantic import BaseModel
from bot.platform.dialogs import states

ReferralSG = states.Referral

class ReferralDialogData(BaseModel):   # только JSON-примитивы (уезжает в Redis)
    draft_code: str | None = None
```

```python
# errors.py
from bot.shared.errors import FeatureError
class ReferralError(FeatureError): ...
class ReferralNotFound(ReferralError): ...
```

```python
# policy.py  (без I/O; возвращает Decision; зовётся ТОЛЬКО из usecase)
from bot.shared.decision import Decision, allow, deny
def can_invite(role: str) -> Decision:
    return deny("Недоступно") if role == "banned" else allow()
```

```python
# ports.py  (Protocol, узкий; имена/типы = pkg-клиент → байнд без адаптера)
from typing import Protocol
from bot.pkg.http_client.internal.referral import Referral

class ReferralGateway(Protocol):
    async def get_referral(self, user_id: str) -> Referral: ...
```

## 5. usecase / views

```python
# usecase.py — порты + policy (+ Logger). Anti-corruption: typed-ошибки → sentinel'ы ЗДЕСЬ.
from pylibinfra.httpclient import NotFoundError, UnavailableError
from pylibinfra.logkit import Logger
from bot.features.referral import errors, policy
from bot.features.referral.ports import ReferralGateway
from bot.pkg.http_client.internal.referral import Referral
from bot.platform.identity import BotIdentity

class ReferralUsecase:
    def __init__(self, gateway: ReferralGateway, log: Logger) -> None:
        self._gateway, self._log = gateway, log

    async def view(self, identity: BotIdentity) -> Referral:
        decision = policy.can_invite(identity.role)
        if not decision.allowed:
            raise errors.ReferralError(decision.reason)
        try:
            return await self._gateway.get_referral(identity.backend_user_id)
        except NotFoundError as exc:
            raise errors.ReferralNotFound(str(exc)) from exc
        except UnavailableError as exc:
            raise errors.ReferralError("Сервис недоступен") from exc
```

Wizard-фича: **все** шаги — методы usecase, включая passthrough (`BookingUsecase.set_services`); шаг возвращает результат-данные (`set_guests → GuestsStep(draft, address_required)` в `dto.py`), а не трогает `DialogManager` — какой экран следующий, решает handler по этим данным.

```python
# views.py — единственное место «ошибка → user-текст»
from typing import Any
from bot.features.referral import errors
from bot.pkg.http_client.internal.referral import Referral

def to_window(v: Referral) -> dict[str, Any]:
    return {"code": v.code, "invited": v.invited}

def error_text(err: Exception) -> str:
    match err:
        case errors.ReferralNotFound(): return "Реферальная программа недоступна."
        case errors.ReferralError(): return "Сервис временно недоступен."
        case _: raise err            # не наша — в recovery-middleware kit'а
```

## 6. Presentation

```python
# dialogs.py — статические подписи I18NFormat, динамика Format("{...}")
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.text import Format
from pylibinfra.tgbotkit import I18NFormat
from bot.features.referral import getters
from bot.features.referral.state import ReferralSG
from bot.platform.dialogs.common import back_to_menu

view_window = Window(
    Format("🎁 Код: <b>{code}</b>\nПриглашено: {invited}"),
    back_to_menu("ref_back"),
    state=ReferralSG.VIEW,
    getter=getters.referral_getter,
)
referral_dialog = Dialog(view_window)
```

```python
# getters.py — @inject из aiogram_dialog, **kwargs ОБЯЗАТЕЛЕН, дефолты всех ключей Format
from typing import Any
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from bot.features.referral import errors, views
from bot.features.referral.usecase import ReferralUsecase
from bot.platform.identity import BotIdentity

@inject
async def referral_getter(
    uc: FromDishka[ReferralUsecase], identity: FromDishka[BotIdentity], **kwargs: Any
) -> dict[str, Any]:
    try:
        return views.to_window(await uc.view(identity))
    except errors.ReferralError as exc:        # ловим в getter, окно не падает
        return {"code": "—", "invited": 0}
```

```python
# handlers.py — реакции/навигация; БЕЗ policy (import-linter «Handlers/getters без policy»):
# валидация/ветвление приходят результатом usecase, handler мапит их на экран (switch_to)
# и ошибку на текст (views.error_text). Формат-валидация ввода — type_factory → on_error.
# dialog-level on_click → @inject из aiogram_dialog;
# dispatcher-level (команда) → @inject из dishka.integrations.aiogram, DialogManager — обычный kwarg.
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from dishka import FromDishka
from dishka.integrations.aiogram import inject
from bot.features.referral.usecase import ReferralUsecase
from bot.platform.dialogs import states

@inject
async def on_referral_command(
    message: Message, dialog_manager: DialogManager, uc: FromDishka[ReferralUsecase]
) -> None:
    await dialog_manager.start(states.Referral.VIEW, mode=StartMode.NORMAL)
```

## 7. provider / adapters / __init__

```python
# provider.py — порт → pkg-клиент напрямую (DIP; Protocol совместим структурно), Scope.REQUEST
from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger
from bot.features.referral.ports import ReferralGateway
from bot.features.referral.usecase import ReferralUsecase
from bot.pkg.http_client.internal.referral import ReferralAPI

class ReferralProvider(Provider):
    scope = Scope.REQUEST
    @provide
    def gateway(self, api: ReferralAPI) -> ReferralGateway:
        return api
    @provide
    def usecase(self, gw: ReferralGateway, log: Logger) -> ReferralUsecase:
        return ReferralUsecase(gw, log)
```

Не-HTTP порт (кэш/Redis) — реализация в `infra/` (структурно удовлетворяет Protocol), байнд так же в `provider.py` (образец — `start/provider.py`: `OnboardingStore → CacheOnboardingStore(cache)`).

`adapters.py` — только если фиче нужны данные другой фичи: объяви cross-feature порт в **своём** `ports.py`, адаптер мапит чужой usecase, связь — в `provider.py` (образец — `profile/adapters.py` + `OnboardingReader`; процедура — `references/backend-port.md` §D). Это единственное (вместе с provider) место импорта другой фичи.

```python
# __init__.py — фасад: ровно то, что видит app.py
from aiogram.filters import Command
from pylibinfra.tgbotkit import CommandSpec
from bot.features.referral.dialogs import referral_dialog as dialog
from bot.features.referral.handlers import on_referral_command
from bot.features.referral.provider import ReferralProvider as Provider

cmd_spec = CommandSpec("message", on_referral_command, (Command("referral"),))
__all__ = ["Provider", "cmd_spec", "dialog"]
```

## 8. Регистрация — всё в `src/bot/app.py` (единый composition root)

- добавь `referral` в импорт `from bot.features import …`;
- `referral.Provider()` — в `build_container()` (`make_async_container(...)`, блок «фичи»);
- `referral.dialog` — в `ExtensionProvider.routers()` (`RouterBundle`); `referral.cmd_spec` — в `commands()` (`CommandBundle`);
- **`src/bot/config.py`**: если есть переводы — добавь `referral.ftl` в `_I18N_RESOURCES` и заведи `src/bot/locales/<lang>/referral.ftl` (ключи с префиксом `referral-`).

## 9. Тесты (RED→GREEN)

- `tests/pkg/test_referral_api.py` — respx-тест нового pkg-клиента (`references/backend-port.md` §A.4).
- `tests/unit/test_referral_usecase.py` — usecase на **фейке порта**: policy-гейты без I/O, маппинг typed-ошибок в sentinel'ы (образец — `test_profile_usecase.py`).
- `tests/unit/test_referral_policy.py` — pure policy/views.
- `tests/flows/test_referral_flow.py` — flow через `BotClient`+`MockMessageManager`+`make_container`/`build_dp` (`tests/_fakes/harness.py`). Бэкенд — `FakeApiClient` (`tests/_fakes/backend.py`; новый pkg-клиент поверх него — добавь `@provide` в `FakesProvider` harness'а). Локай кнопки по `callback_data`/тексту.
- `tests/flows/test_composition.py` — добавь `referral.dialog` в список детача (`for dialog in (...)`), чтобы startup-smoke покрыл коллизии StatesGroup.

```python
# tests/flows/test_referral_flow.py (скелет)
import pytest
from pylibinfra.testkit.bottest import BotClient, MockMessageManager
from tests._fakes.harness import build_dp, make_container
from bot.features import referral

pytestmark = pytest.mark.dialog

async def test_referral_command_opens_window() -> None:
    mm = MockMessageManager()
    container = make_container(referral.Provider())
    dp = build_dp(container, mm, routers=[referral.dialog], commands=[referral.cmd_spec])
    client = BotClient(dp)
    try:
        await client.send("/referral")
        assert mm.one_message() is not None
    finally:
        await container.close()
```

## 10. Верификация + коммит

```bash
make lint                     # import-linter: слои/независимость/чистое ядро/handlers без policy/pkg
make typecheck                # mypy: pkg-клиент структурно удовлетворяет порту
uv run pytest -k "referral or collision" -q
make check                    # перед claim «готово»
```

`feat(referral): scaffold referral feature` (новый pkg-клиент → `+ referral api client`; cross-feature → `+ <X>Reader port`).

## Anti-patterns

- ❌ Скопировать `profile/` целиком и переименовать — тащит чужую специфику. Делай по скелетам.
- ❌ HTTP-вызовы внутри фичи (свой клиент/сырой `httpx`) — клиент живёт в `pkg/http_client/`, фича видит порт.
- ❌ Окно без `state=` / `State()` по месту вместо `platform/dialogs/states.py`.
- ❌ I/O в getter (getter дёргает **usecase**, не порт/pkg-клиент). Мутации — в handler.
- ❌ `policy` в getter/handler — доменные решения приходят результатом usecase (import-linter заблокирует).
- ❌ Импорт другой фичи из ядра/presentation — только `adapters.py`/`provider.py`.
- ❌ Не зарегистрировать в `app.py` (`build_container` + `ExtensionProvider`) — фича не подключится.
- ❌ Забыть `referral.dialog` в `test_composition.py` — startup-smoke не покроет коллизию.
