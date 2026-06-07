# Аудит d-async — async / конкурентность (сквозной синтез)

## Что смотрел

Линза сквозная — собирал async-картину по всем китам, через которые бот живёт под нагрузкой и при
разрывах соединений. Прочитал полностью:

- **Lifecycle клиентов** (создание/закрытие, утечки, порядок teardown): `tgbotkit/runner/base.py`
  (`_BaseRunner`), `runner/polling.py`, `runner/webhook.py`; провайдеры redis (`cachekit/module.py`),
  nats (`natskit/module.py`, `conn.py`), httpx (`httpclient/module.py`, `client.py`), bot
  (`tgbotkit/module.py`), pg-pool (`pgkit/module.py`), s3 (`storagekit/s3/module.py`).
- **Таски и их отмена**: `natskit/bus.py` + `jetstream.py` (детач-таски `_handle_one`, `_tasks`,
  semaphore), `timerkit/timerkit.py`, `outboxkit/worker.py` + `module.py`, `httpkit/server.py`
  (`_serve_task`).
- **CancelledError**: `timerkit`, `outboxkit/worker`, `precheckout` (`wait_for`).
- **Гонки в dedup/throttle/cache**: `middleware/throttle.py`, `middleware/dedup.py`,
  `notifications/dedup.py`, `cachekit/cache.py` (tag-invalidation), `payments/guard.py`.
- **BgManager-фон**: `notifications/{delivery,runner,router,dedup}.py`, бот-потребитель
  `features/notifications/deliver.py`.
- **deprecated get_event_loop / threadsafe**: `outboxkit/metrics.py`.
- **Concurrency-модель апдейтов**: aiogram `start_polling(handle_as_tasks=True)` vs webhook
  `feed_update` синхронно; contextvar-изоляция (`request_id.py`, `httpclient/reqid.py`).
- **Блокирующее в loop**: grep по `time.sleep/open/.read()/threading/run_coroutine_threadsafe`;
  `fluent.runtime` file-IO под `i18n/translator.py`.

**Эмпирически воспроизвёл** (uv run python, Python 3.13.5, nats-py 2.15.0, redis 8.0.0):
- разбор `nats.aio.client.Client.drain` → `Subscription._drain` → `_pending_queue.join()` и
  модельный репро, что drain **не** дожидается детач-таски `_handle_one` (см. находку #1);
- `Msg.ack` → `self._client.publish(self.reply)` — ack по закрытому соединению бросает;
- `get_event_loop()` внутри running-loop вернул running-loop (ок), вне loop'а — `RuntimeError`;
- `start_polling` дефолт `handle_as_tasks=True` (апдейты — конкурентные таски).

Уже найденное смежными агентами (throttle INCR без гарантии EXPIRE; tag-invalidation не атомарна;
`register_lag_gauge` через `get_event_loop()`; `NotificationRunner.drain` пустой; dedup-before-send
+ Delivery глотает ошибку) — **перепроверил, подтверждаю**, и связал в системную картину ниже.

`ruff`/`mypy` по затронутым китам — чисто (сверял в отчётах p-msg/p-store/k-tgbot-mw, перепроверять
не дублирую).

---

## Системная картина: что сломается под нагрузкой / при разрыве соединений

Три независимых дефекта складываются в **один сценарий гарантированной тихой потери уведомления**
при штатном graceful-shutdown консьюмера (деплой/рестарт — самое частое событие в жизни сервиса):

1. JetStream доставил `order-paid` → `JsBus.cb` спаунит детач-таску `_handle_one`
   (`jetstream.py:111`) и **сразу возвращается**.
2. Хендлер зовёт `dedup.seen("order-paid:<id>")` → атомарный `SET NX EX` **сразу помечает ключ
   виденным** (`notifications/dedup.py:17`, до отправки).
3. Идёт рестарт. `container.close()` → `NatsProvider.conn finally: nc.drain()` (`module.py:32`).
   Драйн дожидается только опустошения `_pending_queue` подписки — а `cb` уже вернулся, **детач-
   таска `_handle_one` в полёте не учитывается** (находка #1). `nc.drain()` закрывает соединение.
4. `_handle_one` доходит до `msg.ack()` → `publish` по закрытому соединению → исключение **внутри
   детач-таски**, наверх не всплывает (только «Task exception was never retrieved»), ack не прошёл.
5. После рестарта JetStream **редоставляет** неакнутое сообщение (at-least-once, корректно). Но
   `dedup.seen()` уже стоит (шаг 2) → `on_order_paid` видит `seen → return` (`deliver.py:29`) →
   возвращается «успешно» → `msg.ack()` → **сообщение подтверждено и потеряно навсегда**.

То есть к двум окнам потери, которые нашли p-msg/k-tgbot-feat (ack-after-swallowed-error +
dedup-before-send), добавляется **третье**: ack/nak в детач-таске по уже закрытому при драйне
соединению. Все три бьют в одну точку — доставку push'а об оплате, и все три проявляются именно
под нагрузкой/при рестарте, а не на happy-path. Для бота, где push об оплате критичен, это значит:
**заявленный at-least-once на практике — at-most-once, и хуже всего ведёт себя ровно при деплое.**

---

## Сильные стороны

- **GC-safety детач-тасок сделана правильно.** `NatsBus`/`JsBus` держат `self._tasks: set[Task]` +
  `add_done_callback` (`bus.py:39,62-64`; `jetstream.py:60,111-113`) — без этого asyncio собрал бы
  handler-таски weakref'ом до завершения. Классическая грабля закрыта, с WHY-комментарием.
- **Отмена долгоживущих тасок — образцово.** `timerkit.Runner.stop` и `OutboxProvider.worker`
  (`timerkit.py:29-35`, `outbox module.py:42-45`): `task.cancel()` + `await gather(...,
  return_exceptions=True)` — дожидаются фактической отмены, закрывают «task was destroyed but it
  is pending». `CancelledError` корректно ре-raise'ится в циклах (`worker.py:68-69`,
  `timerkit.py:41-42`), а не глотается. Это правильный паттерн, многие его ломают.
- **Lifecycle сетевых клиентов через async-generator-провайдеры.** redis (`cachekit/module.py:21-32`),
  httpx (`httpclient/module.py:17-24`), pg-pool, s3, bot (`tgbotkit/module.py:78-81`) — все на
  `yield` + `aclose`/`drain`/`close` в `finally`. Двойного close нет (FSM/dedup/cache только держат
  ссылку, не владеют). Утечек ресурсов в нормальном пути не нашёл.
- **Backpressure скоординирован.** `Semaphore(max_in_flight)` на стороне consumer'а
  (`jetstream.py:56,110`) согласован с `max_ack_pending` на JS-консьюмере (`:106`); `acquire` в
  `cb` до спауна таски, `release` в `_on_done` — in-flight не превысит лимит. Грамотно.
- **contextvar-изоляция корректна.** `request_id` ставится `set`→`reset(token)` строго в
  `try/finally` (`request_id.py:25,39`; `delivery.py:36-44,47-53`). Под `handle_as_tasks=True`
  каждый апдейт — своя таска со своей копией contextvar, кросс-протечки `request_id` между
  конкурентными апдейтами нет.
- **`precheckout` — корректная отмена по дедлайну.** `wait_for(decide(query), timeout=9.0)`
  (`precheckout.py:41`) < 10с Telegram, на таймаут `decide` отменяется, fail-closed. Cancel
  пробрасывается в `decide`-корутину штатно.
- **httpx-клиент конкурентно-безопасен.** Один `AsyncClient` шарится между конкурентными
  апдейтами (httpx это поддерживает — внутренний connection-pool); retry/breaker оборачивают
  каждый вызов отдельно (`client.py:113-119`), общего мутабельного состояния, портящегося гонкой,
  в hot-path нет (breaker-`prev`-dict обновляется из callback'а в loop'е, single-thread).

---

## Находки

### HIGH

#### 1. `nc.drain()` не дожидается детач-тасок `_handle_one` → ack/nak по закрытому соединению на shutdown + потеря сообщения (CAT=async, CONF=high, KEY=yes)

`JsBus.cb` (`jetstream.py:109-113`) и `NatsBus.cb` (`bus.py:60-64`) на каждое сообщение делают
`await sem.acquire()` и **спаунят детач-таску** `create_task(self._handle_one(...))`, после чего
`cb` **сразу возвращается**. nats-py `Subscription._drain` дожидается только
`self._pending_queue.join()` — а `task_done()` помечается сразу после возврата `cb`
(`subscription._wait_for_msgs`, `finally: _pending_queue.task_done()`), т.е. **до** того, как
`_handle_one` отработает. Значит `nc.drain()` (`natskit/module.py:32`, единственный teardown
JS-подписок — `NotificationRunner.drain` пустой) считает подписку дренированной, пока детач-таски
ещё в полёте, и закрывает соединение.

Дальше `_handle_one` доходит до `msg.ack()` → `self._client.publish(self.reply)` (проверено по
`nats.aio.msg.Msg.ack`) → publish по закрытому соединению бросает; исключение оседает в детач-таске
(«Task exception was never retrieved»), ack не прошёл. Сообщение редоставится после рестарта — что
**в одиночку безопасно** (at-least-once), но в связке с dedup-before-send (`deliver.py:29` ставит
`seen` до отправки) редоставка отбрасывается дедупом → потеря (см. «Системная картина»).

Воспроизведено модельно: `queue.join()` возвращает `handler_started=True, handler_finished=False`
— драйн отпустил, пока детач-хендлер в полёте.

Это **не** дубль «runner.drain пустой» из k-tgbot-feat: там вывод «teardown через закрытие
соединения, in-flight передоставятся — приемлемо». Здесь показываю, что закрытие соединения
происходит **внутри** in-flight ack'а (не после него), плюс ack может вообще не пройти, плюс
редоставка глушится дедупом. Заявление p-msg «`NatsProvider.conn` finally: drain — корректный
graceful» верно для publisher'а, но **не** для consumer'а с детач-тасками.

**Fix:** `JsBus`/`NatsBus` должны иметь реальный `drain()`: остановить приём (`unsubscribe`),
затем `await asyncio.gather(*self._tasks, return_exceptions=True)` (дождаться текущих
`_handle_one`, чтобы их `ack/nak` прошли по ещё живому соединению), и **только потом**
`nc.drain()`. Вызвать его из `NotificationRunner.drain()` / `_BaseRunner._cleanup` **до**
`container.close()`. В паре с фиксом dedup-before-send (commit-after-send) это закрывает потерю.

### MEDIUM

#### 2. Throttle: `INCR` без гарантированного `EXPIRE` → «вечный бан» окна при отмене на shutdown (CAT=async, CONF=high, KEY=no)

`throttle.py:27-29`: `count = INCR(key); if count == 1: EXPIRE(key, 1)`. Между двумя командами нет
атомарности. Под `handle_as_tasks=True` апдейты — конкурентные таски; на graceful-shutdown aiogram
**отменяет** незавершённые update-таски. Если `CancelledError` прилетит ровно между `INCR` и
`EXPIRE` (первый инкремент окна), ключ остаётся **без TTL** — этот юзер залочен в окне навсегда
(до ручной чистки redis), т.к. `count` уже `≥1` и при следующих апдейтах никогда не сбросится.
Подтверждаю находку k-tgbot-mw #3 и уточняю триггер: не абстрактный «процесс упал», а штатная
отмена update-таски на shutdown под конкурентной моделью aiogram — то есть это происходит при
каждом деплое под нагрузкой, для тех юзеров, чей апдейт попал в окно отмены.

Дефолт `throttle_rps=0` (off), поэтому MEDIUM, не HIGH.

**Fix:** атомарно — Lua (`INCR`+`EXPIRE` за один eval) или `pipeline().incr(key).expire(key, 1,
nx=True)` (`EXPIRE … NX` в redis 8 — есть), чтобы TTL ставился безусловно, не только «первым».

#### 3. Webhook-рантайм: `feed_update` синхронно блокирует ответ Telegram → head-of-line blocking и таймаут-редоставки под нагрузкой (CAT=async/performance, CONF=high, KEY=no)

`runner/webhook.py:25-29`: `_handle` делает `await self._dp.feed_update(self._bot, update)` и
только потом `return Response(200)`. То есть HTTP-воркер держит соединение до **полной** обработки
апдейта (диалог-рендер + backend-вызовы внутри хендлера). Контраст с polling, где
`start_polling(handle_as_tasks=True)` гонит каждый апдейт **отдельной конкурентной таской**
(`polling.py:13-17`, дефолт aiogram). Под нагрузкой медленный backend-вызов в хендлере
**удерживает** HTTP-воркер; при превышении webhook-таймаута Telegram (~60с) апдейт считается
недоставленным и **редоставляется** → дублирование (ловится dedup-middleware по `update_id` —
хорошо) + рост латентности и забивание воркеров. Два рантайма ведут себя под нагрузкой **по-разному**
(webhook — синхронно/HOL-blocking, polling — конкурентно), что нигде не отражено.

**Fix:** в webhook принять апдейт в фон — `feed_webhook_update` / `create_task(feed_update(...))`
с учётом backpressure (ограничить конкурентность семафором), вернуть 200 сразу. Либо явно
задокументировать, что webhook-обработка синхронна, и тяжёлый I/O в хендлерах под webhook —
антипаттерн (тогда оба рантайма хотя бы предсказуемы).

#### 4. tag-invalidation в cachekit не атомарна — теряет ключи под конкуренцией (CAT=async, CONF=high, KEY=no)

Перепроверяю и подтверждаю находку p-store. `RedisCache.set` (`cache.py:53-59`) делает `set`+`sadd`+
`expire` тремя командами без `pipeline/MULTI`; `invalidate_by_tag` (`:66-72`) — `smembers`→`delete`→
`delete(tag_key)` тоже не атомарно. Под конкурентным `set(tags=[t])` между `smembers` и
`delete(tag_key)` новый ключ остаётся живым, а тег-сет удалён → запись «провисает»
неинвалидируемой (stale). Для бота **не задействовано** (locale/onboard/dedup — простые ключи,
без тегов), риск в текущем шаблоне нулевой; как библиотечный кэш-примитив для бэкендов — реальный
источник stale-данных.

**Fix:** `set`+тег-записи в `pipeline(transaction=True)`; инвалидация — Lua (`SMEMBERS`+`DEL`
атомарно).

### LOW / INFO

#### 5. `register_lag_gauge` — deprecated `get_event_loop()` (CAT=async, CONF=high, KEY=no)

`outboxkit/metrics.py:49`: `loop = asyncio.get_event_loop()`. Перепроверил на Python 3.13.5: в
фактическом call-site (`OutboxProvider.worker`, async-провайдер с running-loop'ом) возвращает
running-loop — **работает**. Но паттерн хрупкий: вне running-loop'а (если кто-то когда-то вызовет
`register_lag_gauge` синхронно) — `RuntimeError`. `outboxkit` ботом не используется. Подтверждаю
находку p-msg как «есть, но в текущем call-site безвредно».

**Fix:** `asyncio.get_running_loop()` (явно требует running-loop, что и есть инвариант call-site'а).

#### 6. `FluentTranslator` читает `.ftl` синхронно в event-loop'е на первый рендер локали (CAT=async/performance, CONF=medium, KEY=no)

`i18n/translator.py:29-39`: `FluentLocalization` строится лениво на первый `for_locale(locale)`, а
`fluent.runtime` читает файлы через `codecs.open(...).read()` (проверено по
`FluentResourceLoader.resources`) — **синхронный file-IO в loop'е**. После первого рендера каждой
локали результат кэшируется в `self._cache`, так что это однократный cold-start-блок на локаль, не
per-request. Под `handle_as_tasks=True` два конкурентных первых рендера одной новой локали оба
построят `FluentLocalization` (двойное чтение, last-write-wins в dict) — без порчи, лишняя работа.
Малозначимо; всплывёт при холодном старте с многими локалями.

**Fix (если важен cold-start):** прогреть локали на старте (`emit_startup`) или вынести первичную
загрузку в executor. Для тонкого юзкейса можно оставить как есть.

#### 7. JS-консьюмер без `max_deliver`/`nak(delay)` → hot-loop редоставки для честного хендлера (CAT=async, CONF=high, KEY=no)

Подтверждаю p-msg #2 с async-акцентом: `nak()` без delay (`jetstream.py:142`) + отсутствие
`max_deliver` (`:101-107`) → для подписчика, который честно бросает из хендлера, брокер
передоставляет **немедленно** в tight-loop, забивая `max_in_flight`-семафор и Semaphore-слоты —
консьюмер деградирует под одним «ядовитым» сообщением. Для текущих notifications смягчено тем, что
`Delivery` глотает (handler не бросает → ack), но это и есть корень потери (#1/системная картина).

**Fix:** `max_deliver` (из cfg) + `nak(delay=backoff)` + `term()`/DLQ на исчерпании.

---

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** По async-механике — фундамент в основном крепкий:
отмена долгоживущих тасок образцовая (timerkit/outbox), GC-safety детач-тасок закрыта,
lifecycle-клиенты на `yield`+`aclose` без утечек, contextvar-изоляция корректна,
backpressure-семафор согласован с брокером, `precheckout` правильно отменяется по дедлайну. **Но**
одна async-дыра реальна и бьёт в самый чувствительный путь: при graceful-shutdown консьюмера (т.е.
при каждом деплое) `nc.drain()` закрывает соединение, не дождавшись детач-тасок доставки
(находка #1), а в связке с dedup-before-send это — тихая потеря push'а об оплате. Заявленный
at-least-once на практике превращается в at-most-once именно под рестартом. Это надо чинить до
прода; правится локально в ките (реальный `drain` у `JsBus`/`NatsBus` + commit-after-send).

**2. Насколько гибкая система?** Async-каркас гибок там, где это каркас (порты `Store`/`Cache`,
Semaphore-настройки, сменные резолверы). Негибкость — в обработке отказов под конкуренцией:
жёсткий webhook-рантайм без фонового приёма (#3, HOL-blocking), JS-консьюмер без
`max_deliver`/backoff (#7), throttle/cache-операции не атомарны (#2, #4). То есть happy-path
конкурентно здоров, а отказо-/shutdown-поведение недодумано и местами зашито.

**3. Тревога про один BackendClient к одному API** — вне моей линзы (это `platform/backend` +
httpclient-фасад). С async-стороны замечу только: `httpx.AsyncClient` конкурентно-безопасен и
шарится между апдейтами штатно; circuit-breaker и contextvar-`request_id` — на процесс, не на
клиент, так что несколько httpclient'ов к разным API подхватят один сквозной `request_id` (это
желаемо для трейса) и каждый свой breaker. Async-препятствий завести несколько клиентов нет — это
решение шаблона, не предел библиотеки.

Итог по линзе: async-каркас на ~85% аккуратный и идиоматичный, но **shutdown-путь консьюмера
(находка #1)** ломает заявленную гарантию доставки именно при рестарте под нагрузкой, и это
центральная async-проблема платформы; остальное (throttle-атомарность, webhook-HOL, tag-cache,
get_event_loop) — точечные дефекты разной остроты, все чинибельны в ките.
