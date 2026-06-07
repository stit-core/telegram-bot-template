# 10 — Модель состояния и данных бота (зона J)

> Бот = **фронтенд**. Единственное, что он легитимно хранит, — это **свой**
> state: FSM/диалоги, dialog-стек, короткие TTL-кэши ответов бэкенда, dedup
> `update_id`, rate-limit счётчики, identity-link `tg_user_id ↔ backend_account`.
> **Вся бизнес-данность — на бэкендах** (через `httpclient`), события — в NATS,
> медиа — в S3. В реляционке бот ничего своего не держит (Postgres не нужен,
> см. 05 §7).
>
> Источники истины:
> - cachekit / idempotency / httpclient — `design/_research/05-pylibinfra-integration-kits.md`
>   (§2 cachekit, §1 httpclient, §5 authnkit).
> - aiogram `RedisStorage` / key-builder / `RedisEventIsolation` —
>   `design/_research/07-modern-aiogram-stack.md` (§3).
> - aiogram_dialog storage/stack/сериализация —
>   `aiogram-dialog-docs/reference/04-context-intent-storage-stack.md`,
>   `aiogram-dialog-docs/guides/gotchas-and-production-checklist.md` (темы 2, 3).

---

## 0. Граница: что бот хранит и что НЕ хранит

### Хранит (это «своё» состояние фронтенда)

| Вид | Зачем |
|---|---|
| **FSM state + FSM data** | Текущий шаг пользователя вне aiogram_dialog (`State`, `Storage.set_data`). |
| **Dialog stack** (`Stack`) | Список открытых диалогов в «канале» (intent'ы снизу вверх), метаданные последнего сообщения окна. |
| **Dialog context** (`Context`) | Данные одного открытого диалога: `state`, `start_data`, `dialog_data`, `widget_data`, `access_settings`. |
| **Короткий TTL-кэш ответов бэкенда** | Снизить нагрузку/латентность на повторные `GET` (профиль, справочники). TTL секунды–минуты. |
| **Dedup `update_id`** | Защита от повторной обработки апдейта при webhook-ретраях Telegram. |
| **Rate-limit / anti-flood счётчики** | Входящий троттлинг пользователей (`INCR`+TTL в Redis). |
| **Identity-link `tg_user_id → backend_account_id`** | Маппинг Telegram-пользователя на аккаунт бэкенда (для исходящих вызовов и для адресации push-уведомлений `backend_user → chat_id`). |
| **MediaIdStorage (file_id-кэш)** | Опц.: общий кэш `file_id` диалоговых медиа (по умолчанию in-memory LRU per-process). |

### НЕ хранит (живёт на бэкендах)

- Бизнес-сущности (заказы, профили, балансы, каталог) — только запрашиваются по
  HTTP и опц. кэшируются на короткий TTL. **Кэш ≠ источник истины.**
- Долговременные пользовательские данные, аудит, деньги, права/роли (RBAC решает
  бэкенд; бот может лишь verify'ить JWT-claim).
- Пароли/секреты пользователя, MFA — это бэкенд (`authnkit.Hasher`/`TOTP` боту
  почти никогда не нужны, 05 §5).

---

## 1. Таблица «вид состояния → хранилище → ключ → TTL → сериализация → кто пишет/читает»

| Вид состояния | Хранилище | Ключ (формат) | TTL | Сериализация | Пишет / читает |
|---|---|---|---|---|---|
| **FSM state/data** | aiogram `RedisStorage` (общий Redis) | `fsm:<bot_id>:<chat_id>:<user_id>:<destiny>:<field>` (через `DefaultKeyBuilder`) | `state_ttl` / `data_ttl` (опц., задаём, чтобы Redis не пух; напр. 24–72 ч) | JSON (storage сам сериализует) | aiogram middleware / хендлеры |
| **Dialog stack** | тот же `RedisStorage` (через `BaseStorage`-прокси aiogram_dialog) | `StorageKey(... destiny="aiogd:stack:<stack_id>")` → ключ key-builder'а | как `data_ttl` storage | JSON; поля `Stack` (`_id,intents,last_message_id,last_*`) | aiogram_dialog `StorageProxy.save_stack/load_stack` (под lock стека) |
| **Dialog context** | тот же `RedisStorage` | `StorageKey(... destiny="aiogd:context:<intent_id>")` | как `data_ttl` storage | **строго JSON-примитивы** `dict\|list\|int\|str\|float\|None` (§3) | `StorageProxy.save_context/load_context`; меняется хендлерами через `manager.dialog_data`/виджеты |
| **Event isolation (lock per-stack)** | `RedisEventIsolation` (тот же Redis) | внутренний lock-ключ на storage-key стека (`lock_kwargs={"timeout":60}`) | TTL = таймаут лока (60 c) | — (redis lock) | aiogram dispatcher + aiogram_dialog `load_stack` |
| **TTL-кэш ответа бэкенда** | `cachekit.Cache` (тот же Redis, свой префикс) | `cache:<scope>:<id>` напр. `cache:profile:<tg_user_id>` | секунды–минуты (явный `ttl`), тег `user:<id>` для инвалидации | `get_json/set_json` (JSON) | хендлер после `httpclient.get` пишет; хендлеры читают |
| **Dedup `update_id`** | `cachekit.Cache` (или `IdempotencyStore`) | `tg:update:<update_id>` (05 §2 Пример A) / `idempotency:update:<update_id>` | короткий, ~10 мин (Telegram ретраит при таймауте вебхука) | маркер `b"1"` (Cache) **или** (response,status) для `IdempotencyStore` | inbound-middleware: пишет SETNX-маркер, читает на входе |
| **Rate-limit счётчик** | `cachekit` Redis напрямую (`INCR`+`EXPIRE`) | `rl:<scope>:<tg_user_id>` напр. `rl:msg:<user_id>` | окно лимита (напр. 1–60 c) | int (Redis INCR) | throttling-middleware пишет/читает |
| **Identity-link** | `cachekit.Cache` (тот же Redis, свой префикс) | `link:tg:<tg_user_id>` → `backend_account_id`; обратный `link:acct:<account_id>` → `chat_id` | долгий или без TTL + явная инвалидация (см. §6) | строка/JSON (id, при желании короткий session-JWT) | link-flow (deep-link) пишет; хендлеры и NATS-подписчик читают |
| **MediaIdStorage (file_id)** | по умолчанию in-memory LRU (per-process); опц. Redis | `MediaIdStorageProtocol`-реализация поверх Redis | долгий | строка `file_id`+`file_unique_id` | aiogram_dialog при показе медиа |

> Формат FSM-ключа (07 §3):
> `<prefix>:<bot_id?>:<bus_conn?>:<chat_id>:<user_id>:<destiny?>:<field?>`.
> aiogram_dialog кладёт `user_id=chat_id` в `StorageKey`, а реальную адресацию
> прячет в `destiny` (`aiogd:stack:*` / `aiogd:context:*`), см. reference 04 §5.

---

## 2. Сосуществование трёх потребителей Redis

Три независимых «писателя» в Redis, у каждого свой префикс/неймспейс. **Можно
один Redis-инстанс** — конфликтов нет, т.к. неймспейсы не пересекаются. Шарить
один `redis.Redis`-коннект между aiogram-storage и cachekit — нормально (05 §2:
«Шарить один `redis.Redis`-инстанс между aiogram-storage и cachekit — нормально»).

| Потребитель | Откуда коннект | Префикс ключей | Что пишет |
|---|---|---|---|
| **aiogram `RedisStorage`** | `redis.asyncio.Redis(...)` (07 §3); можно тот же инстанс, что и cachekit | `fsm:*` (`DefaultKeyBuilder(prefix="fsm", with_bot_id=True, with_destiny=True)`) | FSM state/data |
| **aiogram_dialog** | пишет **через тот же** `RedisStorage` (`BaseStorage`) — отдельного подключения не заводит | `fsm:*` c `destiny=aiogd:stack:*` / `aiogd:context:*` | Stack + Context (живёт «внутри» fsm-неймспейса, но в своём destiny) |
| **pylibinfra `cachekit`** | `CachekitProvider` → `redis.from_url(REDIS_URL, ...)` (05 §2) | `cache:*`, `idempotency:*`, `tag:*`, плюс наши `tg:update:*`, `link:*`, `rl:*` | dedup, кэши, identity-link, rate-limit |

### Ключевые требования к сосуществованию

1. **`with_destiny=True` обязателен для aiogram_dialog** (07 §3, reference 04 §5).
   aiogram_dialog адресует стек/контекст через `destiny`; без флага ключи диалога
   и «голого» FSM могут пересечься. `with_bot_id=True` изолирует разных ботов в
   общем Redis.
2. **Один key-builder на storage**, и тот же storage передаётся в
   `setup_dialogs` — aiogram_dialog не строит свой ключ, а идёт через
   `Dispatcher.storage`. Поэтому FSM и диалоги делят `state_ttl/data_ttl`.
3. **cachekit использует свой префикс** (`cache:`/`idempotency:`) и НЕ пересекается
   с `fsm:*`. Наши ручные ключи (`tg:update:`, `link:tg:`, `rl:`) выбираем так,
   чтобы не начинались с `fsm:` — изоляция гарантирована.
4. **БД Redis:** дефолт `REDIS_URL=redis://localhost:6379/0` (05 §2). По умолчанию
   один логический DB-индекс для всех трёх (префиксы и так разделяют). Разные
   `db=` — только если нужна раздельная `FLUSHDB`/эвикшн-политика (напр. кэши с
   `allkeys-lru` отдельно от FSM, который терять нельзя). **Рекомендация:** один
   Redis, один db, разделение префиксами; при разной политике вытеснения — вынести
   кэш в отдельный db/инстанс, чтобы LRU не выбрасывал FSM-стек.
5. **cachekit НЕ даёт aiogram-`BaseStorage`** (05 §2 ⚠️): он отдаёт `redis.Redis`/
   `Cache`, а не `RedisStorage`. Поэтому FSM-storage конструируем сами из
   `redis.asyncio.Redis` (07 §3), а cachekit берём для dedup/кэшей/link.

---

## 3. Сериализация: инвариант «только JSON-примитивы»

**Контракт типа** (reference 04 §2, §8): `Data = dict | list | int | str | float | None`.
Всё, что кладётся в `dialog_data` / `widget_data` / `start_data` / `result`,
проходит `StorageProxy.save_context → storage.set_data → backend (JSON)`. На
JSON/Redis-backend `datetime` / `Decimal` / `set` / pydantic-модель / ORM-объект
**падают `TypeError` ПРИ СОХРАНЕНИИ** — т.е. уже после ответа пользователю, в
`context_saver_middleware` (gotchas тема 2.1). На in-memory «прокатит» и взорвётся
при переезде на персистентный storage — поэтому `MemoryStorage` в проде запрещён
(тема 2.2).

### Как enforce'ить в шаблоне

1. **Типизированные state-модели pydantic, но сериализуемые в dict.** Описываем
   диалоговый state как `pydantic.BaseModel`, а в storage кладём
   `model.model_dump(mode="json")` (datetime → ISO-строка, Decimal → str/float,
   Enum → value). Читаем — `Model.model_validate(manager.dialog_data)`. В
   `dialog_data`/`widget_data`/`start_data` **никогда не кладём саму модель**,
   только `dict` от `model_dump(mode="json")`.
2. **Запрет на «сырые» небезопасные типы.** В шаблоне — хелпер
   `put_dialog_data(manager, model)` / `get_dialog_data(manager, Model)`, который
   единственный пишет в `dialog_data`, всегда через `mode="json"`. Прямой доступ
   к `manager.dialog_data[...]` для записи не-примитивов — анти-паттерн.
3. **Тесты на `JsonMemoryStorage`** (а не `MemoryStorage`): он делает
   `json.dumps`/`loads` и **ловит несериализуемое сразу** (reference 04 §8, gotchas
   тема 2.2). Это страховка на CI: если кто-то положил `datetime`/модель — тест
   падает, а не прод.
4. **`access_settings.custom`** — тоже сериализуется (reference 04 §6): если
   используем, кладём только JSON-совместимое.
5. **`result` в `done(result=...)`** уходит через bg-событие (pydantic
   `DialogUpdateEvent`) и/или в `on_process_result` — те же ограничения (тема 2.1).

---

## 4. Идемпотентность / дедуп апдейтов

**Проблема:** Telegram при таймауте вебхука (бот не успел вернуть 200 за ~отведённое
время) **переотправляет апдейт** с тем же `update_id`. При нескольких воркерах за
одним webhook-эндпоинтом тот же апдейт может попасть в разные процессы. Двойная
обработка → двойное сообщение/двойной вызов бэкенда.

**Решение — inbound-middleware с dedup по `update_id`** (05 §2, Пример A):

- **Дешёвый вариант (маркер):** `cachekit.Cache` — атомарный SETNX-семантикой:
  `get(f"tg:update:{update_id}")`; если `found` → дубль, тихо игнорируем.
  Иначе `set(key, b"1", ttl≈10 мин)` и обрабатываем. **TTL короткий** (Telegram
  ретраит только в окне таймаута; нет смысла держать вечно) — 05 §2 явно: «ставить
  короткий TTL».
  > Важно: между `get` и `set` есть гонка. Для строгой атомарности использовать
  > Redis `SET key val NX EX ttl` (одна команда) либо `IdempotencyStore` (ниже),
  > а не пару get→set.
- **Строгий вариант (сохранить ответ):** `cachekit.IdempotencyStore` /
  `CacheIdempotencyStore` (05 §2): `store.get(f"update:{update_id}")` → если
  `found`, отдать сохранённый результат (response,status), не обрабатывая повторно;
  иначе обработать и `store.set(...)`. Ключ хранится как `idempotency:<key>`,
  TTL `idempotency_ttl=86400` (05 §2). Это готовый dedup-стор (изначально для
  httpkit-идемпотентности). Подходит, когда дубль должен вернуть **тот же** ответ,
  а не просто игнорироваться. Для inbound-апдейтов обычно достаточно маркера —
  ответ Telegram'у это пустой 200, сохранять нечего.

**Рекомендация шаблона:** middleware-«outer» на уровне dispatcher, до диалоговых
middleware; на входе — атомарный `SET tg:update:<id> 1 NX EX 600`; если ключ уже
есть — `return` (апдейт не доходит до хендлеров). Дедуп ставим **до** FSM/диалоговой
загрузки, чтобы не трогать стек на дубле.

> Корреляция: в этом же middleware ставим `request_id.set(f"tg-{update_id}")`
> (05 §1) — один `X-Request-ID` на апдейт прокидывается во все исходящие вызовы
> бэкенда, что заодно даёт идемпотентность и на стороне бэкенда (он может дедупать
> по `Idempotency-Key`).

---

## 5. Мультиинстансность (≥2 воркеров / горизонтальный webhook)

1. **Распределённый `events_isolation` ОБЯЗАТЕЛЕН** (reference 04 §9, gotchas
   тема 3.1, чеклист B.0). Дефолт `SimpleEventIsolation` — in-memory per-process:
   при ≥2 воркерах он **не синхронизирует процессы**, и два процесса могут
   одновременно изменить один стек (гонка за `intents`/`dialog_data`, потеря
   записей). Решение — `RedisEventIsolation`:
   ```python
   dp = Dispatcher(storage=storage, events_isolation=storage.create_isolation())
   setup_dialogs(dp)  # тот же isolation используется и диалогами
   ```
   `storage.create_isolation()` → `RedisEventIsolation` (07 §3), per-user/per-stack
   lock в Redis с `lock_kwargs={"timeout":60}` (фикс 3.19.0).
2. **Гонка за стек.** Lock берётся на **уровне стека** (reference 04 §9): разные
   стеки (разные пользователи в группе, разные `NEW_STACK`) идут параллельно, один
   стек — строго по очереди. `load_stack` берёт lock, `context_unlocker_middleware`
   в `finally` снимает (reference 04 §5, §7). С Redis-isolation это работает и
   между процессами. **Подводный камень:** `fg()` держит lock на стек, пока внутри
   `async with bg.fg()` — тело должно быть коротким, иначе блокируешь стек на всех
   воркерах (gotchas тема 11.3).
3. **MediaIdStorage per-process** (gotchas тема 3.2): дефолтный file_id-кэш —
   in-memory LRU на процесс; при N воркерах каждый прогревается заново (лишние
   первые аплоады, функционально безопасно). Если важна общая экономия — своя
   реализация `MediaIdStorageProtocol` поверх Redis в `setup_dialogs(media_id_storage=...)`.
4. **Горизонтальный webhook.** Все воркеры за одним эндпоинтом → один и тот же
   апдейт может прийти в любой из них при ретрае: dedup (§4) **обязателен и
   общий** (Redis), не локальный. Webhook-секрет (`X-Telegram-Bot-Api-Secret-Token`)
   проверяем сами при ручном FastAPI-пути (07 §2.3, issue #1024).
5. **TTL на FSM/диалоговый storage.** При множестве пользователей и долгоживущем
   процессе Redis пухнет: `remove_context`/`remove_stack` пишут `{}`, **не удаляя
   ключ** (reference 04 §5, gotchas тема 2.5) → накапливаются пустые `aiogd:*`
   ключи. Решение: задать `state_ttl`/`data_ttl` в `RedisStorage` и/или отдельная
   джоба чистки пустых ключей.
6. **Все воркеры — один Redis** (общий state). Никакого локального state, который
   нельзя восстановить из Redis: процесс должен быть stateless по бизнес-данным.

---

## 6. Identity-link: Telegram user → backend account

**Назначение:** связать `tg_user_id` с аккаунтом бэкенда, чтобы (а) исходящие
вызовы шли от имени аккаунта и (б) push-уведомления из NATS адресовались в нужный
`chat_id` (`backend_user_id → chat_id`, который natskit сам не делает — 05 §3).

### Где хранить

`cachekit.Cache` (тот же Redis, свой префикс), две записи:

| Ключ | Значение | TTL |
|---|---|---|
| `link:tg:<tg_user_id>` | `backend_account_id` (или короткий session-JWT) | долгий / без TTL + явная инвалидация |
| `link:acct:<account_id>` | `chat_id` (для адресации push) | то же |

### Как линкуется (deep-link токен, 05 §5)

Пользователь приходит по ссылке `t.me/<bot>?start=<jwt>`, выпущенной бэкендом.
Бот verify'ит JWT (`authnkit.JWTParser.parse` — проверка подписи + `exp`), берёт
`claims["sub"]` = `backend_account_id`, пишет линк:

```python
from pylibinfra.authnkit import JWTParser, ErrTokenExpired, TokenError

async def link_account(parser: JWTParser, cache, tg_user_id: int, token: str):
    try:
        claims = parser.parse(token)          # verify подписи + exp
    except (ErrTokenExpired, TokenError):
        raise InvalidLink()
    backend_user_id = claims["sub"]
    await cache.set(f"link:tg:{tg_user_id}", backend_user_id.encode())
```

### TTL / инвалидация

- **TTL:** identity-link — долгоживущее (пользователь линкуется один раз). Либо без
  TTL, либо большой TTL с продлением при активности. Если хранить **session-JWT**
  бэкенда (не голый id) — TTL = `access_ttl`/`refresh_ttl` токена; протух → требуем
  релинк.
- **Инвалидация:** при `/unlink`, logout на бэкенде (событие через NATS → удалить
  оба ключа), или при компрометации. Удобно повесить **тег** `user:<account_id>`
  на связанные кэши (05 §2: `invalidate_by_tag` сбрасывает «кэш юзера» разом).
- **Двунаправленность:** держим обе записи (`tg→acct` и `acct→chat`), т.к. push из
  NATS приходит с `account_id`, а слать надо в `chat_id`. При unlink чистим обе.

### Безопасность

- **`JWT_SECRET` должен совпадать с бэкендом** (HS256 симметричный, 05 §5 ⚠️).
  Если бэкенд подписывает **RS256/asymmetric — `HS256JWT` НЕ подойдёт**, нужен свой
  парсер. Deep-link токен — **одноразовый и короткоживущий** (бэкенд ставит малый
  `exp`), иначе перехваченная ссылка = захват аккаунта.
- **Не доверять `tg_user_id` как аутентификации** к бизнес-операциям: линк
  подтверждает связь, но критичные действия бэкенд авторизует сам (по своему
  токену/сессии). Бот — фронтенд, не источник прав.
- **Не логировать токен/секрет**; в structlog биндить только `tg_user_id`/`chat_id`/
  `update_id` (04 core-kits §RequestIDMiddleware-аналог).

---

## 7. Подводные камни (свод)

1. **JSON-only инвариант** легко нарушить: `datetime`/`Decimal`/pydantic-модель в
   `dialog_data` падают **после** ответа пользователю (в saver-middleware), на
   in-memory маскируются. Enforce: `model_dump(mode="json")` + тесты на
   `JsonMemoryStorage`. (reference 04 §8, gotchas 2.1/2.2)
2. **`with_destiny=True` обязателен** для aiogram_dialog, иначе диалоговые ключи
   путаются с FSM. (07 §3) `with_bot_id=True` — изоляция ботов в общем Redis.
3. **`SimpleEventIsolation` (дефолт) в multi-worker = гонки за стек.** Передавать
   `storage.create_isolation()` (`RedisEventIsolation`). Lock per-stack: `fg()` с
   долгим телом блокирует стек на всех воркерах. (reference 04 §9, gotchas 3.1/11.3)
4. **dedup `update_id` обязателен и атомарен.** Пара get→set имеет гонку —
   использовать `SET ... NX EX` (одна команда) или `IdempotencyStore`. TTL
   короткий (~10 мин). Webhook-секрет при ручном пути проверять самим. (05 §2,
   07 §2.3)
5. **Redis пухнет:** `remove_context/remove_stack` пишут `{}`, а не удаляют ключ →
   мусор `aiogd:*`. Задавать `state_ttl`/`data_ttl` и/или джобу очистки. (reference
   04 §5, gotchas 2.5)
6. **Кэш бэкенда ≠ источник истины.** Только короткий TTL + тег-инвалидация
   `user:<id>`; на стейл-данные пользователь не должен полагаться в критичных
   операциях.
7. **Identity-link: HS256 совпадение секрета с бэкендом; RS256 не поддержан.**
   Deep-link токен — одноразовый/короткоживущий. Линк ≠ авторизация бизнес-действий.
   (05 §5)
8. **Миграции `StatesGroup`/`State`** ломают старые контексты (`UnknownState`/
   `UnknownIntent`); `IntentErrorMiddleware` молча сбросит битый стек. Не
   удалять/переименовывать состояния без миграции; повесить error-handler. (gotchas
   2.3, чеклист B.0)
9. **cachekit не даёт aiogram-`BaseStorage`** — FSM-storage строим сами из
   `redis.asyncio.Redis`; cachekit берём для dedup/кэшей/link, шаря тот же Redis.
   (05 §2)
