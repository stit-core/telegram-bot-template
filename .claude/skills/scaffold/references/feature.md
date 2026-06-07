# scaffold › feature — новый вертикальный срез

Создаёт новую фичу (bounded context одного пользовательского сценария) по конвенции шаблона. Полный гексагон — эталон `features/profile/`; полные скелеты файлов — `design/FEATURE-BLUEPRINT.md`. Соответствует rule `feature-architecture` (открой, если не загружено).

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

## 2. Дерево фичи

Полный гексагон (`profile`-образец):

```
src/bot/features/<name>/
├── __init__.py        # фасад: Provider, dialog (+ cmd_spec/command_specs)
├── state.py           # re-export StatesGroup + pydantic-данные диалога  [PURE]
├── dto.py             # доменные DTO (anti-corruption)                    [PURE]
├── errors.py          # sentinel-ошибки (от shared.errors.FeatureError)   [PURE]
├── policy.py          # чистые решения → shared.decision.Decision         [PURE]
├── ports.py           # Protocol-порты (BackendGateway, cross-feature)    [PURE]
├── usecase.py         # оркестрация: порты + policy (+ logkit.Logger)
├── gateway.py         # реализация порта поверх platform/backend → DTO    [I/O]
├── views.py           # результат/ошибка usecase → данные виджетов/текст  [PURE]
├── dialogs.py         # Dialog(Window…)                                   [PRESENTATION]
├── getters.py         # @inject(aiogram_dialog) getter — данные в окно
├── handlers.py        # @inject — реакции/навигация
├── adapters.py        # cross-feature anti-corruption (если есть)
└── provider.py        # dishka Provider: порт→адаптер
```

**Сокращённый** (pure, как `start`/`lang`) опускает `dto`/`errors`/`views` и/или заменяет `gateway` на cachekit-store: `__init__`, `state`, `policy`, `ports`, `usecase`, `dialogs`, `getters`, `handlers`, `gateway` (над cachekit), `provider`. import-linter это допускает — слои `(views)`/`(ports)`/`(dto)` опциональны.

## 3. StatesGroup — в центральный каталог

В `src/bot/platform/dialogs/states.py` добавь класс (НЕ объявляй `State()` по месту):

```python
class Referral(StatesGroup):
    VIEW = State()
    INVITE = State()
```

## 4. PURE-ядро (скелеты)

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
# dto.py  (anti-corruption, не схема бэкенда)
from pydantic import BaseModel
class ReferralView(BaseModel):
    code: str
    invited: int = 0
```

```python
# errors.py
from bot.shared.errors import FeatureError
class ReferralError(FeatureError): ...
class ReferralNotFound(ReferralError): ...
```

```python
# policy.py  (без I/O; возвращает Decision)
from bot.shared.decision import Decision, allow, deny
def can_invite(role: str) -> Decision:
    return deny("Недоступно") if role == "banned" else allow()
```

```python
# ports.py  (Protocol, узкий, возвращает локальный DTO)
from typing import Protocol
from bot.features.referral.dto import ReferralView
class BackendGateway(Protocol):
    async def load(self, backend_user_id: str) -> ReferralView: ...
```

## 5. usecase / gateway / views

```python
# usecase.py — знает ТОЛЬКО порты + policy (+ Logger). Не httpx/aiogram/redis.
from pylibinfra.logkit import Logger
from bot.features.referral import errors, policy
from bot.features.referral.dto import ReferralView
from bot.features.referral.ports import BackendGateway
from bot.platform.identity import BotIdentity

class ReferralUsecase:
    def __init__(self, gateway: BackendGateway, log: Logger) -> None:
        self._gateway, self._log = gateway, log

    async def view(self, identity: BotIdentity) -> ReferralView:
        decision = policy.can_invite(identity.role)
        if not decision.allowed:
            raise errors.ReferralError(decision.reason)
        return await self._gateway.load(identity.backend_user_id)
```

```python
# gateway.py — единственный I/O; транспорт-ошибки → sentinel'ы фичи
from bot.features.referral import errors
from bot.features.referral.dto import ReferralView
from bot.platform.backend import BackendClient, BackendNotFound, BackendUnavailable

class HttpReferralGateway:           # структурно удовлетворяет ports.BackendGateway
    def __init__(self, http: BackendClient) -> None:
        self._http = http
    async def load(self, backend_user_id: str) -> ReferralView:
        try:
            raw = await self._http.get(f"/v1/referrals/{backend_user_id}")
        except BackendNotFound as e:
            raise errors.ReferralNotFound(str(e)) from e
        except BackendUnavailable as e:
            raise errors.ReferralError("Сервис недоступен") from e
        return ReferralView(code=raw["code"], invited=int(raw.get("invited", 0)))
```

```python
# views.py — единственное место «ошибка → user-текст»
from bot.features.referral import errors
from bot.features.referral.dto import ReferralView
def to_window(v: ReferralView) -> dict[str, object]:
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
# handlers.py — реакции/навигация. dialog-level on_click → @inject из aiogram_dialog;
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
# provider.py — порт → реализация (DIP), Scope.REQUEST
from dishka import Provider, Scope, provide
from pylibinfra.logkit import Logger
from bot.features.referral.gateway import HttpReferralGateway
from bot.features.referral.ports import BackendGateway
from bot.features.referral.usecase import ReferralUsecase
from bot.platform.backend import BackendClient

class ReferralProvider(Provider):
    scope = Scope.REQUEST
    @provide
    def gateway(self, http: BackendClient) -> BackendGateway:
        return HttpReferralGateway(http)
    @provide
    def usecase(self, gw: BackendGateway, log: Logger) -> ReferralUsecase:
        return ReferralUsecase(gw, log)
```

`adapters.py` — только если фиче нужны данные другой фичи: объяви cross-feature порт в **своём** `ports.py`, адаптер мапит чужой usecase, связь — в `provider.py` (образец — `profile/adapters.py` + `OnboardingReader`). Это единственное (вместе с provider) место импорта другой фичи.

```python
# __init__.py — фасад: ровно то, что видят app.py/extensions.py
from aiogram.filters import Command
from pylibinfra.tgbotkit import CommandSpec
from bot.features.referral.dialogs import referral_dialog as dialog
from bot.features.referral.handlers import on_referral_command
from bot.features.referral.provider import ReferralProvider as Provider

cmd_spec = CommandSpec("message", on_referral_command, (Command("referral"),))
__all__ = ["Provider", "cmd_spec", "dialog"]
```

## 8. Регистрация в точки расширения

- **`src/bot/app.py`**: импортируй фичу, добавь `referral.Provider()` в `make_async_container(...)`.
- **`src/bot/extensions.py`** (`ExtensionProvider`): добавь `referral` в импорт `from bot.features import …`; `referral.dialog` в `routers()` (`RouterBundle`); `referral.cmd_spec` в `commands()` (`CommandBundle`).
- **`src/bot/config.py`**: если есть переводы — добавь `referral.ftl` в `_I18N_RESOURCES` и заведи `src/bot/locales/<lang>/referral.ftl` (ключи с префиксом `referral-`).

## 9. Тесты (RED→GREEN)

- `tests/unit/test_referral_policy.py` — pure policy/views.
- `tests/flows/test_referral_flow.py` — flow через `BotClient`+`MockMessageManager`+`make_container`/`build_dp` (`tests/_fakes/harness.py`). Мокай порт через `FakeBackendClient`. Локай кнопки по `callback_data`/тексту.
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
make lint                     # import-linter держит слои/независимость/чистое ядро
make typecheck                # mypy: gateway структурно удовлетворяет порту
uv run pytest -k "referral or collision" -q
make check                    # перед claim «готово»
```

`feat(referral): scaffold referral feature` (бэкенд-данные → `+ backend gateway`; cross-feature → `+ <X>Reader port`).

## Anti-patterns

- ❌ Скопировать `profile/` целиком и переименовать — тащит чужую специфику. Делай по скелетам.
- ❌ Окно без `state=` / `State()` по месту вместо `platform/dialogs/states.py`.
- ❌ I/O в getter (getter дёргает **usecase**, не gateway). Мутации — в handler.
- ❌ Импорт другой фичи из ядра/presentation — только `adapters.py`/`provider.py`.
- ❌ Не зарегистрировать в `app.py`+`extensions.py` — фича не подключится (бот её не увидит).
- ❌ Забыть `referral.dialog` в `test_composition.py` — startup-smoke не покроет коллизию.
