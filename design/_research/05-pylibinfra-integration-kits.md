# Зона E — integration-киты pylibinfra (для telegram-bot-template)

> Источник: `/root/git/sftbmb/sftbmb-core/pylibinfra/src/pylibinfra/<kit>/`.
> Бот — «фронтенд»: бизнес-логика на бэкендах, бот ходит к ним по HTTP, держит
> свой state в Redis, ловит события из NATS, кладёт медиа в S3.
>
> Общие конвенции всех китов:
> - **Config — `pydantic_settings.BaseSettings`** с `validation_alias` = ENV-имя
>   (`populate_by_name=True`, `extra="ignore"`). Все TTL/таймауты — **float-секунды**.
> - **Provider'ы НЕ provide'ят свой `Config`** («asymmetry note») — caller сам
>   регистрирует Config в DI; для «дешёвого» режима есть фабрика `new_config()`.
> - Все Provider'ы — `Scope.APP` (синглтоны на процесс).
> - OTel-метрики/спаны эмитятся через глобальный provider (`telemetry.init`);
>   без него инструментация — no-op.

---

## 1. httpclient — backend-gateway (ИСХОДЯЩИЙ клиент к бэкендам)

Путь: `pylibinfra/httpclient/` (`client.py`, `breaker.py`, `reqid.py`, `metrics.py`, `config.py`, `module.py`).

httpx-клиент с retry (tenacity, экспон. backoff + джиттер), circuit breaker
(purgatory), OTel-спанами и **авто-прокидыванием `X-Request-ID`** из contextvar.

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `Client` | `__init__(cfg: Config, http: httpx.AsyncClient)`; async-context-manager (`__aenter__/__aexit__`) | `client.py:59` |
| `Client.request` | `async request(method, url, **kwargs) -> httpx.Response` — ядро: инжектит `X-Request-ID`, спан `HTTP <method>`, метрика длительности | `client.py:82` |
| `Client.get/post` | `async get(url, **kwargs)` / `async post(url, **kwargs)` — обёртки над `request` | `client.py:76,79` |
| `Client.aclose` | `async aclose()` — закрывает внутренний httpx-клиент | `client.py:67` |
| `Config` | `timeout=10.0`, `max_retries=3`, `retry_wait=0.2`, `base_url=""`, `breaker: BreakerConfig` | `config.py:7` |
| `BreakerConfig` | `failure_threshold=5`, `recovery_timeout=30.0`, `success_threshold=3` | `breaker.py:18` |
| `BreakerOpenError` | алиас `purgatory ... OpenedState` — чем фейлит открытый брейкер до transport | `breaker.py:10` |
| `HEADER_REQUEST_ID` | `"X-Request-ID"` | `reqid.py:3` |
| `request_id` | `ContextVar[str]` (default `""`) — источник X-Request-ID для исходящих | `reqid.py:7` |
| `HttpClientProvider` | dishka Provider, provide'ит `Client` (resource c lifecycle) | `module.py:13` |
| `new_config()` / `new_breaker_config()` | фабрики Config | `module.py:27,31` |

### Поведение (важно для бота)

- **X-Request-ID** (`client.py:82-89`): `request()` читает `request_id.get()`;
  если непусто и заголовок ещё не задан явно — ставит `X-Request-ID`. Явный
  заголовок приоритетнее contextvar. **httpkit (входящий слой) заполняет тот же
  contextvar `pylibinfra.httpclient.reqid.request_id`** — значит корреляция
  «входящий апдейт → исходящий вызов бэкенда» работает, если бот при обработке
  апдейта установит этот contextvar.
- **Retry** (`client.py:121-148`): ретраит `httpx.TransportError` и HTTP `>=500`
  (`_RetryableStatus`); `stop_after_attempt(max_retries+1)`, backoff
  `base*2**attempt + rand(0,base)`. 4xx **не** ретраятся. Исчерпание ретраев на
  5xx → `httpx.HTTPStatusError` (и брейкер засчитывает фейл).
- **Circuit breaker** (`client.py:113-119`): брейкер оборачивает **всю**
  retry-последовательность; открыт → быстрый фейл `BreakerOpenError` без обращения
  к сети. Бот **обязан** ловить `BreakerOpenError` и показывать «бэкенд недоступен,
  попробуйте позже» вместо 500.
- **OTel патчится глобально один раз** (`HTTPXClientInstrumentor`, `_instrument_once`),
  плюс ручной спан на запрос. Метрики: `http_client_request_duration_seconds`,
  `http_client_breaker_transitions_total`, `http_client_breaker_open`,
  `http_client_retry_attempts_total`.

### Provider/lifecycle

`HttpClientProvider.client` (`module.py:16-24`) создаёт `httpx.AsyncClient(timeout, base_url)`,
оборачивает в `Client`, `yield` и на shutdown `aclose()`. Scope APP → один клиент
на бота.

### Пример (бот → бэкенд)

```python
from pylibinfra.httpclient import Client, BreakerOpenError, request_id

# в middleware/хендлере апдейта: задать корреляцию (один X-Request-ID на апдейт)
request_id.set(f"tg-{update.update_id}")

async def get_profile(client: Client, tg_user_id: int) -> dict:
    try:
        resp = await client.get(f"/api/v1/users/by-tg/{tg_user_id}")
        resp.raise_for_status()        # 4xx не ретраился — обрабатываем сами
        return resp.json()
    except BreakerOpenError:
        raise BackendUnavailable()     # показать «сервис недоступен»
```

> ⚠️ `base_url` берётся из `HTTPCLIENT_BASE_URL`. Если бот ходит к **нескольким**
> бэкендам, один `Client`/один `base_url` не хватит — нужно регистрировать
> несколько Provider'ов с разными Config (по DI-ключу/тегу) или передавать
> абсолютные URL. Также breaker — **один на инстанс Client** (`BREAKER_NAME="httpclient"`),
> т.е. шарится между всеми хостами этого клиента.

---

## 2. cachekit — FSM-state + idempotency (Redis)

Путь: `pylibinfra/cachekit/` (`cache.py`, `idempotency.py`, `config.py`, `module.py`).

Redis-обёртка: порт `Cache`, generic `get_json[T]/set_json[T]`, tag-инвалидация,
и `IdempotencyStore` (то, что httpkit использует для повторов; боту полезно для
**дедупликации `update_id`**).

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `Cache` (Protocol) | `get(key)->(bytes\|None,bool)`, `set(key,value,ttl=None,*,tags=())`, `delete(*keys)`, `invalidate_by_tag(tag)`, `ping()` | `cache.py:18` |
| `RedisCache` | боевая реализация `Cache` поверх `redis.asyncio` (тег → set ключей с TTL) | `cache.py:34` |
| `get_json[T]` | `async get_json(cache, key) -> (T\|None, bool)` — generic free-функция | `cache.py:82` |
| `set_json[T]` | `async set_json(cache, key, value, ttl=None, *, tags=())` | `cache.py:90` |
| `IdempotencyStore` (Protocol) | `get(key)->(bytes\|None, int, bool)` (response, status, found), `set(key, response, status)` | `idempotency.py:16` |
| `CacheIdempotencyStore` | реализация поверх `Cache`, ключ `idempotency:<key>`, TTL из конфига, response в base64-JSON | `idempotency.py:22` |
| `Config` | `url=redis://localhost:6379/0` (`REDIS_URL`), `pool_size=10`, `dial/read/write_timeout`, `idempotency_ttl=86400` | `config.py:5` |
| `CachekitProvider` | provide'ит `redis.Redis` (lifecycle), `Cache`→`RedisCache`, `IdempotencyStore`→`CacheIdempotencyStore` | `module.py:17` |
| `probe(cache)` | фабрика health-probe (`await cache.ping()`); **не** provide'ится в DI (тип коллизит) | `module.py:43` |
| `new_config()` | фабрика Config | `module.py:50` |

### Поведение

- `RedisCache.set` с `tags=` кладёт ключ в set `tag:<tag>` и ставит set'у тот же TTL;
  `invalidate_by_tag` удаляет все ключи тега разом. Удобно «сбросить кэш юзера»
  по тегу `user:<id>`.
- `get_json`/`set_json` — **free-функции, не методы** (`T` у `get_json` выводится
  из аннотации call-site, не из аргументов): `v: tuple[Foo|None, bool] = await get_json(cache, key)`.
- `IdempotencyStore` хранит пару (response-bytes, status) под TTL — изначально для
  httpkit-идемпотентности, но **для бота это готовый dedup-стор**.

### Provider/lifecycle

`CachekitProvider.client` (`module.py:20-32`): `RedisInstrumentor().instrument()`
(спаны redis-команд), `redis.from_url(url, max_connections=pool_size, ...timeouts)`,
`yield`, на shutdown `aclose()`. `Cache` и `IdempotencyStore` — производные provide'ы.

### Пример A — дедупликация Telegram `update_id`

```python
from datetime import timedelta
from pylibinfra.cachekit import Cache

async def already_seen(cache: Cache, update_id: int) -> bool:
    key = f"tg:update:{update_id}"
    _data, found = await cache.get(key)
    if found:
        return True                         # дубль апдейта — пропускаем
    # маркер на короткий TTL (Telegram ретраит апдейты при таймаутах вебхука)
    await cache.set(key, b"1", timedelta(minutes=10))
    return False
```

> Альтернатива через `IdempotencyStore` (хранит и сам ответ):
> `store.get(f"update:{update_id}")` → если `found`, отдать сохранённый результат;
> иначе обработать и `store.set(...)`. Подходит, когда дубль должен вернуть тот же
> ответ, а не просто игнорироваться.

### Пример B — FSM/диалоговый state

```python
import json
from datetime import timedelta
from pylibinfra.cachekit import Cache, get_json, set_json

async def save_fsm(cache: Cache, chat_id: int, state: dict) -> None:
    await set_json(cache, f"fsm:{chat_id}", state, timedelta(hours=1),
                   tags=[f"user:{state['user_id']}"])

async def load_fsm(cache: Cache, chat_id: int) -> dict | None:
    value, found = await get_json(cache, f"fsm:{chat_id}")  # value: dict|None
    return value if found else None
```

> ⚠️ aiogram-storage для FSM ожидает свой интерфейс (`BaseStorage`). cachekit даёт
> **только `redis.Redis`/`Cache`**, не aiogram-`RedisStorage`. Бот может либо
> отдать `redis.Redis` напрямую в `aiogram.fsm.storage.redis.RedisStorage`, либо
> хранить state «руками» через `Cache`/`get_json`/`set_json` (см. пример). Шарить
> один `redis.Redis`-инстанс между aiogram-storage и cachekit — нормально.

---

## 3. natskit — notifications (события бэкенда → сообщение в Telegram)

Путь: `pylibinfra/natskit/` (`bus.py`, `jetstream.py`, `conn.py`, `instrumentation.py`,
`config.py`, `module.py`).

pub/sub поверх NATS: `Bus` (core NATS, at-most-once), опц. JetStream (durable,
at-least-once с ack/nak), backpressure через `asyncio.Semaphore`, panic-recovery
в подписчиках, **W3C trace-context в nats-headers**.

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `Bus` (Protocol) | `publish(subject, payload: Any)`, `subscribe(subject, handler: Handler)` | `bus.py:22` |
| `Handler` | `Callable[[bytes], Awaitable[None]]` | `bus.py:19` |
| `NatsBus` | боевая реализация `Bus`; sem-backpressure, держит ссылки на handler-таски | `bus.py:27` |
| `publish_json[T]` | `async publish_json(bus, subject, msg: T)` | `bus.py:101` |
| `subscribe_json[T]` | `async subscribe_json(bus, subject, handler: Callable[[T], Awaitable[None]])` — JSON-decode за тебя | `bus.py:105` |
| `Conn` | обёртка над `nats.aio.client.Client`; `.raw`, `.healthy()` | `conn.py:9` |
| `new_conn(cfg)` | `async` — поднять соединение (без DI) | `conn.py:22` |
| `StreamBus` (Protocol) | `publish_stream(subject, payload: bytes)`, `subscribe_stream(stream, subject, durable, handler)` | `jetstream.py:29` |
| `JsBus` / `DisabledStreamBus` | JetStream-реализация / no-op (когда выключено, кидает `JetStreamDisabledError`) | `jetstream.py:46,36` |
| `publish_stream_json[T]` / `subscribe_stream_json[T]` | JSON-обёртки для JetStream (durable consumer) | `jetstream.py:173,178` |
| `Config` | `url=nats://localhost:4222` (`NATS_URL`), `connect_timeout`, `reconnect_wait`, `max_reconnects=60`, `backpressure`, `jetstream` | `config.py:24` |
| `BackpressureConfig` | `max_in_flight=100` (`NATS_MAX_IN_FLIGHT`) | `config.py:5` |
| `JetStreamConfig` | `enabled=False` (`NATS_JETSTREAM_ENABLED`), `stream_names`, `retention`, `max_age`, `max_in_flight`, `ack_wait` | `config.py:11` |
| `NatsProvider` | provide'ит `Conn` (lifecycle с `drain()`), `Bus`→`NatsBus`, `StreamBus` | `module.py:18` |
| `probe(conn)` / `new_bus(...)` / `new_config()` | health-probe (не provide'ится) / фабрики | `module.py:47,54,43` |

### Поведение (важно для бота)

- **`NatsBus.subscribe`** (`bus.py:59-66`): каждое сообщение обрабатывается в
  отдельной таске под семафором `max_in_flight`; **handler-ошибка НЕ валит
  подписку** (panic-recovery, лог + error-спан, `bus.py:78-92`). Для core NATS
  **нет ack/повтора** — потерянное сообщение потеряно.
- **JetStream** (`jetstream.py`): durable consumer (`durable_name`), `EXPLICIT`
  ack — успех → `msg.ack()`, ошибка handler'а → `msg.nak()` (переотправка).
  `ensure_streams` создаёт стримы `<name>.>` на старте. **Если боту нужна гарантия
  доставки уведомления** (не пропустить событие, пока бот лежал) — нужен JetStream
  с durable, иначе сообщения, пришедшие в даунтайм, потеряются.
- **Trace-context** (`instrumentation.py`): producer инжектит `traceparent` в
  headers, consumer извлекает → consumer-спан child producer-спана. Бэкенд-→бот
  трейс сшивается автоматически.
- Метрики: `nats_messages_{published,consumed}_total`,
  `nats_{publish,handle}_duration_seconds`, `nats_inflight_messages`.

### Provider/lifecycle

`NatsProvider.conn` (`module.py:21-32`): `nats.connect(...)`, `yield Conn`, на
shutdown `nc.drain()` (дослать/долучить in-flight). `bus` → `NatsBus`,
`stream_bus` → `new_stream_bus` (вернёт `DisabledStreamBus`, если JetStream off).

### Пример — подписка на событие бэкенда → сообщение в Telegram

```python
from aiogram import Bot
from pylibinfra.natskit import Bus, subscribe_json

async def setup_notifications(bus: Bus, tg: Bot, cache) -> None:
    async def on_order_paid(evt: dict) -> None:
        # evt пришёл от бэкенда; маппим backend-user → tg chat_id (см. authnkit/identity-link)
        chat_id = await resolve_chat_id(cache, evt["user_id"])
        if chat_id:
            await tg.send_message(chat_id, f"Заказ {evt['order_id']} оплачен ✅")
    await subscribe_json(bus, "orders.paid", on_order_paid)
    # подписки регистрируются один раз на старте (long-running)
```

> ⚠️ Подписка живёт, пока жив процесс/соединение. Это **отдельный long-running
> компонент** рядом с aiogram-polling/webhook — его надо запустить и держать в
> том же event-loop, а на shutdown дать `Conn.drain()` отработать. Маппинг
> `backend user_id → telegram chat_id` natskit не делает — это на боте (Redis/бэкенд).

---

## 4. storagekit — media (медиа в S3)

Путь: `pylibinfra/storagekit/` (`storage.py`, `config.py`, `module.py`, `url_builder.py`,
`s3/uploader.py`, `s3/module.py`, `memory.py`).

S3-совместимое хранилище (aioboto3, MinIO через `endpoint_url`). Доменно-нейтрально:
валидация mime/размера/декода — на стороне бота.

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `Storage` (Protocol) | `put(data: bytes, content_type: str) -> Ref`, `delete(key: str)` | `storage.py:27` |
| `Ref` | frozen dataclass: `key`, `url` (публичный, не протухает), `content_type`, `size` | `storage.py:16` |
| `new_key(content_type)` | `<uuidv7>.<ext>` — k-sortable ключ; ext по mime (jpg/png/webp/pdf) | `storage.py:34` |
| `URLBuilder` | `build(key) -> "<base>/<bucket>/<key>"` | `url_builder.py:1` |
| `Uploader` | боевой `Storage` поверх aioboto3 (`put_object`/`delete_object`) | `s3/uploader.py:15` |
| `MemoryStorage` | in-memory адаптер для тестов | `memory.py` |
| `Config` | `endpoint`, `access_key`, `secret_key`, `bucket`, `use_ssl=False`, `public_base_url`, `region=us-east-1` (env `STORAGE_S3_*`, `STORAGE_PUBLIC_BASE_URL`) | `config.py:5` |
| `StoragekitProvider` | provide'ит `URLBuilder`, s3-client (lifecycle), `Storage`→`Uploader` | `module.py:15` |
| `StorageError`/`ErrNotFound`/`ErrUploadFailed` | ошибки | `errors.py` |
| `new_config()` | фабрика Config | `module.py:32` |

### Поведение

- `put` сам генерит ключ (`new_key`) и возвращает `Ref` с **готовым публичным
  URL** (`<public_base_url>/<bucket>/<key>`) — read-side читает напрямую, без
  presigned-URL. `delete` маппит `NoSuchKey/404` → `ErrNotFound`.
- `new_s3_client` требует непустые `STORAGE_S3_ENDPOINT` и `STORAGE_S3_BUCKET`
  (иначе `ValueError` на старте Provider'а).

### Provider/lifecycle

`StoragekitProvider.s3_client` (`module.py:22-25`) — async-with на aioboto3-клиент
(`new_s3_client`), `Storage`→`Uploader` через `new_uploader`.

### Пример — фото из Telegram → S3 → URL на бэкенд

```python
from pylibinfra.storagekit import Storage

async def upload_tg_photo(storage: Storage, tg, file_id: str) -> str:
    file = await tg.get_file(file_id)
    buf = await tg.download_file(file.file_path)   # bytes
    ref = await storage.put(buf.read(), content_type="image/jpeg")
    return ref.url     # стабильный URL → отдаём бэкенду в HTTP-запросе
```

> ⚠️ storagekit пишет **байты как есть** — mime/размер/«это правда картинка»
> валидирует бот. Telegram-медиа можно качать и так (`getFile`), S3 нужен, только
> если боту надо **отдать бэкенду стабильный URL** или хранить медиа независимо
> от Telegram-CDN. Для многих ботов это опционально.

---

## 5. authnkit — identity-link (JWT, RBAC; связь tg-user ↔ backend)

Путь: `pylibinfra/authnkit/` (`jwt.py`, `hasher.py`, `totp.py`, `permissions.py`, `module.py`).

Криптокирпичики: JWT sign/verify (HS256), Argon2id-hasher, TOTP, RBAC. Auth-flow
(login/refresh/MFA) — на consumer'е.

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `JWTSigner`/`JWTParser` (Protocol) | `sign(claims: dict, ttl: float) -> str` / `parse(token) -> dict` | `jwt.py:27,32` |
| `HS256JWT` | реализация обоих портов; `sign` добавляет `iat`/`exp` | `jwt.py:54` |
| `JWTConfig` | `secret` (`JWT_SECRET`, обязателен), `access_ttl=900`, `refresh_ttl=2592000` | `jwt.py:18` |
| `ErrTokenExpired/Signature/Malformed`, `TokenError` | sentinel-ошибки (изоляция от pyjwt) | `jwt.py:37-51` |
| `Hasher` (Protocol) | `hash(plain)->str`, `verify(plain, encoded)->bool` | `hasher.py:19` |
| `Argon2idHasher` / `Argon2idParams` | Argon2id поверх argon2-cffi; params `ARGON2_*` | `hasher.py:35,25` |
| `TOTPGenerator` | `generate(account_name)->(secret, otpauth_url)`, `verify(secret, code)->bool` | `totp.py:8` |
| `Permission`/`PermissionSet`/`RolePermissions` | `str` / `frozenset` / `dict` | `permissions.py:10-12` |
| `register_role_permissions(role, *perms)` / `has(role, perm)->bool` | глобальный RBAC-реестр (thread-safe) | `permissions.py:18,23` |
| `AuthnProvider` | provide'ит `Hasher`, и `HS256JWT` под `AnyOf[JWTSigner, JWTParser]` | `module.py:10` |
| `new_argon2id_params()` / `new_jwt_config()` | фабрики | `module.py:22,26` |

### Поведение (для бота)

- Для **identity-link** боту полезен в первую очередь `JWTParser.parse` (verify
  токена бэкенда) и/или `JWTSigner.sign` (выпустить собственный токен сессии).
  Один `HS256JWT`-инстанс отдаётся под оба порта (`AnyOf`).
- `Hasher`/`TOTP` боту обычно **не нужны** (пароли/MFA — на бэкенде), если бот не
  делает свою авторизацию.
- RBAC-реестр **глобальный**: `register_role_permissions` на старте, `has` в
  рантайме.

### Пример — verify deep-link токена связывания аккаунта

```python
from pylibinfra.authnkit import JWTParser, ErrTokenExpired, TokenError

async def link_account(parser: JWTParser, cache, tg_user_id: int, token: str):
    # пользователь пришёл по ссылке t.me/bot?start=<jwt> с бэкенда
    try:
        claims = parser.parse(token)        # verify подписи+exp
    except (ErrTokenExpired, TokenError):
        raise InvalidLink()
    backend_user_id = claims["sub"]
    await cache.set(f"link:tg:{tg_user_id}", backend_user_id.encode())
```

> ⚠️ Секрет JWT (`JWT_SECRET`) должен совпадать с бэкендом — HS256 симметричный.
> Если бэкенд подписывает RS256/asymmetric, этот кит (только HS256) **не
> подойдёт** для verify — понадобится свой парсер.

---

## 6. bruteforcekit — anti-spam guard

Путь: `pylibinfra/bruteforcekit/` (`guard.py`, `config.py`, `module.py`, `pgstore/*`).

Счётчик неудачных попыток per-subject + per-IP; при превышении порога — lockout.
**Core отделён от хранилища; боевой `Store` — PgStore (Postgres).**

### Публичный API

| Символ | Сигнатура / суть | Файл |
|---|---|---|
| `Guard` | `check(subject, ip)->LockState\|None`, `record_failure`, `record_success`, `cleanup` | `guard.py:31` |
| `LockState` | frozen dataclass `until: datetime` | `guard.py:13` |
| `Store` (Protocol) | `read`, `record_failure`, `reset`, `cleanup` (сырой `locked_until`, решение об истечении — у Guard через `Clock`) | `guard.py:18` |
| `Config` | `max_failures=5`, `lock_duration=900`, `window=3600`, `cleanup_retention=86400` (env `BRUTEFORCE_*`) | `config.py:5` |
| `BruteforceProvider` | provide'ит `Guard(store, clock)` — **`Store` и `Clock` нужны извне** | `module.py:12` |
| `PgStore` / `BruteforcePgstoreProvider` | боевой `Store` поверх `pgkit.DB` (таблица `bruteforce_attempts`) | `pgstore/store.py:35`, `pgstore/module.py:12` |
| `new_config()` | фабрика Config | `module.py:20` |

### Поведение

- `Guard.check` (`guard.py:36-40`): читает `locked_until`, сравнивает с `clock.now()`;
  если в будущем — `LockState`. `record_failure`/`record_success` инкремент/сброс.
- `Guard` зависит от `clockkit.Clock` (тестируемость) **и** от `Store`.
- **Единственная боевая реализация Store — Postgres** (`PgStore`, SQL c
  `make_interval`, `ON CONFLICT`). In-memory фейк есть только в
  `testkit/bruteforcetest`.

> ⚠️ **Для бота это главный «джокер»**: bruteforcekit боевым ходом **тянет
> Postgres** (через `pgkit.DB`). Если боту нужен только rate-limit/anti-spam на
> апдейты — дешевле сделать свой счётчик в Redis (`cachekit` + `INCR`/TTL), чем
> ради anti-spam поднимать Postgres. bruteforcekit оправдан, только если бот сам
> держит login-эндпойнты (редко). Альтернатива — реализовать `Store`-порт поверх
> Redis самим (порт минимальный: 4 метода).

---

## 7. pgkit — обычно НЕ нужен боту

Путь: `pylibinfra/pgkit/` (`db.py`, `pool.py`, `migrate.py`, `module.py`, …).

DB-фасад поверх asyncpg: пул, `Transactor` (contextvars-tx), маппинг pg-ошибок,
migrate-runner (yoyo), health-probe, read-replica, `db_pool_*` метрики.

| Символ | Суть | Файл |
|---|---|---|
| `DB` | `execute/fetch/fetchrow/fetchval(sql, *args)` — фасад над пулом/tx | `db.py:9` |
| `Transactor`/`PoolTransactor`/`conn` | транзакции через contextvar | `transactor.py` |
| `PgProvider` | provide'ит `Pool` (lifecycle), `DB`, `Transactor`, read-replica | `module.py:23` |
| `migrate_up`/`MigrateConfig` | yoyo-миграции | `migrate.py` |
| `PoolConfig`/`ReplicaConfig` | DSN/пул-конфиги | `pool.py`, `replica.py` |

**Вердикт для бота: Postgres НЕ нужен.** State бота — в Redis (cachekit), бизнес-данные
— на бэкендах (через httpclient), события — в NATS. Бот ничего своего долговременно
в реляционке не держит. **Единственное, что притащило бы pgkit — это
bruteforcekit.PgStore** (см. §6); если anti-spam делать на Redis, pgkit боту не
нужен совсем.

---

## 8. testkit — для интеграционных тестов бота

Путь: `pylibinfra/testkit/` (`redis.py`, `nats.py`, `postgres.py`, подпакеты).

testcontainers-обёртки + per-kit in-memory фейки. **API framework-agnostic**
(async context-manager'ы, не завязан на pytest).

| Символ | Суть | Файл |
|---|---|---|
| `start_redis()` → `RedisFixture` | поднимает `redis:7-alpine`; `.url`, `.cache()` → `RedisCache` | `redis.py:35` |
| `start_nats()` → `NatsFixture` | поднимает `nats:2-alpine`; `.url`, `.bus()` → `NatsBus` | `nats.py:33` |
| `start_postgres()` → `PostgresFixture` | контейнер Postgres (боту обычно не нужен) | `postgres.py` |
| `eventbus.Recorder` | in-memory фейк `Bus`/`Publisher`: `publish`, `published(subject)`, `last`, `count` — для ассертов без NATS | `eventbus/recorder.py:17` |
| `handlertest` | FastAPI-приложение + httpx **ASGI**-клиент (без сети) + ассерты по Problem+JSON | `handlertest/client.py` |
| `bruteforcetest`, `authntest`, `audittest`, `txkit` | per-kit фейки/ассерты | подпакеты |

### Что брать боту

- **`start_redis()`** — интеграционные тесты FSM/dedup/idempotency на реальном Redis.
- **`start_nats()`** + **`eventbus.Recorder`** — тесты подписок: `Recorder` для
  unit-проверки «бот отправил правильное событие», `start_nats()` для end-to-end
  «событие пришло → бот вызвал send_message» (send_message мокается).
- `handlertest` создаёт FastAPI-приложение — это про httpkit-**сервер**; боту-фронтенду
  напрямую не нужно (бот httpx-**клиент**), но ASGI-паттерн полезен для мока бэкенда.

```python
import pytest
from pylibinfra.testkit import start_redis

@pytest.mark.asyncio
async def test_update_dedup():
    async with start_redis() as fx, fx.cache() as cache:
        assert await already_seen(cache, 42) is False
        assert await already_seen(cache, 42) is True   # дубль
```

---

## Маппинг: кит → роль в боте

| Кит | Роль в боте | Обяз./опц. | Притаскивает |
|---|---|---|---|
| **httpclient** | **backend-gateway** — все вызовы к бэкендам (retry, breaker, X-Request-ID) | **обязателен** | httpx, tenacity, purgatory, OTel |
| **cachekit** | **FSM-state + idempotency** — диалоговый state + dedup `update_id` | **обязателен** | Redis |
| **natskit** | **notifications** — события бэкенда → сообщение в Telegram | **обязателен** (если есть push-уведомления) / опц. (если бот чисто request-response) | NATS (опц. JetStream) |
| **storagekit** | **media** — Telegram-фото/файлы → S3, стабильный URL для бэкенда | **опционально** — только если нужен внешний стабильный URL | aioboto3, S3/MinIO |
| **authnkit** | **identity-link** — verify/sign JWT для связки tg-user ↔ backend (deep-link токены) | **опционально** (только `JWT*`; Hasher/TOTP почти никогда) | pyjwt; HS256-only |
| **bruteforcekit** | **anti-spam** на login-эндпойнты | **редко** — боту обычно не нужен; тянет Postgres | **Postgres** (через pgkit) |
| **pgkit** | реляционное хранилище | **НЕ нужен** — state в Redis, данные на бэкендах | asyncpg |
| **testkit** | интеграционные тесты (Redis/NATS контейнеры, фейки) | dev-зависимость | testcontainers |

### Минимальный обязательный набор бота
`httpclient` + `cachekit` + (`natskit`, если есть push-уведомления). Всё остальное
— опционально и подключается по необходимости.

### 3–4 предупреждения

1. **httpclient: один `base_url` и один breaker на инстанс `Client`.** Для
   нескольких бэкендов — несколько Provider'ов/Config (по DI-ключу), иначе breaker
   шарится между хостами и retry/timeout одинаковы для всех. Бот **обязан** ловить
   `BreakerOpenError` (иначе пользователь видит «ошибку 500» вместо «сервис занят»).
2. **cachekit не даёт aiogram-`BaseStorage`.** Кит отдаёт `redis.Redis`/`Cache`, а
   не aiogram-`RedisStorage`. Либо передать `redis.Redis` в aiogram-storage напрямую,
   либо вести FSM руками через `Cache`/`get_json`/`set_json`. Для dedup `update_id`
   ставить **короткий TTL** (Telegram ретраит апдейты при таймаутах вебхука).
3. **natskit core-NATS — at-most-once: сообщения в даунтайм бота теряются.** Если
   уведомление нельзя терять — нужен **JetStream** (`NATS_JETSTREAM_ENABLED=true`,
   durable consumer, ack/nak). Подписки — отдельный long-running компонент в том же
   event-loop, что и aiogram; на shutdown дать `Conn.drain()` отработать. Маппинг
   `backend user_id → chat_id` natskit не делает — это на боте.
4. **bruteforcekit тянет Postgres** (единственный боевой `Store` — `PgStore`/pgkit).
   Ради anti-spam/rate-limit на апдейты дешевле свой счётчик в Redis (`cachekit`
   `INCR`+TTL) или собственная реализация `Store`-порта (4 метода) поверх Redis,
   чем поднимать Postgres исключительно под bruteforce. **authnkit — только HS256**:
   если бэкенд подписывает токены RS256, verify через `HS256JWT` не сработает.
