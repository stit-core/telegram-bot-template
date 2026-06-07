# 09 · Интеграция бота с бэкендами (зона I) — SOLID / чистая архитектура

> Design-input артефакт зоны I. Центральная тема **«бот = фронтенд»**: вся
> бизнес-логика на бэкендах (HTTP API + события по NATS), бот держит только свой
> диалоговый state (Redis) и переводит апдейты Telegram в вызовы бэкендов.
>
> Опирается на: **01** (ports/adapters, раскладка фичи `internal/features/<f>/`),
> **05** (integration-киты: httpclient/cachekit/natskit/authnkit), **06** (dishka
> ↔ aiogram), `aiogram-dialog-docs/reference/06` (BgManager), и исходники
> `pylibinfra/httpclient/`, `pylibinfra/cachekit/`, `pylibinfra/natskit/`,
> `pylibinfra/httpkit/idempotency.py`.
>
> Все цитируемые API — реальные. Ссылки вида `client.py:82` — на файлы
> `pylibinfra/<kit>/`.

---

## 0. Картина целиком (один абзац)

Фича-потребитель (`internal/features/<feature>/usecase.py`) **объявляет узкий
Protocol-порт** `BackendGateway` и зависит только от него — не от `httpx`, не от
`pylibinfra.httpclient.Client`. Адаптер (`infra/backend/<feature>_gateway.py`)
реализует порт поверх `httpclient.Client`: типизирует запрос/ответ pydantic-DTO,
прокидывает корреляцию (`X-Request-ID`), identity (tg-user-id / сервисный JWT) и
`Idempotency-Key` для мутаций, и **маппит транспортные ошибки бэкенда
(4xx/5xx/`BreakerOpenError`) в доменные ошибки фичи**. Делается это в
`provider.py` (dishka). Каждый бэкенд = свой `Client`/`Config`/breaker = свой
Provider. Обратное направление (push): бэкенд публикует событие → подписчик бота
(`natskit`) резолвит `chat_id` → шлёт сообщение через `Bot` или обновляет диалог
через `BgManagerFactory.bg(...)`. На недоступном бэкенде (breaker open / timeout)
пользователь видит дружелюбное «сервис занят», а не stacktrace 500.

---

## 1. Зависимость-инверсия: Protocol-порт vs адаптер над httpclient

### 1.1 Принцип (зеркало 01 §2)

В Go-шаблоне порт объявляется **в домене-потребителе**, адаптер — в `module/`
(единственное место, где depguard разрешает импорт провайдера). На боте 1:1:

| Go (01) | Бот |
|---|---|
| порт-interface в `<domain>/usecase.go` | `Protocol` в `<feature>/usecase.py` |
| локальный DTO потребителя (`auth.User`, не `*user.User`) | pydantic-DTO фичи, не сырая JSON-схема бэкенда |
| адаптер в `<domain>/module/adapters.go` | адаптер в `<feature>/infra/backend/*.py` |
| регистрация адаптера в `module.go` (fx) | регистрация в `<feature>/provider.py` (dishka) |

**Что это даёт (SOLID):**
- **DIP** — usecase зависит от абстракции `BackendGateway`, а не от `httpx`/`Client`.
- **ISP** — порт сужен до 2–4 методов сценария, а не «весь API бэкенда».
- **анти-corruption** — DTO фичи изолируют usecase от формы JSON бэкенда
  (поменялась схема → правим только адаптер).
- **тестируемость** — в юнит-тестах подставляется фейк порта, фича не ходит в сеть
  (зеркало «мокай Repository, не Pool», 01 §5).

### 1.2 DTO фичи (`<feature>/dto.py`)

Это **доменные** DTO потребителя — не «HTTP-DTO бэкенда». Pydantic для валидации
на границе:

```python
# internal/features/profile/dto.py
from pydantic import BaseModel

class Profile(BaseModel):           # то, чем оперирует usecase/вью
    user_id: str
    display_name: str
    tier: str                       # "free" | "pro" | ...

class TopUpRequest(BaseModel):      # вход мутации (доменный)
    amount_minor: int               # копейки
    currency: str

class TopUpResult(BaseModel):
    balance_minor: int
    tx_id: str
```

> Если у бэкенда есть OpenAPI — кодген «wire-DTO» кладётся **рядом в адаптере**
> (`infra/backend/_wire.py`, «не править руками» как `db/` у sqlc, 01 §5), а адаптер
> маппит wire-DTO → DTO фичи. Не тащить wire-типы в usecase.

### 1.3 Порт (`<feature>/usecase.py`)

```python
# internal/features/profile/usecase.py
from typing import Protocol
from .dto import Profile, TopUpRequest, TopUpResult

class BackendGateway(Protocol):                     # порт — владелец = потребитель
    async def get_profile(self, user_id: str) -> Profile: ...
    async def top_up(self, user_id: str, req: TopUpRequest) -> TopUpResult: ...
```

Usecase оркеструет сценарий, зная только порт + свои ошибки:

```python
# тот же usecase.py
from .errors import BackendUnavailable, ProfileNotFound

class ProfileUsecase:
    def __init__(self, gw: BackendGateway) -> None:
        self._gw = gw

    async def show_profile(self, user_id: str) -> Profile:
        # никаких httpx/Client/статус-кодов здесь — только доменные типы и ошибки
        return await self._gw.get_profile(user_id)
```

### 1.4 Доменные ошибки фичи (`<feature>/errors.py`)

Sentinel-ошибки (зеркало `errors.go`, 01 таблица слоёв). Транспортных деталей тут
нет — их «съедает» адаптер:

```python
# internal/features/profile/errors.py
class FeatureError(Exception): ...
class ProfileNotFound(FeatureError): ...          # ← backend 404
class TopUpRejected(FeatureError):                # ← backend 409/422 с кодом
    def __init__(self, reason: str) -> None: self.reason = reason
class BackendUnavailable(FeatureError): ...       # ← BreakerOpenError / timeout / 5xx
class BackendBadResponse(FeatureError): ...       # ← невалидный JSON / схема
```

### 1.5 Адаптер над `httpclient.Client` (`infra/backend/profile_gateway.py`)

Сердце интеграции. Реализует `BackendGateway`, цитируя реальный API httpclient
(`Client.get/post` — `client.py:76,79`; `BreakerOpenError` — `breaker.py:10`):

```python
# internal/features/profile/infra/backend/profile_gateway.py
import httpx
from pydantic import ValidationError
from pylibinfra.httpclient import Client, BreakerOpenError

from ...dto import Profile, TopUpRequest, TopUpResult
from ...errors import (
    BackendUnavailable, ProfileNotFound, TopUpRejected, BackendBadResponse,
)
from ...usecase import BackendGateway   # порт (структурно реализуем)
from .identity import IdentityContext   # см. §2
from .idempotency import make_idem_key  # см. §3


class HttpProfileGateway(BackendGateway):
    def __init__(self, client: Client, ident: IdentityContext) -> None:
        self._client = client            # один Client = один base_url + один breaker
        self._ident = ident

    # --- read ---
    async def get_profile(self, user_id: str) -> Profile:
        try:
            resp = await self._client.get(
                f"/api/v1/users/{user_id}/profile",
                headers=self._ident.headers(),     # tg-user-id / Authorization (§2)
            )
        except BreakerOpenError:                    # брейкер открыт → fast-fail (§6)
            raise BackendUnavailable()
        except httpx.TimeoutException:
            raise BackendUnavailable()
        return self._read(resp, Profile)            # маппинг статусов + декод

    # --- write (идемпотентно) ---
    async def top_up(self, user_id: str, req: TopUpRequest) -> TopUpResult:
        idem = make_idem_key("top_up", user_id, req)        # стабильный ключ (§3)
        try:
            resp = await self._client.post(
                f"/api/v1/users/{user_id}/balance/top-up",
                json=req.model_dump(),
                headers={**self._ident.headers(), "Idempotency-Key": idem},
            )
        except BreakerOpenError:
            raise BackendUnavailable()
        except httpx.TimeoutException:
            # ⚠️ POST: таймаут НЕ значит «не выполнено». Тот же Idempotency-Key при
            # ретрае не задвоит мутацию на бэкенде (§3).
            raise BackendUnavailable()
        return self._read(resp, TopUpResult, conflict=TopUpRejected)

    # --- общий маппинг ответа → DTO/ошибка (см. таблицу §4) ---
    def _read(self, resp, model, *, conflict=None):
        sc = resp.status_code
        if sc == 404:
            raise ProfileNotFound()
        if sc in (409, 422) and conflict is not None:
            reason = (resp.json() or {}).get("code", "rejected")
            raise conflict(reason)
        if sc >= 500:
            # httpclient уже отретраил 5xx (client.py:137) и поднял HTTPStatusError
            # при исчерпании; сюда дойдёт как ответ только если ретраи отключены —
            # на всякий случай маппим тоже.
            raise BackendUnavailable()
        if sc >= 400:
            raise BackendBadResponse()
        try:
            return model.model_validate_json(resp.content)
        except ValidationError:
            raise BackendBadResponse()
```

> **Тонкость httpclient (client.py:121-148).** `Client` сам ретраит
> `httpx.TransportError` и `>=500` (`client.py:137`), 4xx — **не** ретраит. При
> исчерпании ретраев на 5xx он поднимает `httpx.HTTPStatusError` (а не возвращает
> resp) — `client.py:143`. Поэтому адаптеру стоит обрабатывать и
> `httpx.HTTPStatusError`/`httpx.RequestError` (→ `BackendUnavailable`), и явный
> `resp.status_code`. `Client.get/post` **не** делают `raise_for_status()` сами —
> решение по статусу принимает адаптер.

### 1.6 Регистрация в dishka (`<feature>/provider.py`)

```python
# internal/features/profile/provider.py
from dishka import Provider, Scope, provide
from pylibinfra.httpclient import Client
from .infra.backend.profile_gateway import HttpProfileGateway
from .infra.backend.identity import IdentityContext
from .usecase import BackendGateway, ProfileUsecase

class ProfileProvider(Provider):
    @provide(scope=Scope.REQUEST)        # REQUEST: identity per-update (§2)
    def gateway(self, client: Client, ident: IdentityContext) -> BackendGateway:
        return HttpProfileGateway(client, ident)

    @provide(scope=Scope.REQUEST)
    def usecase(self, gw: BackendGateway) -> ProfileUsecase:
        return ProfileUsecase(gw)
```

`Client` приходит как `Scope.APP`-синглтон от `HttpClientProvider` (06 §1,
`httpclient/module.py:13`). Адаптер — `Scope.REQUEST`, т.к. в нём живёт per-update
identity (дешёвый объект). Возврат метода = тип `BackendGateway` (порт) → usecase
получает абстракцию (DIP на уровне DI-графа).

---

## 2. Корреляция и контекст (X-Request-ID, identity, tenant)

### 2.1 X-Request-ID — авто-проброс через contextvar

httpclient читает `request_id: ContextVar[str]` (`reqid.py:7`) и, если непусто и
заголовок не задан явно, ставит `X-Request-ID` (`HEADER_REQUEST_ID = "X-Request-ID"`,
`reqid.py:3`; логика — `client.py:84-89`). **Один апдейт = один request-id.**
Ставим его в outer-middleware на входе апдейта:

```python
# internal/platform/middleware/correlation.py
import uuid
from aiogram import BaseMiddleware
from pylibinfra.httpclient import request_id

class CorrelationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        rid = f"tg-{getattr(event, 'update_id', '')}-{uuid.uuid4().hex[:8]}"
        token = request_id.set(rid)      # → подхватится ВСЕМИ исходящими вызовами
        try:
            return await handler(event, data)
        finally:
            request_id.reset(token)
```

> Корреляция «входящий апдейт → вызов бэкенда → его лог/спан» сшивается
> автоматически: тот же contextvar, что заполняет httpkit на входящем HTTP
> (05 §1). Бэкенд видит наш `X-Request-ID` в своих логах.
>
> **Фоновые/push-обработчики** (NATS-подписчик, BgManager) идут вне middleware —
> там `request_id.set(...)` надо вызывать руками в начале обработки события (иначе
> исходящие вызовы пойдут без корреляции). Для NATS трейс уже сшит через
> `traceparent` в headers (05 §3), но `X-Request-ID` ставим сами.

### 2.2 Identity — кто пользователь для бэкенда

Бэкенду нужно знать, от чьего имени запрос. Два режима, инкапсулированы в
`IdentityContext` (REQUEST-scope, читает текущего юзера из aiogram-контекста — 06 §2):

```python
# internal/features/profile/infra/backend/identity.py  (или platform/identity)
class IdentityContext:
    def __init__(self, tg_user_id: int, service_jwt: str | None, tenant: str | None):
        self._tg = tg_user_id
        self._jwt = service_jwt
        self._tenant = tenant

    def headers(self) -> dict[str, str]:
        h = {"X-Tg-User-Id": str(self._tg)}     # (A) trusted-header режим
        if self._jwt:
            h["Authorization"] = f"Bearer {self._jwt}"   # (B) сервисный JWT
        if self._tenant:
            h["X-Tenant-Id"] = self._tenant     # (C) per-tenant
        return h
```

- **(A) tg-user-id заголовком** — простейший режим: бот доверенный фронт, шлёт
  `X-Tg-User-Id`, бэкенд маппит на своего юзера. Подходит, когда бот и бэкенд в
  одной trust-зоне (за `pylibinfra`-инфрой, не наружу).
- **(B) сервисный JWT через authnkit** — бот подписывает короткоживущий токен
  `JWTSigner.sign(claims, ttl)` (`authnkit/jwt.py:27`, 05 §5) с `sub=<backend_user_id>`,
  `act=tg-bot`. Бэкенд верифицирует. Backend_user_id берётся из identity-link
  (deep-link токен, 05 §5: `JWTParser.parse` → сохранили `link:tg:<id>` в Redis).

  ```python
  from pylibinfra.authnkit import JWTSigner
  def issue_service_jwt(signer: JWTSigner, backend_user_id: str) -> str:
      return signer.sign({"sub": backend_user_id, "act": "tg-bot"}, ttl=60.0)
  ```

  > authnkit — **только HS256** (`jwt.py:54`): `JWT_SECRET` бота и бэкенда должны
  > совпадать. Если бэкенд на RS256 — этот кит для sign не подойдёт (05 §5 ⚠️).

- **(C) per-tenant** — `X-Tenant-Id`/`X-Tenant` из контекста юзера (какой бэкенд-
  тенант). Резолв tenant'а — в `platform/identity` (по chat_id / link-записи в
  Redis). Тот же заголовок добавляется ко всем gateway-вызовам.

`IdentityContext` собирается REQUEST-провайдером из `from_user` (06 §2) + Redis-
link + tenant-резолвера:

```python
# platform/identity/provider.py
@provide(scope=Scope.REQUEST)
async def identity(self, obj: TelegramObject, cache: Cache,
                   signer: JWTSigner) -> IdentityContext:
    tg = obj.from_user.id
    backend_uid, _ = await get_json(cache, f"link:tg:{tg}")   # из deep-link (05 §5)
    jwt = issue_service_jwt(signer, backend_uid) if backend_uid else None
    tenant, _ = await get_json(cache, f"tenant:tg:{tg}")
    return IdentityContext(tg, jwt, tenant)
```

---

## 3. Идемпотентность мутаций (POST → бэкенд)

**Проблема:** двойной клик inline-кнопки, ретрай вебхука Telegram, ретрай
httpclient на сетевом таймаоте — каждый может задвоить мутацию (списание,
создание заказа).

**Решение — `Idempotency-Key` на каждый POST/PUT/PATCH к бэкенду.** Бэкенд
дедуплицирует по этому ключу (у бэкенда — `httpkit.IdempotencyMiddleware`,
`httpkit/idempotency.py:37`, заголовок по умолчанию `Idempotency-Key` —
`idempotency.py:25`). Ключ должен быть **стабильным для логически одной операции**:

```python
# internal/features/profile/infra/backend/idempotency.py
import hashlib, json
from pydantic import BaseModel

def make_idem_key(op: str, user_id: str, payload: BaseModel) -> str:
    # стабилен при ретрае той же операции; различается для разных payload.
    body = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode()).hexdigest()[:32]
    return f"{op}:{user_id}:{digest}"
```

Два уровня защиты:

1. **На бэкенде (основной).** Тот же `Idempotency-Key` → бэкенд вернёт
   сохранённый (response, status), не выполнив мутацию повторно. Это закрывает и
   httpclient-ретрай по таймауту, и быстрый повтор от двух кликов.

2. **На боте (опционально, ранний short-circuit).** Если хотим не ходить в сеть
   на явный дубль апдейта/клика — `cachekit.IdempotencyStore` (05 §2,
   `idempotency.py:16`): `get(key) -> (bytes|None, status, found)` / `set(key,
   response, status)`. Боту это **готовый dedup-стор** (05 §2):

   ```python
   from pylibinfra.cachekit import IdempotencyStore

   async def top_up_guarded(store: IdempotencyStore, gw, user_id, req):
       key = make_idem_key("top_up", user_id, req)
       cached, status, found = await store.get(key)
       if found and cached is not None:
           return TopUpResult.model_validate_json(cached)   # вернуть тот же ответ
       result = await gw.top_up(user_id, req)
       await store.set(key, result.model_dump_json().encode(), 200)
       return result
   ```

> **Где какой ключ.** `IdempotencyStore` дедуплицирует на боте *тот же ответ*;
> заголовок `Idempotency-Key` дедуплицирует на *бэкенде*. Для мутаций включаем
> **оба слоя одним и тем же ключом** — тогда даже если бот рестартнул между двумя
> кликами (его кэш холодный), бэкенд всё равно не задвоит. Для **dedup апдейтов
> Telegram** (ретрай вебхука) — отдельный короткий маркер `tg:update:<id>` в Cache
> (05 §2, пример A), это про апдейт, а не про мутацию.

---

## 4. Таблица маппинга ошибок (адаптер `_read` / except-блоки)

Единая точка перевода «транспорт бэкенда → доменная ошибка фичи → user-facing».
User-facing рендерится в delivery (хэндлер/диалог), не в адаптере (01: `mapErr` —
в delivery).

| Источник (httpclient/бэкенд) | Где ловим | Доменная ошибка фичи | User-facing (delivery) |
|---|---|---|---|
| `BreakerOpenError` (`breaker.py:10`) — брейкер открыт, fast-fail | `except` в адаптере | `BackendUnavailable` | «⚙️ Сервис временно занят, попробуйте через минуту» + кнопка «Повторить» |
| `httpx.TimeoutException` | `except` в адаптере | `BackendUnavailable` | то же (для POST — без «успешно», см. §3) |
| `httpx.HTTPStatusError` (исчерпаны ретраи 5xx, `client.py:143`) | `except` в адаптере | `BackendUnavailable` | то же |
| `httpx.TransportError` (сеть, после ретраев) | `except` в адаптере | `BackendUnavailable` | то же |
| HTTP **404** | `_read` по статусу | `ProfileNotFound` (специфична фиче) | «Профиль не найден» |
| HTTP **401/403** | `_read` по статусу | `Unauthorized`/`Forbidden` | «Нужно связать аккаунт» (deep-link) / «Недостаточно прав» |
| HTTP **409/422** (бизнес-конфликт) | `_read`, парсим `code` | `TopUpRejected(reason)` и т.п. | конкретное сообщение по `reason` |
| HTTP **429** (rate-limit бэкенда) | `_read` по статусу | `BackendBusy` | «Слишком часто, подождите» |
| Прочие **4xx** / битый JSON / schema-mismatch | `_read` / `ValidationError` | `BackendBadResponse` | «Что-то пошло не так» + лог с `X-Request-ID` |

> **Принцип маппинга:** *transient* (breaker/timeout/5xx/429) → «попробуйте позже»
> (retryable UX). *Permanent business* (404/409/422) → конкретное сообщение, без
> кнопки «Повторить». *Bug* (битый JSON, неожиданный 4xx) → generic + лог
> `X-Request-ID` для разбора. Бот **обязан** ловить `BreakerOpenError` (05 §1 ⚠️) —
> иначе пользователь увидит «ошибку 500» вместо «сервис занят».

---

## 5. Несколько бэкендов (один Client = один base_url + один breaker)

`Client`/`Config` несут **один** `base_url` (`config.py:15`) и **один** breaker на
инстанс (`BREAKER_NAME="httpclient"`, breaker оборачивает всю retry-цепочку —
`client.py:113-119`). Breaker шарится между всеми хостами одного `Client`. Значит
для **N бэкендов — N Provider'ов** с разными Config (каждый со своим base_url,
таймаутом, порогами брейкера). httpclient-Provider **не** provide'ит Config
(asymmetry note, 06 §1) — Config'и регистрирует прикладной `AppConfigProvider`.

Паттерн «именованный Client per backend» через dishka-провайдеры:

```python
# internal/platform/backends/provider.py
import httpx
from dishka import Provider, Scope, provide
from pylibinfra.httpclient import Client, Config

# отдельные Config-типы → отдельные DI-ключи (разные ENV-префиксы)
class BillingHttpConfig(Config):
    model_config = Config.model_config
    # переопределяем алиасы ENV, чтобы конфиги бэкендов не пересекались
class CatalogHttpConfig(Config): ...

# именованные обёртки над Client → разные DI-ключи (NewType-подход)
from typing import NewType
BillingClient = NewType("BillingClient", Client)
CatalogClient = NewType("CatalogClient", Client)

class BackendsProvider(Provider):
    scope = Scope.APP

    @provide
    async def billing(self, cfg: BillingHttpConfig):
        http = httpx.AsyncClient(timeout=cfg.timeout, base_url=cfg.base_url)
        c = Client(cfg, http)
        yield BillingClient(c)
        await c.aclose()

    @provide
    async def catalog(self, cfg: CatalogHttpConfig):
        http = httpx.AsyncClient(timeout=cfg.timeout, base_url=cfg.base_url)
        c = Client(cfg, http)
        yield CatalogClient(c)
        await c.aclose()
```

Фича-адаптер запрашивает **конкретный** клиент по DI-ключу:

```python
class HttpBillingGateway(BillingGateway):
    def __init__(self, client: BillingClient, ident: IdentityContext) -> None:
        self._client = client      # billing-base_url + billing-breaker, изолирован
```

> **Зачем изоляция breaker'ов:** если billing лёг, его брейкер открыт и режет
> только billing-вызовы; catalog продолжает работать. Один общий `Client` на оба
> = один общий брейкер = деградация одного валит запросы к другому. Поэтому
> **один Provider/Config/Client на бэкенд** — обязательно (05 §1, предупреждение 1).
> ENV: `BILLING_BASE_URL`/`CATALOG_BASE_URL` + свои `*_TIMEOUT`/`*_BREAKER_*`
> (через переопределение `validation_alias` в подклассах Config).

---

## 6. Push-направление (бэкенд → бот)

### 6.1 Вариант A (основной): backend → NATS-событие → подписчик бота

Зеркало `delivery/nats/` (01 §6.1: NATS-subscriber — равноправный вход в usecase).
Подписка — отдельный long-running компонент в том же event-loop, что aiogram
(05 §3 ⚠️), регистрируется в lifespan (аналог `fx.Hook`, 01 §3).

```python
# internal/features/billing/delivery/nats/handler.py
from pylibinfra.natskit import Bus, subscribe_json
from pylibinfra.httpclient import request_id
from .dto import OrderPaidEvent     # pydantic-модель payload события бэкенда

async def register(bus: Bus, bot, bg_factory, cache) -> None:
    async def on_order_paid(evt: OrderPaidEvent) -> None:
        request_id.set(f"evt-{evt.event_id}")          # корреляция (§2.1)
        chat_id, _ = await get_json(cache, f"chat:by-backend-uid:{evt.user_id}")
        if not chat_id:
            return                                     # юзер не связан — молча
        await deliver(bot, bg_factory, chat_id, evt)   # см. ниже
    await subscribe_json(bus, "orders.paid", on_order_paid)
```

Два способа «доставить» пользователю:

**(1) Просто сообщение** — когда у юзера нет открытого диалога / уведомление
самодостаточно:

```python
async def deliver_plain(bot, chat_id: int, evt) -> None:
    await bot.send_message(chat_id, f"✅ Заказ {evt.order_id} оплачен")
```

**(2) Обновить открытый диалог** — через `BgManagerFactory.bg(...)`
(`aiogram-dialog-docs/reference/06`, сигнатура `bg_manager.py:292`):

```python
from aiogram_dialog import StartMode, ShowMode

async def deliver_dialog(bot, bg_factory, chat_id: int, user_id: int, evt) -> None:
    # фабрику получили из setup_dialogs(dp) (06 §2 docs); bot ОБЯЗАТЕЛЕН — у фабрики
    # нет «текущего» bot. user_id/chat_id ОБЯЗАТЕЛЬНЫ.
    bg = bg_factory.bg(bot=bot, user_id=user_id, chat_id=chat_id, load=True)
    # load=True: подгрузить реальный Chat/User, иначе FakeChat.type=="" и AUTO-логика
    # SEND/EDIT работает некорректно (06 docs §7,§9).
    await bg.update({"last_event": evt.model_dump()}, show_mode=ShowMode.EDIT)
    # или, если диалога может не быть, явный старт:
    # await bg.start(OrderSG.paid, mode=StartMode.RESET_STACK)
```

> **Подводные камни push-в-диалог (из 06 docs):**
> - `bg().update()` по **закрытому/пустому стеку** = тихий `logger.warning("No
>   context found")`, без ошибки и без сообщения (`update_handler.py:35-37`). Для
>   «другого чата» `stack_id` по умолчанию = `""` (DEFAULT_STACK_ID) — это другой
>   стек; если нужен конкретный — передавать явно.
> - **Гарантия доставки.** core-NATS — at-most-once: событие, пришедшее пока бот
>   лежал, **потеряно** (05 §3 ⚠️). Если уведомление нельзя терять →
>   **JetStream** (`NATS_JETSTREAM_ENABLED=true`, durable consumer, ack/nak,
>   `subscribe_stream_json` — 05 §3).
> - **Маппинг `backend user_id → chat_id`** natskit не делает — это на боте
>   (Redis: `chat:by-backend-uid:<id>`, заполняется при link-флоу, 05 §5).
> - **Middlewares на фоновых событиях не срабатывают по умолчанию** — навесить на
>   `dispatcher.observers[DIALOG_EVENT_NAME]` (06 docs §5), если рендер диалога
>   зависит от вашей i18n/auth-middleware.
> - **Throttle частоту edit** (flood-limit Telegram) — `bg.update()` возвращается
>   до реального выполнения (`Updater.notify` через `call_soon`), плотный цикл
>   наложится (06 docs §12).

### 6.2 Вариант B (альтернатива): backend → HTTP-эндпоинт бота (webhook-in)

Когда события идут не через NATS, а бэкенд дёргает HTTP-эндпоинт бота. Принимаем
своим FastAPI поверх `pylibinfra.httpkit` (06 §4.2). Это **входящий** слой — тут
бот выступает сервером, а не клиентом:

```python
# internal/platform/webhook_in/router.py  (FastAPI поверх httpkit build_app)
from fastapi import APIRouter, Request, Response, Header
from dishka.integrations.fastapi import FromDishka, inject

router = APIRouter()

@router.post("/internal/events/order-paid")
@inject
async def order_paid(
    request: Request,
    bg_factory: FromDishka[...], bot: FromDishka[...], cache: FromDishka[...],
    x_signature: str = Header(...),          # HMAC-подпись бэкенда (доверие)
) -> Response:
    body = await request.body()
    if not verify_hmac(body, x_signature):   # authnkit/HMAC — НЕ публичный эндпоинт
        return Response(status_code=403)
    evt = OrderPaidEvent.model_validate_json(body)
    chat_id, _ = await get_json(cache, f"chat:by-backend-uid:{evt.user_id}")
    if chat_id:
        await deliver_dialog(bot, bg_factory, chat_id, evt.user_id, evt)
    return Response(status_code=200)
```

> **Идемпотентность webhook-in:** бэкенд шлёт `Idempotency-Key`, на эндпоинте —
> `httpkit.IdempotencyMiddleware` (`httpkit/idempotency.py:37`) поверх
> `cachekit.IdempotencyStore` (replay при дубле). Защита от ретраев бэкенда.
>
> **A vs B:** NATS (A) — loose coupling, JetStream даёт durability, трейс сшит
> автоматически (05 §3); предпочтителен для sftbmb. Webhook-in (B) — когда бэкенд
> не на NATS или нужен синхронный ack доставки; тащит за собой webhook-сервер
> (gap httpkit↔dishka-lifespan описан в 06 §4.2). По умолчанию — **A**.

---

## 7. Деградация (UX при недоступном бэкенде)

Когда `BackendUnavailable` (breaker open / timeout / 5xx) долетает до delivery —
показываем дружелюбную деградацию, не stacktrace.

| Точка входа | Паттерн деградации |
|---|---|
| **Команда / inline-кнопка** | Перехват `BackendUnavailable` в хэндлере → ответ «⚙️ Сервис временно недоступен, попробуйте через минуту» + inline-кнопка «🔄 Повторить» (callback повторяет тот же usecase) |
| **aiogram_dialog (getter)** | getter ловит `BackendUnavailable` → возвращает `{"degraded": True}`; Window рендерит «заглушку» (нет данных + кнопка retry), а не падает в 500 |
| **on_click (мутация)** | при `BackendUnavailable` — `callback.answer("Не удалось, попробуйте ещё раз", show_alert=True)`, диалог **не** переключается (state не меняется) |
| **Stale-while-degraded** | если в Cache есть прошлый ответ (`get_json(cache, "profile:<id>")`) — показать его с пометкой «данные могут быть неактуальны», вместо пустого экрана |
| **Push (NATS/webhook)** | при недоступном `Bot.send_message` (Telegram) — лог + (для JetStream) `nak` → переотправка; не ронять подписчик (panic-recovery natskit, 05 §3) |

Принцип: **fail-soft для transient, fail-fast для permanent**. Breaker (открытый
после `failure_threshold=5` фейлов, `recovery_timeout=30s` —
`breaker.py:21,25`) даёт быстрый отказ без подвисания на таймаутах — это и есть
backpressure-защита: при лежащем бэкенде юзеры мгновенно получают «занято», а не
ждут 10s timeout каждый. После `recovery_timeout` брейкер пробует half-open
(`success_threshold=3` — `breaker.py:28`) и сам восстанавливается.

```python
# internal/features/profile/delivery/handlers/profile.py
@router.message(Command("profile"))
@inject
async def show_profile(message, uc: FromDishka[ProfileUsecase]):
    try:
        p = await uc.show_profile(str(message.from_user.id))
    except BackendUnavailable:
        await message.answer("⚙️ Сервис временно занят. Попробуйте через минуту.",
                             reply_markup=retry_kb())          # fail-soft
        return
    except ProfileNotFound:
        await message.answer("Профиль не найден. /link для привязки.")  # fail-fast
        return
    await message.answer(render_profile(p))
```

---

## 8. Последовательности

### 8.1 Входящий апдейт → gateway → ответ

```
Telegram Update
  → aiogram Dispatcher
  → CorrelationMiddleware: request_id.set("tg-<update_id>-<rnd>")   (§2.1)
  → dishka REQUEST-scope (06 §2): резолв IdentityContext (§2.2), Usecase, Gateway
  → handler/on_click (@inject): uc.show_profile(user_id)
      → usecase зовёт BackendGateway.get_profile  (порт, §1.3)
      → HttpProfileGateway: client.get(url, headers=identity.headers())  (§1.5)
          → httpclient.Client: breaker→retry→httpx; X-Request-ID авто (client.py:84)
          → backend отвечает (200 / 4xx / 5xx)
      → _read: статус→DTO или доменная ошибка (§4)
  → delivery: рендер вью ИЛИ деградация (§7)
  → REQUEST-scope закрывается; request_id.reset() в finally middleware
```

### 8.2 Backend-событие → push

```
backend выполнил мутацию
  → publish "orders.paid" в NATS (traceparent в headers)            (05 §3)
  → natskit subscriber бота (long-running, lifespan):  on_order_paid(evt)
      → request_id.set("evt-<id>")                                   (§2.1)
      → cache: chat:by-backend-uid:<user_id> → chat_id              (§6.1)
      → deliver:
          (a) bot.send_message(chat_id, ...)                         простое
          (b) bg_factory.bg(bot, user_id, chat_id, load=True)        в диалог
                → .update({...}, show_mode=EDIT)  →  Updater.notify
                → искусственный aiogd_update через Dispatcher        (06 docs §5)
                → handle_update поднимает реальный DialogManager
                → MessageManager.show_message: edit / send / delete  (06 docs §8)
  (JetStream: успех→msg.ack(); ошибка handler→msg.nak() переотправка)
```

---

## Сухой остаток (что фиксируем в шаблоне)

1. **Порт `BackendGateway` (Protocol) в `<feature>/usecase.py`**, адаптер
   `Http*Gateway` над `httpclient.Client` в `<feature>/infra/backend/`, регистрация
   в `<feature>/provider.py` (dishka). Usecase зависит от порта, не от httpx (DIP),
   DTO фичи изолируют от формы JSON бэкенда (anti-corruption).
2. **Адаптер — единственная точка маппинга** транспорт→домен: `BreakerOpenError`/
   timeout/5xx → `BackendUnavailable`; 404/409/422 → специфичные ошибки фичи;
   user-facing рендерит delivery (§4).
3. **Корреляция через `request_id` contextvar** (авто-`X-Request-ID`), identity —
   `X-Tg-User-Id` или сервисный HS256-JWT (authnkit), per-tenant заголовком; всё в
   REQUEST-scope `IdentityContext`.
4. **Идемпотентность мутаций — стабильный `Idempotency-Key`** (хэш payload):
   дедуп на бэкенде (`httpkit`) + опц. ранний short-circuit на боте
   (`cachekit.IdempotencyStore`).
5. **Один бэкенд = один Provider/Config/Client/breaker** (изоляция деградации);
   N бэкендов — N именованных Client'ов по DI-ключу.
6. **Push: NATS-подписчик (A, по умолчанию) → `Bot.send_message` или
   `BgManagerFactory.bg().update/start`**; webhook-in (B) — альтернатива через
   httpkit. JetStream для durability. Деградация: fail-soft (retry-UX/stale-cache)
   для transient, fail-fast для permanent.
```
