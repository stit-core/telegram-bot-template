# Аудит области p-msg — natskit + outboxkit (pylibinfra)

## Что смотрел

Полностью прочитал оба кита:

- **natskit** (`src/pylibinfra/natskit/`): `bus.py` (core-NATS `NatsBus`), `jetstream.py`
  (`JsBus`/`StreamBus`, durable-подписки, ack/nak), `conn.py` (подключение), `config.py`,
  `module.py` (dishka `NatsProvider`), `instrumentation.py` (OTel span/метрики).
- **outboxkit** (`src/pylibinfra/outboxkit/`): `outbox.py` (порты `Store`/`LagReporter`,
  `Message`), `bus.py` (transactional-выход — insert в outbox), `worker.py` (батч-дренаж),
  `metrics.py` (`register_lag_gauge`), `module.py`, `pgstore/` (Postgres-реализация:
  `store.py`, `partitions.py`, `module.py`).
- **Связь с ботом** (область заказчика — фоновые уведомления): `tgbotkit/notifications/`
  (`router.py`, `delivery.py`, `dedup.py`, `runner.py`), `tgbotkit/runner/base.py`,
  и потребитель в шаблоне `src/bot/features/notifications/deliver.py`.

Прогнал `ruff check` и `mypy` по обоим китам — **оба чисто** (`Success: no issues found`,
`All checks passed`). Проверил тесты: `tests/natskit/`, `tests/outboxkit/`.

Особое внимание — проверка наводки смежного агента: «хендлер уведомлений делает ack даже когда
send проглотил ошибку (потенциально at-most-once)». **Подтверждаю и эскалирую** — ниже.

---

## Сильные стороны

- **Транзакционный outbox сделан правильно.** `pgstore/store.py` — `SELECT … FOR UPDATE SKIP
  LOCKED` (store.py:14-17) даёт корректный конкурентный дренаж без двойной публикации; insert
  в `outboxkit.Bus` (bus.py:20-26) идёт в открытой доменной tx → атомарность бизнес-state +
  outbox-строки. Партиционирование по месяцам с keeper'ом впереди календаря (partitions.py,
  module.py:26-31) — продуманно.
- **Worker честно at-least-once на своей половине.** `_process` (worker.py:46-62): publish →
  только потом `mark_published`; любая ошибка прерывает тик **до** пометки (worker.py:54,60),
  событие переживёт до следующего тика. `run_loop` не умирает от сбоя тика (worker.py:70-72),
  корректно реагирует на `CancelledError` (worker.py:68-69). Покрыто тестами
  (`test_worker.py`: `test_publish_error_does_not_mark`, `test_run_loop_survives_tick_error`).
- **Lifecycle подключения аккуратный.** `NatsProvider.conn` (module.py:21-32) — `yield` +
  `finally: await nc.drain()`, корректный graceful-выход. `OutboxProvider.worker`
  (module.py:31-45) отменяет задачу и **дожидается** отмены через `gather(..., return_exceptions=True)`
  — закрывает классическую грабли «task was destroyed but it is pending».
- **GC-safety тасок.** И `NatsBus`, и `JsBus` держат `self._tasks: set[Task]` с
  `add_done_callback` (bus.py:37-39,62-64; jetstream.py:60,111-113) — без этого asyncio
  собрал бы handler-таски weakref'ом до завершения. Грамотно, с WHY-комментарием.
- **Backpressure через `Semaphore`** скоординирован с `max_ack_pending` на JS-консьюмере
  (jetstream.py:56,106) — in-flight не превысит лимит ни на стороне приложения, ни на брокере.
- **Observability на уровне.** W3C trace-context инжектится в nats-headers и извлекается на
  consumer'е (instrumentation.py:62,67) → consumer-span child producer'а сквозь брокер; полный
  набор метрик published/consumed/inflight/duration + `outbox_lag_seconds` как observable gauge.
- **Чистая порт-абстракция.** `Store`/`LagReporter` (outbox.py) — `runtime_checkable` Protocol;
  доменный код зависит от порта, Postgres подключается структурно. `StreamBus`-протокол +
  `DisabledStreamBus` (jetstream.py:29-43) — корректный null-object, когда JetStream выключен.

---

## Находки

### CRITICAL

#### 1. JetStream-подписка делает `ack()` после того, как Delivery проглотил ошибку отправки → реальный at-most-once, тихая потеря уведомлений

`KEY=yes`. Это не «потенциально», а детерминированная дыра в гарантии доставки, и она
усугублена дедупом.

Цепочка (всё в ките, шаблон ни при чём):

1. `JsBus._handle_one` (jetstream.py:123-150): вызывает `handler(msg.data)`; **только если
   handler бросил** — `await msg.nak()` (line 142) и `return`; иначе (line 144) `await msg.ack()`.
   Семантика правильная — *при условии, что ошибка доставки доходит до handler'а исключением*.
2. Но handler — это `wrap` из `subscribe_stream_json` → `NotificationRouter._bind.consume`
   (router.py:30-33) → `OrderDeliverer.on_order_paid` → `delivery.send_message`.
3. `Delivery.send_message` (delivery.py:46-53) **ловит `except Exception` и проглатывает**
   (только лог, line 50-51). `start_dialog` (delivery.py:40-44) — то же самое.

Итог: при сбое `bot.send_message` (Telegram 5xx / сетевой блип / flood-wait / бот заблокирован)
исключение **не** доходит до `_handle_one`, тот видит «успех» и делает `ack()`. Сообщение
подтверждено брокеру и потеряно навсегда. **At-most-once**, ровно вопреки заявленному в доках
«at-least-once JetStream» (dedup.py:1, deliver.py:6, background-updates.md).

**Усугубление дедупом.** `OrderDeliverer.on_order_paid` зовёт `self._dedup.seen(...)` (deliver.py:29)
**до** `send_message` (deliver.py:34), а `DeliveryDedup.seen` — это `SET NX EX` (dedup.py:17),
который **сразу помечает ключ виденным**. То есть даже если бы redelivery случился (его нет, см.
выше — был `ack`), он был бы отброшен дедупом. Dedup-before-send + ack-on-swallowed-error = двойная
гарантия потери на любом сбое отправки.

Почему это by-design-конфликт, а не просто баг одного файла: `Delivery` *намеренно* глотает ошибку
(«at-least-once-доставка не должна валить consumer'а», delivery.py:42) — разумно против poison-
сообщения. Но `JsBus` интерпретирует «handler не бросил» как «доставлено» и аккает. Две половины
кита держат **взаимоисключающие** контракты: одна говорит «я никогда не сигналю об ошибке наверх»,
вторая «отсутствие ошибки = ack». В стыке — гарантия рассыпается.

`SEV=critical | CAT=errors | CONF=high`

**Fix (любой из, в порядке предпочтения):**
- Дать `_handle_one` различать «доставлено / не доставлено» вместо «бросил / не бросил»: handler
  возвращает признак (или kit вводит явный `Ack`/`Nak`/`Term`-результат), `Delivery` при сбое
  возвращает «не доставлено» → `nak(delay=...)`, а не глотает молча.
- Либо: `Delivery` глотает только **терминальные** ошибки (бот заблокирован, чат удалён — толку
  ретраить нет → `term()`), а транзиентные (5xx, flood-wait, таймаут) пробрасывает → `nak`.
- И обязательно: перенести `dedup.seen()` **на момент после успешной отправки** (commit-after-send),
  иначе ретрай всё равно будет отброшен. Сейчас дедуп защищает не «от повторной доставки», а «от
  повторной *попытки*».
- Добавить `max_deliver` + DLQ-subject на консьюмере (см. находку #2), чтобы ретраи не были вечными.

---

### HIGH

#### 2. JS-консьюмер без `max_deliver`/backoff → poison-сообщение уходит в hot-loop редоставки

`KEY=yes`. `ConsumerConfig` (jetstream.py:101-107) задаёт `ack_policy=EXPLICIT`, `ack_wait`,
`max_ack_pending` — но **нет** `max_deliver` и нет `backoff`. При устойчиво падающем handler'е
`_handle_one` делает `msg.nak()` **без delay** (jetstream.py:142) → брокер немедленно
передоставляет → снова падает → … Бесконечный tight-loop на одном сообщении (до `max_age`
стрима, по умолчанию 7 дней), жжёт CPU/трафик и забивает `max_ack_pending`-слот.

`nats-py` 2.15 поддерживает `nak(delay=...)` (проверено: сигнатура `nak(self, delay=None)`), но
kit его не использует. Без `max_deliver` нет и DLQ — «ядовитое» событие невозможно отложить в
сторону.

Замечу: для *текущего* потребителя (notifications) это смягчено тем, что `Delivery` глотает ошибку
→ handler не бросает → идёт `ack`, а не `nak` (см. находку #1). То есть hot-loop проявится у
**любого другого** потребителя `subscribe_stream`, который честно бросает из handler'а — а именно
так задуман контракт `Handler` для не-notifications-подписчиков. Это негибкость кита: «правильный»
способ (бросить из handler) ведёт в вечный редоставку-цикл.

`SEV=high | CAT=correctness | CONF=high`

**Fix:** добавить в `ConsumerConfig` `max_deliver` (из cfg, дефолт ~5) и `backoff`/`nak(delay)`
с экспоненциальной паузой; при исчерпании `max_deliver` — `msg.term()` + публикация в DLQ-subject
(или хотя бы метрика+лог), чтобы стрим не копил вечных «ядовитых».

#### 3. Реконнект подключён, но без error/closed/reconnected-callback'ов и без сигнала о деградации

`SEV=high | CAT=async | CONF=medium`. `nats.connect` (conn.py:23-28, module.py:24-28) задаёт
`reconnect_time_wait` и `max_reconnect_attempts=60` — но **не** передаёт `error_cb`,
`disconnected_cb`, `reconnected_cb`, `closed_cb`. Последствия:

- После исчерпания `max_reconnects` (60 попыток × 2с ≈ 2 мин) клиент **закрывается насовсем**,
  и **ничего об этом не сигналит**: подписки молча мертвы, бот считает себя живым. `Conn.healthy`
  (conn.py:17-19) проверяется только health-probe'ом (`probe`, module.py:47-51) — он отловит, но
  только если кто-то его дёргает; авто-восстановления/алерта нет.
- Push-консьюмер JetStream после долгого разрыва **не переустанавливает подписку** сам — `JsBus`
  не реагирует на `reconnected_cb`. Durable-консьюмер на сервере переживёт реконнект, но
  client-side subscription может потребовать ре-subscribe; без callback'а это не обрабатывается.
- Дефолт `max_reconnects=60` означает: при разрыве NATS дольше ~2 минут уведомления **тихо
  выключаются до рестарта бота**. Для системы с заявленной at-least-once-доставкой это сюрприз.

`CONF=medium` (часть поведения зависит от рантайма nats-py при долгом разрыве — точную
ре-подписку push-консьюмера не воспроизводил локально).

**Fix:** прокинуть `error_cb`/`disconnected_cb`/`reconnected_cb`/`closed_cb` (лог + метрика
`nats_connection_state`), на `reconnected_cb` — переустановить JS-подписки; рассмотреть
`max_reconnects=-1` (бесконечно) для consumer-процесса, как принято для долгоживущих сервисов.

---

### MEDIUM

#### 4. Нулевое тестовое покрытие ack/nak-семантики JetStream — самая хрупкая механика не проверена

`SEV=medium | CAT=testing | CONF=high`. Единственный интеграционный тест natskit
(`tests/natskit/test_integration.py`) гоняет **core-NATS** roundtrip (`NatsBus` /
`subscribe_json`), а `JsBus` / `subscribe_stream` / ack / nak / redelivery — **не покрыты вообще**
(нет ни одного теста, дёргающего `JsBus._handle_one`). Именно тут живёт критическая находка #1 и
hot-loop #2. `test_bus.py` — про core-bus; `tests/outboxkit/` хорошо покрывает worker, но не
JS-сторону. Дыра в гарантиях прошла бы любой текущий `make check` незамеченной.

**Fix:** интеграционный тест на `NatsContainer` с JetStream: (а) handler бросает → `nak` →
сообщение передоставлено; (б) handler-обёртка глотает ошибку → проверить, что текущее поведение
именно теряет сообщение (golden-тест на регрессию после фикса #1); (в) `max_deliver` исчерпан →
не вечный цикл.

#### 5. Outbox теряет порядок внутри subject при сбое публикации в середине батча

`SEV=medium | CAT=correctness | CONF=medium`. `Worker.tick` (worker.py:40-44) публикует батч
**последовательно** и при ошибке на N-м сообщении (worker.py:50-54) `raise` прерывает тик: первые
N-1 уже `mark_published`, N-е и далее остаются. На следующем тике `list_unpublished` отдаёт их в
порядке `created_at, id` (store.py:16) — то есть в рамках батча порядок не нарушится. Но если
параллельно работает несколько worker-инстансов (`SKIP LOCKED` это допускает), относительный
порядок публикации между ними **не гарантирован** — два события одного subject могут уйти в NATS
в обратном порядке. Для бота-уведомлений это, как правило, неважно (события идемпотентны по ключу),
но если потребитель закладывается на FIFO per-subject — это сюрприз, нигде не задокументированный.
`CONF=medium`: проблема проявляется только при >1 worker и заказе на строгий порядок.

**Fix:** задокументировать «outbox не гарантирует строгий FIFO per-subject при конкурентных
worker'ах»; кому нужен порядок — single-worker + остановка батча на первой ошибке (уже так) или
ordering-ключ на стороне NATS.

#### 6. `register_lag_gauge` захватывает event-loop через deprecated `get_event_loop()` на этапе регистрации

`SEV=medium | CAT=async | CONF=medium`. `register_lag_gauge` (metrics.py:49) делает
`loop = asyncio.get_event_loop()` в момент **регистрации провайдером** (вызывается в
`OutboxProvider.worker`, module.py:36-37 — внутри async-провайдера, так что loop есть). Но:

- `asyncio.get_event_loop()` без running-loop deprecated в 3.12+ (в running-контексте ок, но
  стиль хрупкий — корректнее `get_running_loop()`).
- Захваченный `loop` используется из фонового потока `PeriodicReader` через
  `run_coroutine_threadsafe` (metrics.py:53). Если loop к моменту дёрга закрыт (shutdown-гонка
  между остановкой loop и последним flush'ем метрик ридером) — `fut.result()` бросит, но это
  поглощается `except Exception: return []` (metrics.py:55-57). Тихо, но не падает — приемлемо.
  Риск: gauge молча перестаёт эмитить, диагностики нет.

`CONF=medium`. **Fix:** `asyncio.get_running_loop()`; на закрытом loop'е логировать debug, чтобы
«тихий» отказ gauge был заметен в наблюдаемости.

---

### LOW / INFO

#### 7. `subscribe_stream` дублирует `durable` в двух местах

`SEV=low | CAT=dx | CONF=high`. `js.subscribe(..., durable=durable, ..., config=ccfg)` где
`ccfg.durable_name=durable` тоже (jetstream.py:101-102,116). Дублирование безвредно (значения
совпадают), но если когда-то разойдутся — неочевидный приоритет. Косметика.

#### 8. `ensure_streams` хардкодит `subjects=["{name}.>"]`, `storage=FILE` — негибко

`SEV=low | CAT=flexibility | CONF=high`. `JsBus.ensure_streams` (jetstream.py:69-74) задаёт
один subject-wildcard на стрим и только file-storage, без возможности memory-storage,
нескольких subject-паттернов, replicas, max_bytes/max_msgs. Для одного бота норм; для
переиспользуемого кита — узкое место. Retention/max_age конфигурируемы (config.py:16-21), но
остальное — нет. by-design для тонкого юзкейса, но стоит знать.

#### 9. `ensure_streams` идемпотентен только при совпадении конфигурации стрима

`SEV=low | CAT=correctness | CONF=low`. `add_stream` (jetstream.py:77) на существующем стриме с
**другим** конфигом (изменили retention/max_age в env) у JetStream может вернуть ошибку или молча
не применить — kit оборачивает любое исключение в `RuntimeError` (jetstream.py:78-79), бот не
стартует. Не `update_stream`. `CONF=low` (зависит от версии сервера). На проде смена параметров
стрима потребует ручного вмешательства.

---

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** В части messaging — да, фундамент крепкий:
транзакционный outbox с партициями и `SKIP LOCKED`, дедуп, трейс сквозь брокер, аккуратный
lifecycle. **Но** заявленная гарантия «надёжная доставка уведомлений» сейчас **не выполняется**
из-за находки #1: на любом сбое отправки в Telegram (а они регулярны — flood-wait, юзер
заблокировал бота, 5xx) уведомление **тихо теряется** и не ретраится. Для «нормального» бота с
платёжными/статусными пушами это серьёзно: заказчик будет уверен, что at-least-once работает (так
написано в доках), а по факту — at-most-once. Это надо чинить до прода.

**2. Насколько гибкая система?** На уровне natskit — средне. Outbox-порты и `StreamBus`-протокол
красиво расширяемы. Но JS-консьюмер зашит жёстко: нет `max_deliver`/backoff/DLQ (#2), нет
callback'ов реконнекта (#3), `ensure_streams` хардкодит структуру стрима (#8). «Правильный» способ
обрабатывать ошибку в произвольном subscriber'е (бросить из handler) ведёт в вечный redelivery-loop
— то есть гибкость есть для happy-path, но обработка отказов недодумана и негибка.

**3. Про `BackendClient`/несколько API** — вне моей области (это platform/httpclient, не
nats/outbox). Прямого аналога «один захардкоженный клиент» в natskit/outboxkit нет: `StreamBus` —
протокол, `Store` — порт, оба допускают несколько реализаций. Тревога заказчика к messaging-слою
не относится.
