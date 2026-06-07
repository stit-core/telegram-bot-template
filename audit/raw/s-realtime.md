# Стресс-тест s-realtime — высоконагруженные realtime-уведомления (NATS пачками → много юзеров)

## Сценарий

Бот с realtime-пушами: внешние события через NATS JetStream летят пачками (тысячи/мин), должны
доходить до **многих** пользователей быстро, с дедупом, упорядоченно, с уважением к Telegram
rate-limits (**30 msg/s** global, **1 msg/s** на чат). Прохожу путь
`features/notifications/deliver.py` → `tgbotkit/notifications/{router,delivery,dedup,runner}` →
`natskit/jetstream.py` (push-консьюмер JetStream, ack/nak, backpressure) → `bot.send_message` →
shutdown/`BgManager`. Вопрос: масштабируется ли механика или это демо-уровень, и где «первая
потеря/блокировка».

## Что смотрел (по реальному коду)

- **Транспорт**: `natskit/jetstream.py` (push-`js.subscribe(cb=...)`, `ConsumerConfig`, semaphore,
  `_handle_one` ack/nak), `natskit/conn.py`/`module.py` (реконнект), `natskit/config.py`
  (`NATS_JS_MAX_IN_FLIGHT`, `ack_wait`, `max_age`, retention).
- **Доставка**: `tgbotkit/notifications/delivery.py` (`send_message`/`start_dialog` поверх
  Bot/BgManager, swallow-on-error), `dedup.py` (`DeliveryDedup.seen` = `SET NX EX`), `router.py`,
  `runner.py` (`drain` — пустышка), `runner/base.py` (`_cleanup`), `module.py` (`Bot(...)` —
  дефолтная сессия).
- **Потребитель**: `features/notifications/deliver.py` (`OrderDeliverer.on_order_paid`: dedup →
  резолв `chat_id` по cache → send), `__init__.py`/`extensions.py` (проводка `build_router`),
  `platform/links.py` + `start/gateway.py` (как пишется `chat_link`).
- **Эмпирика** (`uv run`, aiogram 3.28.2, nats-py 2.15): подтвердил, что `js.subscribe` — **push**,
  `flow_control=False`/`idle_heartbeat=None` по умолчанию, `Msg.nak` поддерживает `delay`,
  `AiohttpSession.make_request` **не** ретраит `TelegramRetryAfter` (raise), а в tgbotkit **нет
  ни одного** rate-limiter/Semaphore/sleep на исходящем пути (grep по всему `tgbotkit`).

Опираюсь на смежные отчёты (`p-msg`, `k-tgbot-feat`, `t-feat-lang-notif`, `d-async`,
`d-resilience`) — общую дыру «mark-before-send + ack-after-swallow + drain не ждёт детач-таски»
**подтверждаю по коду** и не пересказываю целиком, а смотрю под нагрузочной линзой: что из этого
становится **массовым** при тысячах событий/мин, плюс добавляю то, что у них не было целью —
**rate-limit/flood-control, backpressure-потолок, ordering под конкуренцией**.

---

## VERDICT: blocked

Механика — **демо-уровень для realtime fan-out**. Happy-path на низком темпе работает, но при
заявленной нагрузке (тысячи/мин на много чатов) она **гарантированно** упирается в Telegram
flood-control, и архитектура отвечает на это **тихой потерей** сообщений, а не throttle+retry.
Сценарий «быстро, с дедупом, упорядоченно, с уважением к rate-limit» не поддержан **ни в одном**
из четырёх требований: rate-limit не соблюдается вообще, ordering не гарантируется, дедуп защищает
не то, доставка теряется под первым же всплеском. Это не один баг — это отсутствие целого слоя
(outgoing rate-governor) плюс известные складывающиеся окна потери.

---

## Прохождение сценария: где упирается

### Путь одного события под нагрузкой

```
JetStream push ─► cb: sem.acquire() (max 100) ─► create_task(_handle_one)
   _handle_one: handler(data) ─► on_order_paid:
       dedup.seen(order-paid:<id>)  (SET NX EX, помечает ДО отправки)
       cache.get(chat_link:<user_ref>)  (1 redis GET)
       delivery.send_message ─► bot.send_message  (1 Telegram HTTP, БЕЗ rate-limit)
            ↳ на ошибке: лог + ПРОГЛОТИТЬ  (delivery.py:50-51)
   ack()  (всегда, т.к. handler «не бросил»)
```

### Backpressure: semaphore vs Telegram flood-control

`JsBus` держит `Semaphore(max_in_flight)`, дефолт **100** (`jetstream.py:48-56`,
`config.py:19`), и это же значение идёт в `max_ack_pending` консьюмера (`jetstream.py:106`).
Server-side backpressure корректен: брокер не пушит больше 100 неакнутых
(`flow_control=False` — проверил, но `max_ack_pending` сам по себе ограничивает поток). То есть
до **100 хендлеров параллельно** — и каждый делает **свой** `bot.send_message`.

И вот первая стена: **100 одновременных `send_message`** — это до **100 исходящих сообщений почти
в один момент**, против Telegram-лимита **30 msg/s глобально**. Backpressure кита настроен на
**пропускную способность брокера**, а не на **пропускную способность Telegram**. Эти две величины
не связаны нигде в коде. Семафор «защищает» NATS-консьюмер от переполнения, но **никак** не
защищает от заваливания Telegram API. Достаточно одного всплеска в пару сотен событий, чтобы
выйти за 30 msg/s.

### Rate-limit / 429 / `retry_after`: отсутствует целиком

В `tgbotkit` **нет ни одного** механизма соблюдения Telegram rate-limit (подтверждено grep'ом:
ни `Semaphore`, ни `sleep`, ни `throttl*` на исходящем пути; единственный `ThrottleMiddleware` —
**входящий** outer-middleware на апдейты юзера, к доставке отношения не имеет,
`middleware/throttle.py:18-31`). `Bot` создаётся с **дефолтной** `AiohttpSession`
(`module.py:79`), а aiogram 3.28 **не ретраит** `TelegramRetryAfter` автоматически (проверил:
`AiohttpSession.make_request` бросает). Значит при 429:

1. `bot.send_message` бросает `TelegramRetryAfter`;
2. `Delivery.send_message` **ловит и проглатывает** (`delivery.py:50-51`) — только лог;
3. handler возвращается «успешно» → `_handle_one` делает `ack()` (`jetstream.py:144`);
4. сообщение **подтверждено брокеру и потеряно навсегда**; дедуп-ключ уже стоит (шаг до отправки)
   → даже гипотетический redelivery был бы отброшен.

То есть **штатная реакция платформы на flood-wait — это тихая потеря уведомления**. Чем выше
нагрузка, тем больше 429, тем больше потерь — деградация не «замедление», а «молчаливое
исчезновение». Per-chat 1 msg/s (например, несколько событий одному юзеру в пачке) ловится тем же
429 → та же потеря.

### Ordering: не гарантируется

`max_ack_pending=100` + детач-таски (`create_task(_handle_one)`, `jetstream.py:111`) означают, что
**до 100 сообщений обрабатываются конкурентно**, и `ack`/`send` происходят в порядке завершения
тасок, **не** в порядке доставки. Для двух событий одного чата (`order-paid:A`, затем `B`) порядок
их `send_message` **не определён** — кто из детач-тасок первым доберётся до Telegram. JetStream
push с одним `filter_subject` доставляет упорядоченно, но kit тут же **распараллеливает** и теряет
порядок на стороне приложения. `ordered_consumer=False` (дефолт, проверил). Нет ни per-chat
sequencing (очередь на чат), ни single-flight на чат. Для realtime-ленты, где порядок статусов
важен («оплачено» → «отгружено»), это сюрприз: сообщения могут прийти переставленными.

### Дедуп под нагрузкой и «без TTL»

Уточняю наводку: `DeliveryDedup` **имеет** TTL — дефолт `86400` сек (`dedup.py:12,14`,
`max(int(ttl),1)`). «Без TTL» — неточность; ключ протухает через сутки. Реальные проблемы дедупа
другие, и под нагрузкой они острее:

- **mark-before-send** (`deliver.py:29` ставит `seen` до `send` на :34): ключ метит «доставлено»
  до фактической отправки. Под нагрузкой, где 429/5xx **регулярны**, это значит, что **каждая**
  неудачная отправка оставляет «доставлено»-ключ на недоставленное событие → редоставка (если бы
  она была) отброшена. Дедуп защищает «от повторной *попытки*», а не «от повторной *доставки*».
- **TTL=24ч + retention/`max_age` стрима до 7 дней** (`config.py:18`): если по какой-то причине
  событие задержалось в стриме дольше суток (затор, долгий аутэйдж), дедуп-ключ протухнет, и при
  редоставке сообщение **уйдёт повторно** — юзер получит дубль «оплата получена». Окно
  рассогласования `dedup_ttl < stream_max_age` нигде не закрыто.
- **redis-зависимость на каждое событие**: `seen` = синхронный `SET NX` без fail-open. При
  деградации redis под нагрузкой каждый хендлер бросит на `seen` → `nak` → редоставка → ещё
  больше нагрузки на redis (см. poison-loop ниже).

### Резолв chat_id

Один `cache.get(chat_link:<user_ref>)` на событие (`deliver.py:39`) — по нагрузке дёшево (1 redis
GET). Но: (а) контракт `user_ref == tg_id` нигде не зафиксирован (`start/gateway.py:24-25` пишет
по `tg_id`, читается по `payload.user_ref`); если бэкенд под нагрузкой шлёт `backend_user_id` —
**все** push'и резолвятся в `None` и **молча** дропаются (`deliver.py:32-33`), без лога/метрики.
Под нагрузкой это «100% потеря, и её никто не видит». (б) Нет батч-резолва: каждое событие — round
trip в redis, при тысячах/мин это тысячи последовательных GET (по одному на детач-таску); не
катастрофа, но и не оптимизировано (нет mget/pipeline).

### Потеря push: три складывающихся окна (подтверждаю по коду)

Под нагрузкой/при рестарте срабатывают **все три** известных окна (детально — `d-async` #1,
`p-msg` #1, `d-resilience` #2), и я подтверждаю их по исходнику:

1. **ack-after-swallowed-error** (`delivery.py:50-51` глотает → `jetstream.py:144` ack'ает) —
   срабатывает на **каждом** 429/5xx, т.е. постоянно под нагрузкой.
2. **dedup-before-send** (`deliver.py:29` до `:34`) — глушит любой гипотетический ретрай.
3. **drain не ждёт детач-таски**: `NatsProvider.conn finally: nc.drain()` (`module.py:32`) +
   `NotificationRunner.drain` — пустышка (`runner.py:33-34`) → на рестарте in-flight `_handle_one`
   акает/шлёт по закрытому соединению. Под нагрузкой in-flight всегда ≈ `max_in_flight` (100),
   т.е. на **каждом деплое теряется до 100 сообщений** в полёте.

### Poison-loop без `max_deliver`

`ConsumerConfig` (`jetstream.py:101-107`) **не** задаёт `max_deliver`/`backoff`; `_handle_one`
делает `msg.nak()` **без delay** (`jetstream.py:142`). Для текущего notifications-консьюмера это
замаскировано (Delivery глотает → handler не бросает → ack, а не nak). **Но**: любой более честный
хендлер (или будущий subscriber), который бросает на временной ошибке, попадёт в **tight-loop
немедленной редоставки** — `nak` без delay → мгновенный редел → снова падение → … до `max_age`
(7 дней). Под нагрузкой один «ядовитый» payload в пачке забивает `max_ack_pending`-слот и жжёт
CPU/redis, деградируя **весь** консьюмер. `nak(delay=...)` поддерживается (проверил), но не
используется.

### Реконнект под разрывом

`nats.connect` (`conn.py:23-28`, `module.py:23-28`) — без `error_cb`/`reconnected_cb`/`closed_cb`,
`max_reconnects=60` (дефолт, `config.py:32`). При разрыве NATS дольше ~2 мин (60×2с) клиент
закрывается **насовсем**, подписки молча мертвы, push'и **тихо выключаются до рестарта бота**.
Плюс push-консьюмер без `flow_control=True`/`idle_heartbeat` (проверил дефолты) — над медленным/
рвущимся линком нет heartbeat-детекции залипшей подписки. Для realtime-ленты, где разрывы при
тысячах/мин вероятнее, это значит периоды полной невидимой немоты.

---

## Честный потолок: «сколько потянет до первой потери/блокировки»

- **До первой потери от flood-control**: **~30 сообщений в первую же секунду всплеска**. Как
  только пачка событий даёт >30 исходящих/сек (а с `max_in_flight=100` это происходит при первом
  же буфере в сотню событий), Telegram отвечает 429, и **первое же** 429 = первая тихая потеря.
  Реальный устойчивый потолок доставки = **30 msg/s ≈ 1800/мин** — и это **только если** добавить
  rate-governor; **без** него платформа не «замедляется до 1800/мин», а **теряет всё сверх 30/с**.
  Заявленные «тысячи/мин» (>1800/мин) **физически недостижимы** через один бот-токен в принципе,
  но текущая механика вместо честного backpressure отвечает потерей.
- **До первой потери от деплоя**: **каждый рестарт** теряет до `max_in_flight` (100) in-flight
  сообщений (drain не ждёт детач-таски). Под нагрузкой in-flight ≈ всегда полон.
- **До первой блокировки консьюмера**: **один** битый payload у честного хендлера → hot-loop,
  забивающий слот `max_ack_pending`; при 100 слотах сотня «ядовитых» = полный стоп.
- **Дубли**: при задержке события в стриме > 24ч (`dedup_ttl`) — повторная доставка юзеру.

Итог потолка: **happy-path масштабируется до ~30 msg/s суммарно** (предел Telegram), но платформа
**не доводит** до этого предела безопасно — она начинает **терять** уже на десятках msg/s и
**тихо**. Это демо-уровень: годится для редких единичных пушей (оплата раз в минуту на разные
чаты), **не** для realtime fan-out пачками.

---

## BREAKING_POINTS

- **[SEV=critical] Нет outgoing rate-limit/flood-control вообще; 429 → swallow → ack → тихая
  потеря** :: `tgbotkit/notifications/delivery.py:46-53` (swallow), `natskit/jetstream.py:144`
  (ack-on-no-raise), `module.py:79` (дефолтная сессия без retry, aiogram не ретраит RetryAfter) ::
  workaround: **нет** в рамках шаблона — это отсутствующий слой в ките; «обходить» не получится,
  т.к. `Delivery` — единственная санкционированная обёртка (rule `background-updates`).
- **[SEV=critical] Backpressure (`max_in_flight=100`) развязан с Telegram-лимитом (30 msg/s) →
  до 100 параллельных send → детерминированный flood** :: `natskit/jetstream.py:48-56,106,110` +
  `config.py:19` :: workaround: понизить `NATS_JS_MAX_IN_FLIGHT` до ~1 **сериализует** доставку,
  но не уважает per-chat и убивает throughput; полумера, не решение.
- **[SEV=high] Ordering не гарантирован: 100 конкурентных детач-тасок ack/send в порядке
  завершения, `ordered_consumer=False`, нет per-chat-очереди** :: `natskit/jetstream.py:106,111`
  :: workaround: `max_in_flight=1` (сериализует всё, но это глобальный bottleneck, не per-chat).
- **[SEV=high] Drain не ждёт детач-таски `_handle_one` → каждый деплой теряет до 100 in-flight
  push'ей** :: `natskit/module.py:32` (`nc.drain`), `tgbotkit/notifications/runner.py:33-34`
  (drain-пустышка), `jetstream.py:109-113` :: workaround: нет (нужен реальный `drain` в ките).
- **[SEV=high] mark-before-send + ack-after-swallow: дедуп метит «доставлено» до отправки, ретрай
  невозможен** :: `features/notifications/deliver.py:29` (до `:34`), `tgbotkit/notifications/dedup.py:16-18`
  :: workaround: нет (нужен reserve/commit в ките; единственный примитив `seen` не даёт построить
  безопасно).
- **[SEV=high] Poison-loop: нет `max_deliver`/`nak(delay)`/DLQ → честный хендлер на временной
  ошибке уходит в tight-redelivery, забивая `max_ack_pending`** :: `natskit/jetstream.py:101-107`
  (нет max_deliver), `:142` (nak без delay) :: workaround: нет.
- **[SEV=medium] `dedup_ttl=86400` < `stream_max_age=7д` → событие, застрявшее в стриме >24ч, при
  редоставке шлётся повторно (дубль)** :: `tgbotkit/notifications/dedup.py:12`, `natskit/config.py:18`
  :: workaround: поднять `DeliveryDedup ttl` ≥ `max_age` (но `ttl` не прокинут в env у kit-обёртки —
  `dedup.py:12` хардкод-дефолт, шаблон строит `DeliveryDedup(client)` без ttl, `__init__.py:19`).
- **[SEV=medium] Контракт `user_ref==tg_id` не зафиксирован; расхождение → 100% тихая потеря fan-out
  без лога/метрики** :: `start/gateway.py:24-25` vs `deliver.py:26,31,39` :: workaround: писать
  chat_link по согласованному ключу — продуктовая правка шаблона (это допустимо).
- **[SEV=medium] Реконнект без callback'ов, `max_reconnects=60` → >2мин разрыва = немота до
  рестарта; push без `flow_control`/`idle_heartbeat` = нет heartbeat-детекции залипания** ::
  `natskit/conn.py:23-28`, `natskit/module.py:23-28`, `jetstream.py:115-117` :: workaround: нет.
- **[SEV=medium] Тихий промах без observability: `OrderDeliverer` без логгера, все ветки `return`
  без лога/метрики; нет счётчика доставленных push'ей** :: `deliver.py:27,30,33` (немые `return`),
  нет `delivered_total` :: workaround: прокинуть `logkit.Logger` в `OrderDeliverer` (правка шаблона,
  частично; метрика доставки — в ките).

---

## REQUIRED_CHANGES (чтобы сценарий стал чистым)

В **ките** (`pylibinfra/tgbotkit` + `natskit`) — это PR'ы по `tgbotkit-boundary`, не правки шаблона:

1. **Outgoing rate-governor** в `Delivery` (или отдельный `RateLimitedBot`/middleware на сессии):
   глобальный лимитер 30 msg/s + per-chat 1 msg/s (token-bucket в redis, общий на инстансы), с
   очередью/паузой вместо отправки в стену. Это **отсутствующий слой**, без него realtime-доставка
   невозможна в принципе.
2. **Honor `TelegramRetryAfter`**: при 429 — `await asyncio.sleep(retry_after)` + повтор (а не
   swallow); транзиентные сетевые/5xx — пробросить, чтобы хендлер сделал `nak(delay)` → redeliver.
   `Delivery.send_message` должен **возвращать признак успеха** или бросать, а не глотать молча.
3. **reserve/commit-дедуп**: `reserve(key, short_ttl)->bool` + `commit(key, long_ttl)` после
   успешного `send`; на сбое — не оставлять «done», дать redeliver. TTL ≥ `stream_max_age`.
4. **Реальный `drain`**: `JsBus.drain()` = unsubscribe → `gather(*self._tasks)` (дождаться
   in-flight ack/send по живому соединению) → потом `nc.drain()`; звать из
   `NotificationRunner.drain` **до** `container.close()`.
5. **`max_deliver` + `nak(delay=backoff)` + DLQ/`term()`** в `ConsumerConfig`; `flow_control=True`
   + `idle_heartbeat` на push-подписке; nats reconnect-callbacks + ре-subscribe на `reconnected`.
6. **Ordering-опция**: per-chat single-flight (хэш chat_id → воркер/очередь) или явный
   `ordered_consumer` для подписок, где порядок важен; задокументировать, что дефолт — конкурентный
   (порядок не гарантирован).
7. **Observability доставки**: `delivered_total{result}`, `dropped{reason}`; логгер в путь
   доставки (kit + прокинуть в `OrderDeliverer`).

В **шаблоне** (допустимые продуктовые правки): зафиксировать/исправить контракт `user_ref`;
прокинуть `DeliveryDedup(client, ttl=...)`; прокинуть логгер в `OrderDeliverer`; локализовать текст
(вне realtime-линзы, см. `t-feat-lang-notif`).

---

## FINDINGS (severity)

### CRITICAL

- **Полное отсутствие соблюдения Telegram rate-limit на исходящем пути.** `tgbotkit` не содержит
  ни одного rate-limiter/sleep/Semaphore на отправке (grep по всему kit'у — только входящий
  `ThrottleMiddleware`, `middleware/throttle.py:18`, к доставке не относится). `Bot` — дефолтная
  сессия (`module.py:79`), aiogram 3.28 не ретраит `TelegramRetryAfter` (эмпирически подтвердил).
  Backpressure кита (`max_in_flight=100`, `jetstream.py:48-56`) развязан с лимитом Telegram (30/с) →
  до 100 параллельных send → детерминированный 429 на первом всплеске. `SEV=critical | CAT=async |
  CONF=high | KEY=yes`.

- **429/5xx → swallow → ack → тихая потеря (под нагрузкой — постоянная).** `Delivery.send_message`
  глотает любое исключение отправки (`delivery.py:50-51`), `_handle_one` ack'ает на «не бросил»
  (`jetstream.py:144`). При flood-wait это срабатывает на **каждом** сбое, т.е. чем выше темп, тем
  больше потерь. Заявленный at-least-once → фактический at-most-once. `SEV=critical | CAT=errors |
  CONF=high | KEY=yes`.

### HIGH

- **Ordering не гарантирован под конкуренцией.** До 100 детач-тасок (`jetstream.py:111`),
  `ordered_consumer=False`, нет per-chat-сериализации → порядок статусов одному чату может
  переставиться. `SEV=high | CAT=correctness | CONF=high | KEY=yes`.

- **Drain не ждёт in-flight → потеря до 100 push'ей на каждый деплой.** `nc.drain` закрывает
  соединение, не дождавшись детач-тасок (`module.py:32`, `runner.py:33-34` — drain-пустышка). Под
  нагрузкой in-flight всегда ≈ полон. `SEV=high | CAT=async | CONF=high | KEY=no`.

- **mark-before-send + единственный примитив `seen`** делают безопасную доставку непостроимой:
  ключ метит «доставлено» до отправки (`deliver.py:29` до `:34`, `dedup.py:16-18`). `SEV=high |
  CAT=errors | CONF=high | KEY=no`.

- **Poison-loop: нет `max_deliver`/`nak(delay)`/DLQ** (`jetstream.py:101-107,142`) — один битый
  payload у честного хендлера забивает консьюмер. `SEV=high | CAT=correctness | CONF=high | KEY=no`.

### MEDIUM

- **`dedup_ttl=86400` < `stream_max_age` (до 7д) → дубль при задержке события >24ч.**
  `dedup.py:12`, `config.py:18`; ttl не прокинут (`__init__.py:19` строит без ttl).
  `SEV=medium | CAT=correctness | CONF=medium | KEY=no`.

- **Контракт `user_ref==tg_id` не зафиксирован → расхождение = 100% тихая потеря fan-out.**
  `start/gateway.py:24-25` vs `deliver.py:26,31,39`. `SEV=medium | CAT=correctness | CONF=medium |
  KEY=no`.

- **Реконнект без callback'ов + push без `flow_control`/`idle_heartbeat` → немота при долгом
  разрыве/залипании.** `conn.py:23-28`, `jetstream.py:115-117`. `SEV=medium | CAT=async |
  CONF=medium | KEY=no`.

- **Нулевая observability доставки** (`OrderDeliverer` без логгера, немые `return`
  `deliver.py:27,30,33`; нет `delivered_total`) → все тихие потери невидимы в проде.
  `SEV=medium | CAT=observability | CONF=high | KEY=no`.

### INFO / сильные стороны

- **Server-side backpressure корректен**: `max_ack_pending` = `max_in_flight`, semaphore зеркалит
  (`jetstream.py:56,106,110`), GC-safety детач-тасок закрыта (`_tasks` + `add_done_callback`).
  Брокер не переполнит консьюмер — проблема **не** здесь, а в развязке с Telegram-лимитом.
  `SEV=info`.
- **Trace-context сквозь брокор** (`instrumentation.py:62,67`) — consumer-span child producer'а;
  метрики consumed/inflight есть. Наблюдаемость **транспорта** хорошая; наблюдаемости **доставки**
  нет. `SEV=info`.
- **Дедуп TTL есть** (вопреки наводке «без TTL»): дефолт 86400 (`dedup.py:12,14`). Проблема не в
  отсутствии TTL, а в его рассогласовании с `max_age` и в mark-before-send. `SEV=info`.

---

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Для **редких** пушей (единичное событие на разные
чаты, темп << 30/с) — да, путь работает. Для **realtime fan-out пачками** — **нет, не на текущей
механике**: нет слоя соблюдения Telegram rate-limit, и вместо честного throttle+retry платформа
**тихо теряет** всё сверх 30 msg/s, плюс теряет in-flight на каждом деплое и не гарантирует
порядок. Это не «допилить в шаблоне» — отсутствует целый инфра-слой, который по философии репо
живёт в ките. До его появления realtime-сценарий блокирован.

**2. Насколько гибкая система?** Для happy-path точки расширения есть (`router.on`, сменный
`stream/subject/durable`). Но обработка **нагрузки и отказов** зашита жёстко и недо-обобщена:
дедуп — только `seen` (нет reserve/commit), консьюмер — без `max_deliver`/backoff/DLQ/flow_control,
доставка — без rate-governor и без сигнала об ошибке, drain — пустышка, реконнект — без callback'ов.
«Правильный» способ (бросить из хендлера) ведёт в hot-loop. Гибкости для realtime под нагрузкой
**недостаточно** — её пришлось бы добавлять PR'ами в kit, а не настройкой.

**3. Тревога про несколько `BackendClient`** — вне этой линзы (это `platform/backend`/httpclient).
В messaging-слое жёсткой привязки к одному источнику нет (`router.on` параметризован), так что
конкретно тревога заказчика тут не проявляется. Замечу лишь параллель: как `httpclient` имеет один
host-agnostic breaker на все API, так и доставка имеет один глобальный путь без per-chat/per-stream
изоляции нагрузки — общий паттерн «один разделяемый контур без сегментации» повторяется.
