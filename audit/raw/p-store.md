# Аудит p-store: storagekit + cachekit + pgkit

Область: `pylibinfra/src/pylibinfra/storagekit/` (195 строк), `cachekit/` (226), `pgkit/` (444).
Это инфра-киты хранилищ: S3-объекты, Redis-кэш, Postgres. Меряю против философии «тонкий шаблон +
вся инфра в ките»: механика, сериализация, TTL, lifecycle соединений, типобезопасность, утечки,
гонки.

## Что смотрел

- **storagekit**: порт `Storage` (put/delete), `Ref`, `new_key`/uuid7, `URLBuilder`, `MemoryStorage`,
  боевой `s3/uploader.py` + `s3/module.py` (aioboto3), `StoragekitProvider`.
- **cachekit**: порт `Cache` + `RedisCache`, generic `get_json[T]`/`set_json[T]`, tag-invalidation,
  `CacheIdempotencyStore`, `CachekitProvider` (redis lifecycle + OTel).
- **pgkit**: `PoolConfig`/`new_pool`, `Transactor` (contextvar), `DB`-фасад, `ReadWriteDB`/replica,
  `migrate_up` (yoyo), `errors` (SQLSTATE-предикаты), `metrics` (db_pool_* gauges), `db_probe`.
- **Как использует бот**: cachekit — `LocalePrefStore` (i18n), `CacheOnboardingStore` (start),
  `OrderDeliverer` дедуп доставки (`DeliveryDedup`), identity-link, dedup-middleware. storagekit и
  pgkit ботом **не используются** (бот Redis-only) — это библиотечные киты для бэкендов.
- Прогнал `mypy` (Success, 26 файлов), `ruff check` (All checks passed) по трём китам; прочитал
  unit/integration-тесты каждого кита.

Ключевой контекст: единый `redis.Redis` из `CachekitProvider.client` шарится между FSM
`RedisStorage`, dedup-middleware, `Cache`, `DeliveryDedup` (см. `tgbotkit/module.py:84,91,118`,
`tgbotkit/storage.py`). Это by design (изоляция через `key_builder`/префиксы), не дефект.

## Сильные стороны

- **Чистые порты + структурная типизация.** `Cache`/`Storage`/`Executor`/`Transactor` —
  `@runtime_checkable` Protocol; адаптеры удовлетворяют структурно, потребитель зависит от
  интерфейса (`cache.py:18`, `storage.py:27`, `transactor.py:12`). mypy strict проходит чисто.
- **Go-style `(value, found)` корректен.** `RedisCache.get` отдаёт `(bytes|None, bool)`: пустое
  значение `b""` даёт `found=True`, не путается с miss (`cache.py:38`). То же в idempotency
  (`tuple[bytes|None,int,bool]`) и `get_json`. Это правильная семантика, легко ошибиться — не
  ошиблись.
- **Lifecycle соединений через async-generator providers.** redis (`cachekit/module.py:21-32`) и
  pg-pool (`pgkit/module.py:26-31,41-53`) закрываются на `container.close()` (`yield` + `aclose`/
  `close`). Реплика-пул закрывается отдельно. Двойного close нет: FSM/dedup только держат ссылку,
  не владеют клиентом. Утечек ресурсов в нормальном пути не нашёл.
- **Дедуп атомарен.** `DeliveryDedup.seen` и `DedupMiddleware` — `SET NX EX` (атомарный single-op),
  гонки между воркерами нет (`tgbotkit/notifications/dedup.py:18`, `middleware/dedup.py:33`). TTL
  ограничен снизу `max(int(ttl),1)`.
- **idempotency-сериализация бинарно-безопасна.** Тело ответа base64 внутри JSON
  (`idempotency.py:33,36`), тест `test_binary_response_survives` гоняет `bytes(range(256))`.
- **pgkit session-timeouts без инъекции.** `statement_timeout`/`idle_in_tx`/`lock_timeout` ставятся
  на каждом коннекте через `init` (`pool.py:37-44`); значение — `int` из `_ms()`, имена хардкод —
  SQL-инъекция исключена. Транзактор корректно прокидывает соединение через contextvar, тест
  проверяет rollback и очистку токена в `finally` (`transactor.py:44-49`).
- **SQLSTATE-предикаты вместо isinstance.** `errors.py` матчит по коду (`23505` и т.д.) — устойчиво
  к обёрнутым/неизвестным asyncpg-классам. `is_retryable` покрывает `40001`/`40P01`.
- **Tag-TTL не растёт мусором.** `expire(tag_key, ttl)` привязывает время жизни тег-сета к записи
  (`cache.py:57-59`) — осознанный анти-leak.
- **uuid7-ключи без новой зависимости**, k-sortable по ms (`storage.py:44-54`); неизвестный
  content-type → ключ без расширения, остаётся валидным.

## Находки

### medium — tag-invalidation не атомарна и теряет ключи при гонке (CAT=async/correctness, CONF=high)

`RedisCache.set` делает `set` + `sadd` + `expire` тремя отдельными командами без pipeline/MULTI
(`cache.py:53-59`), а `invalidate_by_tag` — `smembers` → `delete(keys)` → `delete(tag_key)` тоже не
атомарно (`cache.py:66-72`). Два следствия: (1) краш между `set` и `sadd` оставляет значение без
тега — оно переживёт `invalidate_by_tag`; (2) если `set(...,tags=[t])` добавит ключ в сет между
`smembers` и `delete(tag_key)` инвалидации, новый ключ останется живым, а тег-сет будет удалён —
запись «провисает» неинвалидируемой. Для боевого инвалидационного кэша это классический источник
stale-данных. Бот эти теги не использует (locale/onboard/dedup — простые ключи), поэтому в текущем
шаблоне риск нулевой; но как библиотечный примитив для бэкендов — реальная проблема.
**Fix:** обернуть `set`+тег-записи в `pipeline(transaction=True)`; для инвалидации — Lua-скрипт
(`SMEMBERS`+`DEL` атомарно) или хотя бы удалять `tag_key` до перечисления членов.

### medium — `max_conn_lifetime` в pgkit сконфигурирован, но не применяется (CAT=correctness/dx, CONF=high)

`PoolConfig.max_conn_lifetime` (`PG_MAX_CONN_LIFETIME`, дефолт 1800с) объявлен и покрыт тестом
дефолта (`pool.py:21`, `tests/pgkit/test_config.py:13`), но в `asyncpg.create_pool` передаётся
только `max_inactive_connection_lifetime=cfg.max_conn_idle_time` (`pool.py:69`). asyncpg не имеет
параметра «max lifetime» — поле молча no-op. Оператор, выставивший `PG_MAX_CONN_LIFETIME`, думает,
что соединения рециклятся по возрасту (важно за PgBouncer/прокси, что убивает старые конн., и при
failover), а они живут до idle-recycle/серверного kill. Конфиг даёт ложное чувство контроля.
**Fix:** либо реализовать max-lifetime (custom `init`/wrapper, считающий возраст и закрывающий
коннект), либо убрать поле и задокументировать ограничение asyncpg. pgkit ботом не используется —
влияние на шаблон нулевое, но это дефект кита.

### low — `cachekit.Config.write_timeout` нигде не используется (CAT=dx, CONF=high)

`REDIS_WRITE_TIMEOUT` (дефолт 3.0) объявлен (`config.py:13`), но в `redis.from_url` передаются
только `socket_connect_timeout` и `socket_timeout` (`module.py:27-29`). redis-py использует
`socket_timeout` и на read, и на write — отдельного write-таймаута нет. Мёртвое поле конфига:
выглядит как ручка, ничего не делает. **Fix:** удалить поле (или объединить семантику в комментарии).

### low — S3 `delete` фактически никогда не кидает `ErrNotFound`; расхождение с `MemoryStorage` (CAT=correctness, CONF=medium)

`Uploader.delete` ловит `ClientError` и мапит `NoSuchKey`/`404` в `ErrNotFound`
(`s3/uploader.py:43-48`), но `DeleteObject` в S3/MinIO **идемпотентен** — удаление отсутствующего
ключа возвращает 204, исключения нет. То есть ветка `ErrNotFound` для боевого адаптера практически
мёртвая. При этом `MemoryStorage.delete` **кидает** `ErrNotFound` на отсутствующий ключ
(`memory.py:27-29`). Тест на этой семантике (memory) зелёный, а прод ведёт себя иначе — классический
fake-vs-real дрейф: код, полагающийся на `ErrNotFound` от delete, пройдёт тесты и сломается (точнее,
тихо не сломается) в проде. Бот storage не использует — влияние теоретическое. **Fix:** выровнять —
сделать `MemoryStorage.delete` тоже идемпотентным (no-op на отсутствующем ключе), либо
задокументировать, что delete идемпотентен, а `ErrNotFound` относится только к put/get-семантике.

### low — `Transactor` через contextvar небезопасен при `create_task` внутри транзакции (CAT=async, CONF=medium)

`PoolTransactor.with_tx` кладёт tx-соединение в `ContextVar` (`transactor.py:26,46`). contextvar
**копируется** в дочерний таск при `asyncio.create_task`/`gather`, поэтому код вида
`async with tr.with_tx(): await asyncio.gather(repo_a(), repo_b())` заставит обе корутины дёргать
**одно** asyncpg-соединение конкурентно. asyncpg-коннект не поддерживает конкурентные запросы —
получишь `InterfaceError: another operation is in progress` или порчу протокола. Ни кода-гарда, ни
предупреждения в docstring нет. Это известный footgun паттерна «tx в contextvar». pgkit ботом не
используется, но для бэкендов на нём — грабли. **Fix:** хотя бы строка в docstring («внутри with_tx
не порождай конкурентные таски»); идеально — детект (счётчик активных операций на коннекте) или
обёртка, бросающая понятную ошибку.

### low — `get_json`/idempotency.get не защищены от битых данных в кэше (CAT=errors, CONF=medium)

`get_json` (`cache.py:86`) и `CacheIdempotencyStore.get` (`idempotency.py:31-33`) делают
`json.loads`/`entry["response"]`/`base64.b64decode` без try. Битая/легаси/чужая запись под тем же
ключом → необработанный `JSONDecodeError`/`KeyError`/`binascii.Error` пробьётся в вызывающий код.
Для кэша «не смог прочитать → miss» обычно безопаснее, чем падение. Низкий приоритет (записи свои,
формат стабильный), но в shared-redis с эволюцией формата — потенциальный источник 500.
**Fix:** ловить decode-ошибки и трактовать как miss (`return None, False`).

### info — `max_conn` реплики копируется, `min_conns` — нет (CAT=correctness, CONF=medium)

`replica_pool` делает `cfg.model_copy(update={"dsn":..., "max_conns": rep_cfg.max_conns})`
(`module.py:48-50`) — реплике достаётся `min_conns` мастера, не своя настройка. `ReplicaConfig` и не
имеет `min_conns`, так что это by design, но асимметрия (есть `PG_REPLICA_MAX_CONNS`, нет
`PG_REPLICA_MIN_CONNS`) может удивить. Низкий приоритет.

### info — `RedisInstrumentor().instrument()` внутри provider-генератора (CAT=observability, CONF=low)

`cachekit/module.py:24` вызывает глобальный instrument при каждом резолве `client`. Для APP-scope
резолв один — практически безвредно; комментарий заявляет идемпотентность. Аналогично pgkit
защищён флагом `_INSTRUMENTED` (`pool.py:47-55`) — там сделано аккуратнее. Расхождение стиля, не баг.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. Для бота релевантен только cachekit, и он
сделан добротно: чистый порт `Cache`, корректный `(value, found)`, атомарный дедуп, аккуратный
lifecycle redis, бинарно-безопасная idempotency. Все потребители в шаблоне (locale, onboarding,
chat-link, dedup) ложатся на простые `get/set` — самые надёжные операции кита. Найденные дефекты
(tag-атомарность, write_timeout, S3/pgkit-варты) в **бот-пути не задействованы**.

**2. Гибкость.** cachekit гибок ровно настолько, насколько нужно боту: порт + generic JSON-хелперы +
теги. Хочешь свой кэш-адаптер — реализуй `Cache`-Protocol, DI подменит. pgkit/storagekit — отдельные
полноценные киты «про запас» (бэкенды, не бот): пул, транзактор, реплика, миграции, S3 — у заказчика,
если бот пойдёт в Postgres, инфраструктура уже есть, не с нуля. Это **плюс к гибкости**, а не нагрузка
(deps в core, но киты импортятся лениво, ничего лишнего не стартует).

**3. Тревога про один клиент к одному API (BackendClient).** Это **не** моя область (platform/backend),
но storage-слой даёт прямой контр-аргумент к «негибко by design»: cachekit/pgkit/storagekit — это
**порты + сменные адаптеры через DI**, а не синглтоны-фасады. Несколько разных Postgres/Redis/S3
заводятся как отдельные DI-ключи (паттерн уже показан: `ReplicaPool` — отдельный pool отдельным
NewType-ключом, `module.py:16,42`). То есть архитектурный примитив «несколько клиентов к разным
бэкендам» в pylibinfra **есть и работает**; если в `platform/` он не применён для HTTP-клиентов —
это решение шаблона, не предел библиотеки.

Итог по области: **здоровая инфра-прослойка**. Ни одной critical/high; для бота — фактически ноль
действующих дефектов. Топ-3 (tag-атомарность, мёртвый `max_conn_lifetime`, S3/memory delete-дрейф) —
это «починить в ките до того, как кто-то построит на нём бэкенд», а не блокеры шаблона.
