# Аудит области p-testkit — pylibinfra testkit (568 LOC)

Каталог: `/root/git/sftbmb/sftbmb-core/pylibinfra/src/pylibinfra/testkit/`

## Что смотрел

Весь testkit целиком (19 файлов, 568 LOC):

- **Контейнерные fixtures** (без extra): `__init__.py`, `redis.py`, `nats.py`, `postgres.py` —
  async-context-manager'ы поверх `testcontainers` + хелперы на боевой kit (`cache()`/`bus()`/`db()`).
- **bottest** (extra `[tgbotkit]`): `bottest/__init__.py`, `bottest/runner.py` (`bind_dialogs`),
  `bottest/storage.py` (`JsonMemoryStorage`); реэкспорт `BotClient`/`MockMessageManager` из
  `aiogram_dialog.test_tools`.
- **handlertest**: `handlertest/client.py` — тест-FastAPI + httpx-ASGI + ассерты по APIError.
- **per-kit in-memory фейки**: `eventbus/recorder.py`, `audittest/recorder.py`,
  `authntest/hasher.py`, `bruteforcetest/store.py`, `txkit/tx.py`.

Сверял с прод-поведением: реальный `tgbotkit.notifications.Delivery`/`DeliveryDedup`/`storage`,
реальный `BotRunner._bind`, дефолтный кодек `RedisStorage`. Смотрел, как testkit реально
используется в шаблоне (`telegram-bot-template/tests/`) и какие фейки шаблон вынужден писать сам
(`tests/_fakes/`). Прогнал `ruff check` и `mypy` по testkit, проверил self-тесты testkit и
изоляцию импортов.

Инструментально:
- `ruff check src/pylibinfra/testkit/` → **All checks passed**.
- `mypy src/pylibinfra/testkit/` → **Success: no issues found in 19 source files**.
- `import pylibinfra.testkit` без `[tgbotkit]` → ОК (aiogram не подтягивается — изоляция держится).
- Подтвердил: дефолтный `RedisStorage(json_dumps=...)` = stdlib `json`; на `set`/`date`/`Decimal`
  даёт `TypeError` — ровно как `JsonMemoryStorage`. Паритет кодека реален.
- testkit покрыт собственными тестами: `pylibinfra/tests/testkit/test_{bottest,handlertest,
  audittest,authntest,bruteforcetest,txkit,eventbus,integration}.py`.

## Сильные стороны

1. **Framework-agnostic lifecycle** (`testkit/__init__.py:8-11`): контейнеры через
   async-CM, а не pytest-fixture — kit не завязан на pytest, переиспользуем в любом раннере.
   Чисто и by-design.

2. **`JsonMemoryStorage` — честный паритет с продом** (`bottest/storage.py:16-22`). Прод-`RedisStorage`
   сериализует stdlib-`json` (проверено инструментально), и testkit round-trip'ит тем же
   `json.dumps`/`json.loads`. Ловит `datetime`/`Decimal`/`set`/ORM в `dialog_data` в unit/flow-lane
   **до** прода. Это закрывает реальный класс багов (несериализуемый state → падение на живом Redis).

3. **`bind_dialogs` 1:1 повторяет прод-`BotRunner._bind`** (`bottest/runner.py:21-23` против
   `tgbotkit/runner/base.py:57-61`): `setup_dishka` → `setup_dialogs` строго последним. Flow-тест
   гоняет реальный пайплайн диспетчера, а не его огрызок. Возвращает `BgManagerFactory` — задел под
   фоновые сценарии.

4. **Фейки структурно совпадают с боевыми портами** (mypy-strict зелёный, Protocol проверяется
   структурно): `bruteforcetest.Store` (`bruteforcetest/store.py`) — сигнатуры
   `read/record_failure/reset/cleanup` точь-в-точь как `bruteforcekit.guard.Store`
   (`bruteforcekit/guard.py:19-28`). `eventbus.Recorder.publish(subject, payload)` удовлетворяет и
   `outboxkit.Publisher`, и `natskit.Bus.publish`. Подмена фейка на боевой не ломает типы.

5. **Реалистичные failure-фейки там, где это важно для security-kit'ов**: `bruteforcetest` даёт
   `Permissive`/`Locked`/`Recorder` (`store.py:11/24/41`) — то есть можно протестить и
   «заблокирован», и «не заблокирован», и «зафиксировал failure». Это правильный набор: фейк не
   только «happy path». Аналогично `txkit.in_rollback_tx` (`txkit/tx.py:36-49`) — реальная
   транзакция с откатом, не заглушка.

6. **handlertest бьёт через ASGI без сети** (`handlertest/client.py:28-32`) и навешивает **реальные**
   httpkit error-handler'ы (`new_app:18-24`) — то есть тестируется боевой рендер `Problem+JSON`, а
   не его имитация. Ассерты говорящие (`assert_api_error` печатает полный объект при провале).

7. **testkit сам покрыт тестами** и **изолирован по импортам**: top-level `testkit/__init__.py`
   тянет только контейнерные fixtures, `bottest` — отдельный подмодуль за extra. Не-бот-консьюмер
   `pylibinfra` не получает aiogram транзитивно.

## Находки

### MEDIUM

**[M1] Нет переиспользуемого фейка `Delivery` / хелпера фонового флоу — каждый бот пишет свой, и
он не умеет симулировать сбой доставки.**
`CAT=testing, CONF=high.`

Это прямой ответ на тревогу из задания про «FakeDelivery всегда успешен». Уточнение: **в testkit
вообще нет** фейка `Delivery`. Шаблон вынужден писать его руками —
`telegram-bot-template/tests/_fakes/delivery.py:8-17`:

```python
class FakeDelivery:
    async def send_message(self, *, chat_id, text, **kwargs) -> None:
        self.messages.append((chat_id, text))
```

Этот фейк **только** аккумулирует сообщения и **никогда не падает**. Боевой
`tgbotkit.notifications.Delivery` (`notifications/delivery.py:46-53`) имеет нетривиальную
ветку: при исключении `bot.send_message` он **логирует и проглатывает** (at-least-once-доставка не
должна валить consumer'а). Эту ветку (а это критичный инвариант доставки —
«сбой одного push не роняет весь поток событий») через `FakeDelivery` **протестить нельзя**: он
не умеет «упасть на N-й отправке». Тест-набор шаблона (`tests/unit/test_notifications.py`)
проверяет только «доставлено / дедуп / нет link → пропуск», но не «backend упал → consumer выжил».

Это симптом дырки в testkit: фоновая доставка — заявленная грабля (`rule background-updates`,
закрыта в kit), но testkit не даёт инструмента её тестировать. `bind_dialogs` возвращает
`BgManagerFactory` (комментарий «для фоновых сценариев», `bottest/runner.py:4`), но
**ни один testkit-хелпер не прогоняет реальный фоновый деливери-флоу** — нет аналога `BotClient`
для пути «событие → Delivery → окно». Грабли фона (load=True, пустой стек, EDIT не гарантирован,
изоляция request_id — `delivery.py:1-6`) остаются непокрытыми тест-китом.

*Fix:* перенести `FakeDelivery` в testkit (`bottest`/новый `notifytest`) как первоклассный фейк
с режимом инъекции ошибки (`fail_on(chat_id)` / счётчик попыток), удовлетворяющий
`Delivery`-протоколу структурно. Дать flow-хелпер «прогнать deliver_* и проверить отрисованное
окно» поверх `BgManagerFactory`, чтобы фоновый путь тестировался так же, как `BotClient`
тестирует обычный апдейт.

### LOW

**[L2] `BotClient`/bottest не покрывает побочки реального Bot — invoice/pre_checkout/медиа.**
`CAT=testing, CONF=high.`

Прямое следствие того, что `BotClient` гоняет диспетчер с `MockMessageManager`, но без боевого
`Bot`. Шаблонный flow-тест платежей честно это фиксирует
(`telegram-bot-template/tests/flows/test_payments_flow.py:3-5`): *«Клик "Купить" не делаем
(send_invoice требует реального бота)»*. То есть один из самых ответственных путей бота (счёт →
pre_checkout → successful_payment) flow-тест-китом **не проходится end-to-end** — он раскидан по
unit-тестам usecase и «kit-механике». Для not-питониста это неочевидное ограничение: «у меня есть
BotClient, почему я не могу докликать оплату до конца».

`BotClient` API минимален и заточен под диалоги: `send`/`click`/`my_chat_member_update`/
`request_chat_join` (проверено по surface). Этого достаточно для inline-диалогов, но любой выход
за пределы text+inline-keyboard (медиа, invoice, reply-keyboard-ответы, ловля исключений
хендлера) testkit не помогает протестить — это not-a-bug самого `aiogram_dialog`, но граница, про
которую testkit/доки молчат.

*Fix:* документировать границу «что bottest умеет, что — нет» (явный список: только text+inline;
invoice/медиа/pre_checkout — unit usecase). Опц. дать тонкий фейк-`Bot`, ловящий `send_invoice`/
`answer_pre_checkout_query` в список вызовов, чтобы продуктовый код вокруг счёта тестировался без
сети.

**[L3] `JsonMemoryStorage` дублирует одноимённый класс из `aiogram_dialog.test_tools`.**
`CAT=testing, CONF=medium.`

`aiogram_dialog` уже шипит `JsonMemoryStorage` (`test_tools/memory_storage.py`), который хранит
`data` как `json.dumps(data)` и тоже даёт `TypeError` на несериализуемом в `set_data`. testkit
переопределяет тот же класс с тем же именем (`bottest/storage.py:16`). Разница есть и она в пользу
testkit: версия kit'а **наследует** `MemoryStorage` (полный API + совместимость с остальной
инфра-цепочкой), а не пишет `BaseStorage` с нуля как aiogram_dialog. Но: (а) одноимённость с
библиотечным классом — ловушка для читателя (легко не понять, какой именно используется); (б) стоит
оставить хотя бы WHY-комментарий «почему свой, а не из test_tools». Не баг, гигиена.

*Fix:* комментарий-WHY в `storage.py` («наследуем MemoryStorage ради полного API/совместимости с
RedisEventIsolation-стилем, в отличие от BaseStorage-версии test_tools») либо переименовать во
избежание коллизии (`JsonRoundtripMemoryStorage`).

**[L4] Шаблонный `FakeRedis` игнорирует TTL (`ex`) — «дедуп протух по TTL» не тестируется.**
`CAT=testing, CONF=medium.`

Опять же это template-local фейк (`tests/_fakes/redis.py:16-26`), не testkit, но он закрывает дыру,
которую testkit оставил: для `DeliveryDedup` (боевой — `SET NX EX`, `notifications/dedup.py:17`) и
`guard_charge` нет готового фейка в testkit, шаблон лепит свой `set(nx, ex)`. Этот фейк
**молча игнорирует `ex`**, поэтому поведение «через TTL ключ протух → второй раз доставится» через
него не проверишь (хотя в unit-тесте это и не критично). Симптоматично: testkit даёт
`start_redis()`-контейнер, но не даёт лёгкого in-memory `Redis`-фейка под `SET NX EX` для
unit-lane — и каждый бот переизобретает полу-реализацию, которая может разъехаться с боевой
семантикой.

*Fix:* добавить в testkit (`cachetest`/`bottest`) минимальный in-memory `redis.asyncio`-совместимый
фейк, поддерживающий `set(nx, ex)` с учётом TTL (фейковые часы), чтобы дедуп/charge-guard
тестировались one-liner'ом и без дрейфа.

### INFO

**[I5] handlertest шипится в core (fastapi/httpx — core-deps), но это not-bot-инструмент.**
`CAT=build, CONF=high.` Фактологическая заметка, не претензия: `handlertest` про httpkit-консьюмера,
к боту отношения не имеет; в фокусе «строить ботов» он нерелевантен. Корректно вынесен из bottest.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?**
Да, для **типового** бота на inline-диалогах testkit даёт очень хороший happy-path-инструмент:
`BotClient`+`MockMessageManager`+`JsonMemoryStorage` гоняют реальный пайплайн диспетчера (то же
`setup_dishka→setup_dialogs`, что в проде), ловят несериализуемый state раньше прода и читаются
почти как сценарий («`send("/start")` → `click(...)` → `one_message()`»). Шаблон демонстрирует
рабочие flow-тесты start/profile/payments. **Но** два ответственных пути остаются вне зоны
комфорта testkit: **фоновая доставка** (нет фейка `Delivery` с симуляцией сбоя, нет flow-хелпера
для `deliver_*` — M1) и **платёжный send/pre_checkout** (требует реального Bot — L2). Их приходится
гонять unit-тестами usecase, а ветку «push упал → consumer выжил» — никак. Для «нормального» бота
этого хватает, но самые дорогие баги (потеря/задвоение доставки) тест-китом не ловятся из коробки.

**2. Насколько гибкая система?**
Гибкая по форме (async-CM вместо pytest-fixture → любой раннер), но **узкая по покрытию сценариев**.
testkit покрывает unit-лейн каждого kit'а (фейки портов структурно совместимы — менять реализацию
можно безболезненно) и dialog-flow. Чего нет — переиспользуемых фейков для tgbotkit-специфики
(`Delivery`, `Redis`-SET-NX-EX): их каждый бот переписывает в `tests/_fakes/` (см.
`telegram-bot-template/tests/_fakes/{delivery,redis}.py`), и эти ручные полу-реализации дрейфуют
от боевой семантики (FakeDelivery не падает, FakeRedis игнорит TTL). Это не «жёсткость
архитектуры», а **недоинвестированный testkit для фона/доставки** — лечится добавлением 2-3 фейков
в kit, без слома дизайна.

**3. Про несколько BackendClient к разным API.**
Вне области testkit напрямую, но штрих в тему: testkit-фейки **структурно-типизированы** (Protocol,
mypy-strict), а не привязаны к конкретному классу — то есть на уровне тестов «несколько разных
клиентов» проблемы не создаёт: каждый порт фейкается независимо (как `FakeBackendClient` в шаблоне
параметризуется данными). Тестовая инфра не закладывает синглтонность бэкенда — ограничение (если
оно есть) живёт в `platform/`, не в testkit. `CONF=medium` — сужу только по тестовой границе.

---
Итог: крепкий, чистый (ruff+mypy зелёные, self-тесты есть), эргономичный для диалог-flow тест-кит с
честным паритетом сериализации и проводки. Главный долг — **фон/доставка**: нет фейка `Delivery` с
инъекцией ошибки и flow-хелпера для `deliver_*`, из-за чего критичная ветка at-least-once-доставки
(сбой не валит consumer'а) не тестируется, а каждый бот переписывает дрейфующие фейки руками.
