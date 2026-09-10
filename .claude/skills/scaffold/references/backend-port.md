# scaffold › backend-port — pkg-клиент + порт фичи

Добавляет фиче новый источник данных. HTTP живёт **не в фиче**, а в `src/bot/pkg/http_client/` (клиенты областей API поверх `pylibinfra.httpclient.ApiClient`); фича видит его через **порт** — Protocol в `ports.py`, типизированный wire-моделями pkg-клиента (имена методов порта = имена методов клиента), `provider.py` байндит порт → pkg-клиент **напрямую** (структурно, mypy проверяет). Anti-corruption — в **usecase**: единственная точка маппинга typed-ошибок HTTP-границы (`bot.pkg.http_client.errors`) в sentinel'ы `errors.py` по канону «специфичные + catch-all `ApiError`» (+ wire→домен, где нужно). Границы enforce'ит import-linter («Чистое ядро», «pkg не знает про бот»). Соответствует rule `feature-architecture`.

## Случаи (выбери)

| Случай | Что делаешь | Образец |
|---|---|---|
| **Backend-метод** — данные/мутация на нашем бэкенде | §A (pkg-клиент, `internal/`) + §B (порт) | `ProfileAPI` + `profile.ports.BackendGateway` |
| **Сторонний API** (CRM/LLM/биллинг) | §A в `external/` + §C (именованный бэкенд) + §B | `pkg/http_client/external/` |
| **Cross-feature** — фиче A нужны данные из фичи B | §D (порт + адаптер) | `profile.ports.OnboardingReader` + `profile.adapters.OnboardingReaderAdapter` |

Не-HTTP реализация порта (Redis/кэш) — не сюда: модуль в `features/<имя>/infra/` (образец — `start/infra/store.py: CacheOnboardingStore`), байнд в `provider.py` фичи.

## Когда применять

- «Фиче нужно дёрнуть `GET /v1/...`» / «добавь мутацию на бэкенд».
- «Подключи CRM/LLM-сервис» (второй base_url).
- «Фиче referral нужен флаг онбординга из start».

## Когда НЕ применять

- Вызов внутри одной фичи — просто метод usecase.
- Данные уже есть в state/identity — порт не нужен.
- pkg-клиент и порт уже есть, нужен экран — `references/window.md`/`references/dialog.md`.

---

## A. Метод pkg-клиента

### 1. Понять контракт
Endpoint, метод, форма ответа, идемпотентность мутации (`Idempotency-Key`?). Коды ошибок мапит сам `ApiClient`: 404 → `NotFoundError`, 409 → `ConflictError`, 401 → `AuthError`, 403 → `ForbiddenError`, 429 → `RateLimitedError` (+`retry_after`; подкласс `UnavailableError`), 400/422/прочие 4xx → `InvalidRequestError`, 5xx-после-ретраев / transport / открытый breaker → `UnavailableError`, не-JSON 2xx или несоответствие `model=` → `ContractError` (подкласс `UnavailableError`). Все классы — `bot.pkg.http_client.errors`; у каждого есть `method`/`path`/`status_code`/`retry_after`/`body_snippet`.

### 2. Wire-модель + метод клиента
В существующий класс (`internal/profile.py: ProfileAPI` / `booking.py: BookingAPI` / `payments.py: PaymentsAPI`) или новый модуль `internal/<area>.py` (сторонний API — `external/<area>.py`). Wire-модель наследует `WireModel` (`wire.py`: `extra="forbid"` — дрейф контракта ловится на границе; `frozen`; поля без бизнес-дефолтов). Декод — `model=` самого клиента (несоответствие → `ContractError`); клиент зависит от `JsonApi`-Protocol (`api.py`), не от kit-класса:

```python
# pkg/http_client/internal/billing.py
from bot.pkg.http_client.api import JsonApi
from bot.pkg.http_client.wire import WireModel


class Balance(WireModel):
    amount: int
    currency: str


class BillingAPI:
    def __init__(self, api: JsonApi) -> None:
        self._api = api

    async def get_balance(self, user_id: str) -> Balance:
        return await self._api.get(f"/v1/balance/{user_id}", model=Balance)
```

Мутация — `idempotency_key=` считается **самим клиентом** каноном `idempotency.idempotency_key(op, *parts)` (sha256 → ASCII-safe: кириллица в latin-1 HTTP-заголовке падает `UnicodeEncodeError` до запроса). Без ключа kit выполняет мутацию **одной попыткой** (ретраи только с ключом):

```python
from bot.pkg.http_client.idempotency import idempotency_key

await self._api.post(
    f"/v1/orders/{oid}/cancel",
    json={...},
    idempotency_key=idempotency_key("order-cancel", oid),
)
```

Typed-ошибки клиент **не ловит** — они и есть его контракт. Исключение — идемпотентное смягчение, когда 409/404 на повторе = «уже применено» = успех (образец — `PaymentsAPI.fulfill_order`/`revoke_order`).

### 3. Провайд клиента
Тот же бэкенд «core» — `@provide` в `pkg/http_client/provider.py` (`InternalApiProvider`) поверх реестра:

```python
@provide
def billing(self, clients: ApiClients) -> BillingAPI:
    return BillingAPI(clients.get(CORE_BACKEND))
```

Другой base_url (другой сервис) → §C.

### 4. respx-тест — `tests/pkg/`
Транспорт-граница тестируется здесь и только здесь (фикстура `api` — `tests/pkg/conftest.py`: `ApiClient` без ретраев на `http://backend`):

```python
# tests/pkg/test_billing_api.py
import httpx
import pytest
import respx
from pylibinfra.httpclient import ApiClient

from bot.pkg.http_client.errors import ContractError, NotFoundError
from bot.pkg.http_client.internal.billing import BillingAPI

pytestmark = pytest.mark.pkg


@respx.mock
async def test_get_balance_returns_model(api: ApiClient) -> None:
    respx.get("http://backend/v1/balance/u1").mock(
        return_value=httpx.Response(200, json={"amount": 5, "currency": "XTR"})
    )
    assert (await BillingAPI(api).get_balance("u1")).amount == 5


@respx.mock
async def test_get_balance_broken_contract_raises_contract_error(api: ApiClient) -> None:
    respx.get("http://backend/v1/balance/u1").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    with pytest.raises(ContractError, match="does not match Balance"):
        await BillingAPI(api).get_balance("u1")
```

Проверь как минимум: happy path (модель собралась), 404 → `NotFoundError`, ломаный контракт → `ContractError`; у мутации — заголовок `Idempotency-Key` (канон-формат, latin-1-кодируемость). Негативный канон таксономии/ретраев целиком — `tests/pkg/test_error_taxonomy.py` (не дублируй его в каждом клиенте).

---

## B. Порт фичи

### 1. Protocol — `ports.py`
Сужай до методов ЭТОГО сценария (ISP). Имена и типы — **как у pkg-клиента** (структурная совместимость, без адаптера):

```python
from typing import Protocol

from bot.pkg.http_client.internal.billing import Balance


class BillingGateway(Protocol):
    async def get_balance(self, user_id: str) -> Balance: ...
```

Если у фичи уже есть порт (`BackendGateway`) — добавь метод в него.

### 2. Байнд — `provider.py` фичи

```python
@provide
def gateway(self, api: BillingAPI) -> BillingGateway:
    return api


@provide
def usecase(self, gw: BillingGateway, log: Logger) -> BillingUsecase:
    return BillingUsecase(gw, log)
```

### 3. Маппинг ошибок — в usecase (единственная точка)
usecase знает порт + policy; typed-ошибки HTTP-границы (`bot.pkg.http_client.errors`) мапит в sentinel'ы фичи **здесь**, не в getter/handler. Канон «специфичные + catch-all»: доменно-значимые классы (`NotFoundError`/`ConflictError`) → свои sentinel'ы, замыкающий `except ApiError` → `*Unavailable` (401/422/429/Contract не протекают в recovery). Sentinel'ы user-текст **не несут** — текст живёт в `.ftl` (ключ отдаёт `views.error_text`):

```python
from bot.pkg.http_client.errors import ApiError, NotFoundError


async def balance(self, identity: BotIdentity) -> Balance:
    decision = policy.can_view_balance(identity.role)
    if not decision.allowed:
        raise errors.BillingForbidden(decision.reason)
    try:
        return await self._gateway.get_balance(identity.backend_user_id)
    except NotFoundError as exc:
        raise errors.BalanceNotFound from exc
    except ApiError as exc:
        self._log.warn("billing.backend_fault", kind=type(exc).__name__, status=exc.status_code)
        raise errors.BillingUnavailable from exc
```

Нужен доменный тип вместо wire-модели (единицы, инварианты) — мапь тут же и держи его в `dto.py` (образец — payments: wire-`Offer` → `Order(Money)` в `PaymentsUsecase.offer`). Просмотровым фичам хватает wire-модели как есть (profile отдаёт `User`).

### 4. Юнит-тест usecase — фейк порта
Не транспорт: рукописный фейк, структурно удовлетворяющий Protocol (образцы — `tests/unit/test_profile_usecase.py`, `test_booking_usecase.py`):

```python
class _Gateway:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def get_balance(self, user_id: str) -> Balance:
        if self._error is not None:
            raise self._error
        return Balance(amount=5)


async def test_balance_maps_unavailable() -> None:
    uc = BillingUsecase(_Gateway(error=UnavailableError("503")), nop())
    with pytest.raises(errors.BillingUnavailable):
        await uc.balance(_IDENTITY)
```

Flow-тесты не трогаются: harness (`tests/_fakes/harness.py`) отдаёт pkg-клиенты поверх `FakeApiClient` (`tests/_fakes/backend.py` — in-memory реализация `JsonApi`: payload per-path (`payloads[path]` + общий `payload`), per-метод инжекторы `get_error`/`post_error`/`put_error`/`patch_error`/`delete_error`, запись `calls`/`idempotency_keys`, `model=` применяется как в ките).

---

## C. Несколько именованных бэкендов

Бот ходит в **несколько** независимых API (core + CRM/LLM/биллинг). Реестр — kit: `BackendsConfig.backends: dict[имя, BackendConfig]` → `ApiClientsProvider` (уже в `app.py`) → `ApiClients.get(имя)`. У каждого бэкенда свой клиент со своей политикой (таймаут/ретраи/цепь); цепь и метрики `http_client_*` kit ведёт на каждый upstream-хост (label `host`). dishka различает клиентов по **классам областей API** (`CrmAPI` vs `ProfileAPI`) — никаких маркер-обёрток не нужно.

1. **Модуль клиента** — §A (`internal/crm.py` или `external/crm.py`).
2. **Имя-константа + `@provide`** — `pkg/http_client/provider.py`:

```python
CRM_BACKEND = "crm"


@provide
def crm(self, clients: ApiClients) -> CrmAPI:
    return CrmAPI(clients.get(CRM_BACKEND))
```

3. **Декларация в `BackendsConfig`** — `config.py` (`AppConfigProvider.backends`); каждый бэкенд — свой `BackendConfig`, `base_url` **обязателен** (пустой валит старт fail-fast; глобальные `HTTPCLIENT_*` в декларацию не протекают). Провайдер уже объединяет `HTTPCLIENT_BACKENDS` (JSON из ENV) с «core» из кода — программная запись добавляется рядом:

```python
@provide
def backends(self) -> httpclient.BackendsConfig:
    declared = httpclient.new_backends_config()  # HTTPCLIENT_BACKENDS (JSON), fail-fast
    backends = dict(declared.backends)
    if CORE_BACKEND not in backends:
        backends[CORE_BACKEND] = _core_backend()
    if CRM_BACKEND not in backends:  # запись из ENV перекрывает код (deploy-override)
        backends[CRM_BACKEND] = httpclient.BackendConfig(
            base_url=os.environ["CRM_BASE_URL"],
            headers={"Authorization": f"Bearer {os.environ['CRM_TOKEN']}"},
        )
    return declared.model_copy(update={"backends": backends})
```

Альтернатива программной записи — env-JSON целиком: `HTTPCLIENT_BACKENDS='{"crm": {"base_url": "...", "headers": {"Authorization": "Bearer ..."}}}'` (тогда в `backends()` ничего не добавляется); выбор источника — решение стека (`docs/stack/backends.md`). Новый бэкенд добавь в fail-fast composition-тест (`tests/flows/test_composition.py`).

> Новый `*_BASE_URL` env — инфра-поверхность: оформи INFRA-HANDOFF (rule `infra-impact`).

---

## D. Cross-feature

### 1. Направление
Кто **потребляет** — тот владеет портом. profile нужен флаг из start → порт `OnboardingReader` живёт в `profile/ports.py`, не в start.

### 2. Узкий порт — `ports.py` потребителя
Контракт — в терминах потребителя, не тип чужой фичи:

```python
class OnboardingReader(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...
```

### 3. Адаптер — `adapters.py` потребителя
ЕДИНСТВЕННОЕ (вместе с provider) место импорта другой фичи (import-linter `ignore_imports`):

```python
from bot.features.start.usecase import StartUsecase


class OnboardingReaderAdapter:  # структурно удовлетворяет ports.OnboardingReader
    def __init__(self, start_uc: StartUsecase) -> None:
        self._start = start_uc

    async def is_onboarded(self, tg_id: int) -> bool:
        return (await self._start.status(tg_id)).completed
```

### 4. Связать в provider.py

```python
@provide
def onboarding(self, start_uc: StartUsecase) -> OnboardingReader:
    return OnboardingReaderAdapter(start_uc)
```

`StartUsecase` резолвится из контейнера (start.Provider зарегистрирован в `build_container`, `app.py`). Если чужого usecase-метода нет (`status`) — добавь его в фичу-источник.

---

## Тесты + верификация

- pkg-клиент — `respx` в `tests/pkg/` (§A.4): пути/payload/Idempotency-Key/валидация контракта.
- usecase — **фейк порта** (§B.4): policy-гейты без I/O, маппинг typed-ошибок в sentinel'ы.
- mypy strict проверит, что pkg-клиент/адаптер **структурно удовлетворяет** порту (Protocol) — частая ошибка ловится здесь.

```bash
make typecheck                # Protocol-совместимость
make lint                     # import-linter: чистое ядро, pkg ↛ бот, cross-feature только adapters/provider
uv run pytest tests/pkg/test_billing_api.py tests/unit/test_billing_usecase.py -q
make check
```

`feat(billing): add balance api + gateway port` / `feat(profile): add OnboardingReader port`

## Anti-patterns

- ❌ Сырой `httpx` в фиче или в pkg-клиенте — только `pylibinfra.httpclient.ApiClient`.
- ❌ Ловить/мапить typed-ошибки в getter/handler или в pkg-клиенте — единственная точка маппинга в sentinel'ы — usecase (исключение — идемпотентное смягчение 409/404 в клиенте).
- ❌ Возвращать из pkg-клиента сырой JSON (без `model=`) — ломаный контракт всплывёт `KeyError`'ом в окне вместо `ContractError`; wire-модель мимо `WireModel` (`extra="forbid"`) — молчаливый дрейф контракта.
- ❌ Idempotency-ключ «руками» (f-строка с сырым вводом) — только `idempotency_key(op, *parts)`; без ключа мутация не ретраится.
- ❌ Адаптер-прослойка между портом и pkg-клиентом «для чистоты» — Protocol совместим структурно, байнд в provider достаточно.
- ❌ Широкий порт «на вырост» (10 методов «вдруг пригодится»). Сузь до нужного сейчас.
- ❌ Импорт другой фичи из `usecase.py`/`getters.py` — только `adapters.py`/`provider.py` (import-linter заблокирует).
- ❌ Импорт `bot.features.*`/`aiogram` из pkg — контракт «pkg не знает про бот».
- ❌ Двусторонняя cross-feature зависимость A↔B — сигнал кривых границ; подумай о третьей фиче или platform-glue (`platform/links.py`-паттерн).
- ❌ Мутация без `Idempotency-Key` при риске двойного клика/ретрая httpclient; не-ASCII в ключе.
- ❌ Новый бэкенд без декларации в `BackendsConfig` — `UnknownBackendError` при резолве клиента (ловит composition-тест); без INFRA-HANDOFF на новый `*_BASE_URL` — разъедешься с прод-окружением.
- ❌ `from pylibinfra.httpclient import ...` в фиче — одна дверь: всё через `bot.pkg.http_client` (banned-api TID251 заблокирует).
