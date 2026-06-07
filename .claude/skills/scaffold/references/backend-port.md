# scaffold › backend-port — порт + адаптер + DTO

Добавляет фиче новый источник данных через **порт (Protocol) + реализацию + DTO**: либо новый метод бэкенда (`BackendGateway`), либо cross-feature чтение из другой фичи. Граница «ядро не знает про httpx/другую фичу» enforce-ится import-linter'ом — порт это и есть способ её соблюсти. Соответствует rule `feature-architecture`.

## Два случая (выбери)

| Случай | Порт где | Реализация где |
|---|---|---|
| **Backend-метод** — фиче нужны данные/мутация на бэкенде | `ports.py` фичи (`BackendGateway`) | `gateway.py` (HTTP поверх `platform/backend`) |
| **Cross-feature** — фиче A нужны данные из фичи B | `ports.py` фичи-потребителя (свой узкий порт) | `adapters.py` (мапит чужой usecase) |

Образцы: backend — `profile.ports.BackendGateway` + `profile.gateway.HttpProfileGateway`; cross-feature — `profile.ports.OnboardingReader` + `profile.adapters.OnboardingReaderAdapter`.

## Когда применять

- «Фиче нужно дёрнуть `GET /v1/...`» / «добавь мутацию на бэкенд».
- «Фиче referral нужен флаг онбординга из start».

## Когда НЕ применять

- Вызов внутри одной фичи — просто метод usecase.
- Данные уже есть в state/identity — порт не нужен.

---

## A. Backend-метод

### 1. Понять контракт
Endpoint, метод, форма ответа, коды ошибок (404 → sentinel? 5xx/breaker → `BackendUnavailable`?), идемпотентность мутации (`Idempotency-Key`?).

### 2. DTO (anti-corruption) — `dto.py`
Локальный тип фичи, не схема бэкенда:
```python
class Balance(BaseModel):
    amount: int
    currency: str = "XTR"
```

### 3. Метод порта — `ports.py`
Сужай до того, что нужно ЭТОМУ сценарию (ISP):
```python
class BackendGateway(Protocol):
    async def load_balance(self, backend_user_id: str) -> Balance: ...
```
Если у фичи уже есть `BackendGateway` — добавь метод в него.

### 4. Реализация — `gateway.py`
Маппит транспорт-ошибки в sentinel'ы; `httpx` скрыт за `platform/backend.BackendClient`:
```python
async def load_balance(self, backend_user_id: str) -> Balance:
    try:
        raw = await self._http.get(f"/v1/balance/{backend_user_id}")
    except BackendNotFound as e:
        raise errors.BalanceNotFound(str(e)) from e
    except BackendUnavailable as e:
        raise errors.FeatureError("Сервис недоступен") from e
    return Balance(amount=int(raw["amount"]), currency=raw.get("currency", "XTR"))
```
Мутация — добавь `idempotency_key=` (как `profile.gateway.update_name` / `payments.gateway.fulfill`):
```python
await self._http.post(f"/v1/orders/{oid}/cancel", json={...}, idempotency_key=f"cancel:{oid}")
```

### 5. Использовать в usecase
usecase зовёт **порт** (тип — `BackendGateway`), не gateway-класс. provider.py уже связывает порт→`HttpXxxGateway` — если порт существующий, новый метод доступен сразу.

---

## B. Cross-feature

### 1. Направление
Кто **потребляет** — тот владеет портом. profile нужен флаг из start → порт `OnboardingReader` живёт в `profile/ports.py`, не в start.

### 2. Узкий порт — `ports.py` потребителя
Возвращает **локальный** DTO потребителя, не тип чужой фичи:
```python
class OnboardingReader(Protocol):
    async def is_onboarded(self, tg_id: int) -> bool: ...
```

### 3. Адаптер — `adapters.py` потребителя
ЕДИНСТВЕННОЕ (вместе с provider) место импорта другой фичи (import-linter `ignore_imports`):
```python
from bot.features.start.usecase import StartUsecase

class OnboardingReaderAdapter:           # структурно удовлетворяет ports.OnboardingReader
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

@provide
def usecase(self, gw: BackendGateway, onb: OnboardingReader, log: Logger) -> ProfileUsecase:
    return ProfileUsecase(gw, onb, log)
```
`StartUsecase` резолвится из контейнера (start.Provider зарегистрирован в `app.py`). Если чужого usecase-метода нет (`status`) — добавь его в фичу-источник.

---

## Тесты + верификация

- usecase-тест через **фейк порта** (не транспорт): подставь fake-gateway/fake-reader, проверь поведение usecase.
- backend-случай: `respx` мокает httpx на границе `BackendClient` (`tests/backend/`), либо `FakeBackendClient` (`tests/_fakes/backend.py`).
- mypy strict проверит, что адаптер/gateway **структурно удовлетворяет** порту (Protocol) — частая ошибка ловится здесь.

```bash
make typecheck                # Protocol-совместимость
make lint                     # import-linter: cross-feature только из adapters/provider
uv run pytest tests/.../test_X.py -q
make check
```

`feat(profile): add Balance backend gateway` / `feat(profile): add OnboardingReader port`

## Anti-patterns

- ❌ Возвращать из gateway/адаптера сырой JSON или тип чужой фичи (`*start.OnboardingStatus`). Маппь в локальный DTO.
- ❌ Широкий порт «на вырост» (10 методов «вдруг пригодится»). Сузь до нужного сейчас.
- ❌ `httpx` напрямую в gateway — только через `platform/backend.BackendClient`.
- ❌ Импорт другой фичи из `usecase.py`/`getters.py` — только `adapters.py`/`provider.py` (import-linter заблокирует).
- ❌ Двусторонняя cross-feature зависимость A↔B — сигнал кривых границ; подумай о третьей фиче или platform-glue (`platform/links.py`-паттерн).
- ❌ Мутация без `Idempotency-Key` при риске двойного клика/ретрая httpclient.
