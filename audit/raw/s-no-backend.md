# Стресс-тест s-no-backend — бот БЕЗ внешнего бэкенда (чисто-локальная логика, состояние в Redis)

Сценарий: потребитель шаблона строит бота, у которого **нет внешнего бэкенда вообще**. Вся
бизнес-логика локальна, состояние — в Redis/Postgres через pylibinfra, **никаких исходящих HTTP-
вызовов**. Вопрос: сколько инфраструктуры предполагает обязательный backend; чисто ли выпиливается
`platform/backend` + httpclient-зависимость; не ломается ли dishka-граф / проводка / скилл
`/de-template`; тянет ли tgbotkit обязательный `httpclient.Client` транзитивно; где «бэкенд» зашит
как предположение.

**Вердикт: supported, но awkward на де-темплейте.** Чисто-локальный бот построить **можно** — и это
по сути то, что уже делают фичи `start`/`lang`/`notifications` (все три — Redis/cache-only, ноль HTTP).
Архитектура НЕ припаяна к backend намертво: `httpclient.Client` в DI-графе просит **единственный**
потребитель — `BackendProvider` шаблона; tgbotkit его транзитивно **не** тянет. Но выпиливание не
бесшовное: dishka валидирует граф **на старте**, поэтому backend убирается только «всё-или-ничего»
(оба провайдера + все gateway фич синхронно), а гайд `/de-template` прямо подталкивает оставить
`BackendProvider` «на всякий» — что роняет старт. Плюс `backend_user_id` вшит в общий тип `BotIdentity`.

## Что смотрел

- Composition root: `src/bot/app.py`, `src/bot/config.py`, `src/bot/extensions.py`.
- platform-backend: `src/bot/platform/backend/{client,provider,errors,__init__}.py`.
- identity: `src/bot/platform/identity/{identity,provider}.py`, `src/bot/platform/links.py`.
- Потребители backend в фичах: `features/{profile,payments}/{gateway,provider}.py`; локальные фичи
  `features/{start,lang,notifications}/*` (что они тянут).
- tgbotkit DI-граф: `pylibinfra/src/pylibinfra/tgbotkit/module.py`, `runner/*`,
  `middleware/request_id.py`, `notifications/delivery.py` — что из httpclient импортит kit.
- httpclient: `pylibinfra/src/pylibinfra/httpclient/{__init__,module}.py`; pyproject extra `[tgbotkit]`
  vs core-deps (`pylibinfra/pyproject.toml`).
- de-template: `.claude/skills/de-template/{SKILL.md,references/prune.md,references/wiring.md}`.
- stack-deep-dive: `.claude/skills/stack-deep-dive/SKILL.md` (есть ли кейс «без бэкенда»).
- Тест-харнес: `tests/_fakes/harness.py` (моно-BackendClient в графе).

**Эмпирически прогнал** (через `uv run python`): поведение dishka-валидации графа —
`make_async_container` **проверяет граф на старте** (недостающая фабрica → `GraphMissingFactoryError`
немедленно), но **лишняя** фабрика без потребителя граф НЕ роняет. Это ключ к оценке выпиливаемости.

## Сильные стороны (для этого сценария)

- **Локальный бот — это не натяжка, а уже половина шаблона.** Фичи `start` (онбординг-флаг + chat-link
  в cachekit, `start/gateway.py:8-25`), `lang` (locale-pref в cachekit, `lang/provider.py:16-18`),
  `notifications` (NATS→Telegram через `Delivery`/`DeliveryDedup`, `notifications/deliver.py:13-16`) —
  **ни одна не дёргает HTTP**. Их единственный I/O — Redis через `cachekit.Cache`. То есть «бот без
  бэкенда, состояние в Redis» — уже работающий паттерн в трёх из пяти reference-фич. Свою локальную
  фичу делаешь по образцу `start` (порт `OnboardingStore` → cache-адаптер), а не `profile`.
- **tgbotkit НЕ тянет `httpclient.Client` в DI-граф.** Из httpclient kit импортит **только** лёгкий
  contextvar `request_id` — для прокидывания `X-Request-ID=tg-<update_id>` в исходящие вызовы
  (`tgbotkit/middleware/request_id.py:16,25` и `notifications/delivery.py:16,36`). Это модуль `reqid`,
  не `Client`. Ни `BotProvider`, ни runner, ни одна middleware не просят `httpclient.Client` как
  dishka-зависимость (grep `: Client` по `tgbotkit/module.py`/`runner/` — пусто; единственный
  `Client`-параметр во всём pylibinfra-DI вне httpclient — это `nats.Client` в `natskit/conn.py:10`,
  другой тип). Значит при отсутствии backend `request_id`-contextvar просто остаётся неиспользованным —
  ноль вреда.
- **`httpclient.Client` в графе — ровно один потребитель.** `BackendProvider.client` (APP-scope,
  `backend/provider.py:15-17`). Больше никто во всём DI-графе `Client` не просит. Убираешь
  `BackendProvider` + потребителей — `HttpClientProvider` становится не нужен, и его удаление граф не
  ломает (т.к. dishka допускает лишние фабрики, но требует все зависимости — а зависимость на `Client`
  исчезает вместе с `BackendProvider`).
- **DIP-границы помогают.** `usecase`/`policy`/`state`/`dto` фич не знают про backend — они зависят от
  узких портов (`ports.BackendGateway`, `profile/usecase.py:13`). Локальная фича просто реализует порт
  поверх cache/pg вместо http — `usecase` не меняется. Анти-коррупционный слой работает в обе стороны.
- **Состояние FSM/dialog — целиком в Redis через kit**, без всякого backend (`tgbotkit/storage.py`,
  RedisStorage). Чисто-локальный бот по определению поддержан стораджем.

## Находки

### HIGH — выпиливание backend — «всё-или-ничего» на старте; `/de-template` подталкивает к падающей конфигурации (CAT=dx, CONF=high) [KEY]

dishka валидирует граф **в `make_async_container`** (проверено эмпирически: недостающая фабрика →
`GraphMissingFactoryError` немедленно при сборке контейнера, не при `.get()`). Следствие для сценария:

- Оставить `BackendProvider()` в `app.py:41`, но убрать `HttpClientProvider()` (`app.py:34`) →
  `BackendProvider.client` просит `Client` (`backend/provider.py:16`), фабрики нет → **бот падает на
  старте**, до первого апдейта. Не «деградирует», а вообще не поднимается.
- Wiring-гайд де-темплейта прямо ведёт сюда: `de-template/references/wiring.md:10` —
  *«Без бэкенда — но `BackendProvider` обычно остаётся»*. Это совет оставить провайдер, чей
  единственный смысл — обернуть `Client`, которого без `HttpClientProvider` в графе нет. Буквальное
  следование = `GraphMissingFactoryError` на старте.
- Чтобы вычистить backend чисто, нужно синхронно тронуть **минимум 5 точек**: `HttpClientProvider()`
  (`app.py:34`), `BackendProvider()` (`app.py:41`), `AppConfigProvider.http`→`HttpConfig`
  (`config.py:72-74`), весь `platform/backend/`, и все backend-gateway/provider удаляемых фич
  (`profile`/`payments`). `prune.md` перечисляет prune фич, но **нигде в де-темплейте нет чеклиста
  «убрать backend-слой целиком для локального бота»** — `prune.md:33-35` даже относит
  `platform/backend/` к «что НЕ удалять (платформа, не фичи)». То есть для чисто-локального бота гайд
  велит **сохранить** мёртвый backend-слой.

Workaround есть и он простой (удалить оба провайдера + `http`-Config + `platform/backend` + http-gateway
фич), но он **не задокументирован** и противоречит явному совету wiring.md. Не-питонист, ведомый
`/de-template`, получит либо падающий старт (оставил `BackendProvider`), либо висящий неиспользуемый
backend-слой (оставил всё по prune.md).

**fix:** (1) добавить в `de-template` ветку «local-only бот»: явный чеклист удаления backend-слоя
(`platform/backend/` + `HttpClientProvider`/`BackendProvider`/`AppConfigProvider.http` + backend-
gateway). (2) Исправить `wiring.md:10` — «без бэкенда `BackendProvider` УБИРАЕТСЯ вместе с
`HttpClientProvider`», не «обычно остаётся». (3) `prune.md:33-35` — пометить `platform/backend` как
«удаляемый, если форк без HTTP-бэкендов».

### MEDIUM — `backend_user_id` вшит в общий тип `BotIdentity` → «бэкенд» зашит как предположение идентичности (CAT=architecture, CONF=high) [KEY]

`BotIdentity` (`platform/identity/identity.py:12-15`) — общий REQUEST-scope тип идентичности, который
получает **каждая** фича. У него три поля, и одно из них — `backend_user_id: str`, «связанный аккаунт
на бэкенде». Для чисто-локального бота это поле **семантически лишнее**: нет бэкенда — нет backend-id.

- `IdentityProvider._resolve_backend_id` (`identity/provider.py:38-42`) на каждый апдейт читает
  cachekit-ключ `link:tg:<id>` и при отсутствии линковки **подменяет** `backend_user_id = str(tg_id)`
  (`provider.py:42`). Для локального бота этот резолв — лишний Redis-read на каждый апдейт ради поля,
  которое никто (кроме `profile`) не использует.
- `backend_user_id` потребляет **только** `profile` (`profile/usecase.py:27,33` → `gateway.py:22,33`).
  В чисто-локальном боте без `profile` поле — мёртвый груз в типе, который тащит за собой и `links.py`
  (`BACKEND_LINK_PREFIX`, `backend_link_key`).
- Тип захардкожен: убрать `backend_user_id` из `BotIdentity` — это правка **общего платформенного
  типа**, которую де-темплейт не описывает; идентичность подаётся как «платформа, не трогать»
  (`prune.md:33`). То есть предположение «у пользователя есть backend-id» вшито в каркас, а не в фичу.

Не блокер (поле можно игнорировать), но это **протекание модели «бот = фронт к бэкенду» в самый общий
тип**. Локальный бот платит лишним Redis-резолвом на апдейт и несёт поле-фантом во всех фичах.

**fix:** сделать `backend_user_id` опциональным/выносимым — например `BotIdentity` несёт только
`tg_id`+`role`, а `backend_user_id` — отдельный REQUEST-провайдер, который подключают **только** фичи,
которым он нужен (как порт). Тогда local-only бот не платит за backend-резолв и не несёт поле-фантом.
Минимум — задокументировать в де-темплейте, что `backend_user_id`/`_resolve_backend_id`/`links.py:BACKEND_*`
удаляются для бота без бэкенда.

### MEDIUM — `httpx`/`purgatory`/`tenacity` — в core-deps pylibinfra: локальный бот их физически тащит (CAT=build, CONF=high)

Extra `[tgbotkit]` (`pylibinfra/pyproject.toml:72-76`) добавляет только `aiogram`/`aiogram-dialog`/
`fluent.runtime`. Но `httpx>=0.28`, `tenacity`, `purgatory-circuitbreaker` — в **core**-deps
(`pyproject.toml:42-44`), то есть приезжают транзитивно **всегда**, даже у бота, который не делает ни
одного HTTP-вызова. Плюс `purgatory` тянет `pkg_resources`/`setuptools` (зачем пин `setuptools<81`,
`pyproject.toml:55-57`). Для чисто-локального бота это «мёртвый вес» в образе: httpx-стек +
circuit-breaker, которые не вызываются.

Это **свойство pylibinfra-упаковки, не шаблона** — pylibinfra монолитен по core (httpclient/pgkit/
storagekit/auth — всё в одном пакете, extra только для aiogram/testkit). Локальный бот не может
отказаться от httpx, не отказавшись от pylibinfra. Влияние: размер образа + поверхность зависимостей,
не функциональность. CONF=high (deps читаются прямо из pyproject).

**fix:** вне шаблона — это решение pylibinfra (вынести httpclient/pgkit/storagekit в опциональные extra,
как сделано для tgbotkit/testkit). Для шаблона — ничего; зафиксировать как «цена монолитного core
pylibinfra», осознанный trade-off (deps лениво импортятся, ничего лишнего не стартует, см. p-store).

### LOW — тест-харнес моно-`BackendClient`: локальная фича без backend тестируется «через» backend-фейк (CAT=testing, CONF=medium)

`tests/_fakes/harness.py:30,48-49,63` — `make_container` **всегда** регистрирует `FakeBackendClient`
в графе (APP-scope), даже для фич, которым backend не нужен (`start`/`lang`/notifications). Для
чисто-локального бота это означает: харнес несёт backend-фейк, которого в проде уже не будет. Не
ошибка (лишняя фабрика граф не роняет — проверено), но харнес моделирует мир «backend всегда есть»;
форк, выпиливший backend, должен ещё и переписать `harness.py` (убрать `backend`-параметр и
`FakeBackendClient`), иначе тесты тащат фантом. Де-темплейт `prune.md:8` (точка тестов) этого не
упоминает.

**fix:** сделать `backend` в `make_container` опциональным/отсутствующим по умолчанию (регистрировать
`FakeBackendClient` только когда фиче-провайдер его реально просит), или дать в `prune.md` пункт
«backend убран → почисть harness».

### INFO — единственный `HTTPCLIENT_BASE_URL` обязателен, даже если backend не используется до удаления (CAT=config, CONF=medium)

Пока `HttpClientProvider`/`BackendProvider` в графе (т.е. до полного выпиливания), `HttpConfig`
(`config.py:73-74`) читает `HTTPCLIENT_BASE_URL`. Если форк «ещё не дошёл» до удаления backend, но уже
не имеет бэкенда, оператор обязан выставить фиктивный `HTTPCLIENT_BASE_URL`, иначе httpclient-конфиг
может не подняться/клиент будет бить в никуда. Это переходное состояние, снимается полным выпиливанием
(HIGH-находка). Фиксирую как контекст, не дефект.

## Ответ на вопросы заказчика в этой области

**Насколько просто построить чисто-локального бота?** — **Просто по существу, но шероховато по
процедуре.** Архитектура локальный бот поддерживает первым классом: три из пяти reference-фич
(`start`/`lang`/`notifications`) уже чисто-локальны (Redis-only, ноль HTTP), DIP-порты позволяют
реализовать любую фичу поверх cache/pg вместо http без правки `usecase`, а tgbotkit-рантайм к backend
нейтрален (не тянет `Client` в DI, использует из httpclient только contextvar трейс-id). То есть
«нормального» локального бота построить **можно и нужно** — это не натяжка сценария.

Шероховатости все на **этапе выпиливания backend**, не на этапе работы:
1. backend убирается «всё-или-ничего» (dishka валидирует граф на старте) — оставишь `BackendProvider`
   без `HttpClientProvider`, бот не стартует;
2. `/de-template` **подталкивает** оставить `BackendProvider` (`wiring.md:10`) и относит
   `platform/backend` к «не удалять» (`prune.md:33`) — для local-only это ведёт либо к падению, либо к
   мёртвому слою;
3. `backend_user_id` вшит в общий тип `BotIdentity` — предположение «есть бэкенд» протекло в каркас
   идентичности, локальный бот платит лишним Redis-резолвом на апдейт и несёт поле-фантом;
4. harness и core-deps (httpx/purgatory) тоже «помнят» про backend.

Ни одна из шероховатостей не фатальна и не требует правки kit'а — всё чинится в шаблоне (удалить слой)
+ доработкой де-темплейта (чеклист local-only). Но **из коробки** «бэкенд» подан как дефолтное
предположение (один `BackendClient`, один `HttpClientProvider`, поле в `BotIdentity`, совет
«BackendProvider остаётся»), и потребителю-непитонисту, делающему локального бота, придётся осознанно
этот дефолт демонтировать — чего гайд сейчас не объясняет. Это симптом того же «один бэкенд by design»,
что зафиксировал t-platform, но с другой стороны: проблема не только в «несколько бэкендов», но и в
«ноль бэкендов» — оба отклонения от «ровно один HTTP-бэкенд» требуют ручной работы и недокументированы.
