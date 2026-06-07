# Аудит d-resilience — обработка ошибок и устойчивость (сквозной синтез)

Это **синтез-линза**: я не аудирую один модуль, а прохожу failure-режимы бота end-to-end и собираю
системную картину «что происходит с пользователем/деньгами, когда что-то ломается». Опираюсь на
готовые отчёты смежных агентов (k-tgbot-mw, k-tgbot-feat, p-msg, t-feat-payments, t-feat-lang-notif,
t-platform) + собственную проверку исходников и **две независимые эмпирические репродукции** на живом
коде (порядок recovery↔dp.errors; недренаж in-flight в polling).

## Что смотрел

Прошёл девять failure-режимов из задания по реальному коду обоих репозиториев:

1. **backend 5xx / timeout / breaker-open** → `httpclient/client.py:121-147` (retry+breaker),
   `platform/backend/client.py:49-70` (маппинг транспорт→домен), потребление в
   `features/{profile,payments}/gateway.py`, `views.error_text`, getter/handler error-path.
2. **redis недоступен** → `middleware/dedup.py:34`, `payments/guard.py:24`, `notifications/dedup.py:17`,
   FSM-storage (`storage=RedisStorage`), отсутствие fail-open и health-gate в polling.
3. **nats недоступен / разрыв** → `natskit/module.py:21-40` (eager `nats.connect` через цепочку
   `runner→bus→conn`), `natskit/conn.py:23-28` (нет error/reconnected-callback'ов), `jetstream.py:62-79`
   (`ensure_streams` роняет boot).
4. **невалидный апдейт** → `runner/webhook.py:25-29` (`Update.model_validate`), dedup/identity на
   `from_user is None` (`identity/provider.py:29-32`).
5. **исключение в getter/handler** → `profile/getters.py:25-31`, `views.error_text` (`case _: raise`),
   `dialog-architecture` rule («ловим в getter, не наша ошибка — в recovery»).
6. **протухшая inline-кнопка (UnknownIntent/OutdatedIntent/UnknownState)** → `errorux.py:54-67`,
   `recovery.py:28-41`, `aiogram_dialog/setup.py:252` (`IntentErrorMiddleware` на `router.errors`),
   `intent_middleware.py:479-507` (`_fix_broken_stack`). **Репродукция вживую** (ниже).
7. **сбой fulfill платежа** → `payments/handlers.py:71-73`, `guard.py:23-28`, `usecase.complete`.
8. **сбой доставки уведомления** → `notifications/deliver.py:29-36`, `delivery.py:46-53`,
   `jetstream.py:123-150` (ack-on-no-raise).
9. **деплой / shutdown с застрявшим юзером** → `runner/base.py:76-89` (`_cleanup`), `polling.py:12-17`,
   aiogram `dispatcher.py:354-440,598-625` (недренаж in-flight). **Репродукция вживую** (ниже).

Эмпирика (template `.venv`, python3.13): воспроизвёл (а) что `RecoveryMiddleware` глотает
`UnknownIntent` раньше `dp.errors` — `dp.errors` не сработал ни разу; (б) что aiogram в polling не
ждёт `_handle_update_tasks` на остановке (grep: только `.add`/`.discard`, ни одного `gather`/`await`).

## Системная картина (карта «сетей последней надежды»)

Бот имеет **четыре** контура защиты от сбоя. Сквозная проверка показывает, что три из них дырявы:

```
incoming Update ─► ErrorsMiddleware(dp.errors) ─► Recovery ─► Observability ─► Container ─► dialog/handler
                   └─ aiogram_dialog stack-fix    └─ глотает      └─ метрит      
                      + kit on_stale UX            всё подряд

фон (NATS)      ─► JsBus._handle_one(ack/nak) ─► Delivery(глотает send-error) ─► deliver_*(dedup-before-send)
```

1. **Сеть `dp.errors` (восстановление dialog-стека + tailored UX)** — **МЁРТВА для обычных апдейтов.**
   Recovery сидит внутри ErrorsMiddleware и перехватывает раньше. Подтверждено эмпирически.
2. **Сеть Recovery (анти-паника, не валить воркер)** — работает как анти-краш, но «глотает» слишком
   широко: ест и те исключения, что должны были чиниться выше (находка 1).
3. **Сеть JetStream ack/nak (at-least-once доставка)** — **закорочена** тем, что Delivery глотает
   ошибку отправки → handler «не бросил» → `ack` на недоставленном (находка 2).
4. **Сеть idempotency/dedup (защита от двойной обработки)** — стоит «mark-before-commit», поэтому при
   сбое *первой* попытки маскирует ретрай вместо защиты от дубля (находки 2, 3).

Итог: каждый из заявленных в docstring'ах контрактов восстановления держится **только на happy-path**;
ровно в момент сбоя (а это его работа) — рвётся. Это и есть главный системный вывод линзы.

---

## Сильные стороны (resilience-плюсы, которые держатся)

- **Анти-краш реально работает.** Один битый апдейт не валит воркер: Recovery (`recovery.py:28-41`)
  ловит, метрит `tg_update_panics_total`, best-effort UX в своём `try/except`. JS-`run_loop`/worker
  переживают сбой тика (`p-msg` подтвердил). Бот не входит в краш-луп от одного отравленного входа.
  (SEV=info)
- **Fail-closed там, где это про деньги/безопасность.** `pre_checkout` fail-closed по таймауту/ошибке
  (`precheckout.py:41-45`, deadline 9<10с); `confirm` сверяет цену на бэкенде, не доверяя клиенту
  (`handlers.py:53-55`); breaker-open и 5xx-после-ретраев честно мапятся в `BackendUnavailable` и
  getter показывает мягкий текст вместо падения (`getters.py:27-28`). Это правильная сторона риска:
  при неопределённости — отказать, не пропустить. (SEV=info)
- **At-least-once на «своей половине» транзакционного outbox корректен** (`p-msg`: publish→mark, не
  наоборот; `SKIP LOCKED`; тесты на «не пометить при сбое publish»). Дыра — на стыке JS↔Delivery, не в
  outbox. (SEV=info)
- **Идемпотентность по бизнес-ключу заложена** (`guard_charge` по `charge_id`, `DeliveryDedup` по
  `order-paid:<id>`, `Idempotency-Key=charge_id` на бэкенде). Примитивы атомарны (`SET NX EX`). Проблема
  не в атомарности, а в **моменте** установки ключа (before-commit). (SEV=info)
- **getter/handler error-UX по конвенции — грамотный.** Доменная ошибка ловится в getter/handler,
  превращается в текст (`views.error_text`), окно не падает; «не наша» ошибка осознанно пробрасывается
  в recovery (`views.py: case _: raise`). Это правильный дизайн error-boundary на уровне фичи. (SEV=info)
- **`from_user is None` не роняет резолв** (`identity/provider.py:30-32`) — service-апдейты без юзера
  обрабатываются синтетическим нулевым identity, а не паникой. (SEV=info)

---

## Находки (по влиянию на пользователя/деньги)

### CRITICAL

#### 1. [errors] Порядок Recovery↔dp.errors убивает обе сети восстановления протухшей кнопки: tailored-UX мёртв И dialog-стек не чинится → пользователь застревает в цикле ошибки до ручного /start
`KEY=yes | CAT=errors | CONF=high`

Это **усиление и расширение** находки 1 из k-tgbot-mw: я не только подтверждаю её эмпирически, но и
довожу до пользовательского последствия.

**Доказательство (репродукция на живом Dispatcher, template `.venv`):**
```
EVENTS: ['enter:Recovery', 'enter:Obs', 'Obs-reraises:UnknownIntent', 'RECOVERY-SWALLOWS:UnknownIntent']
DP_ERRORS_FIRED: False
```
`ErrorsMiddleware` (диспетчит `dp.errors`) — самый внешний, хардкод в `Dispatcher.__init__`
(`aiogram/dispatcher/dispatcher.py:80`). `RecoveryMiddleware` навешивается позже
(`middleware/__init__.py:45`) → сидит **внутри**. `UnknownIntent`/`OutdatedIntent`/`UnknownState`
(подклассы `Exception`) всплывают из dialog-observer'ов и **первым их ловит Recovery**
(`recovery.py:31 except Exception`), глотает, возвращает `None`. `dp.errors` не срабатывает.

**Две жертвы (расширение):**
1. **kit `on_stale`/шаблонный `AppErrorUX.on_unknown_intent`** (`errorux.py:60-67`, `errors.py:19-23`)
   — мёртвый код. Tailored «Сессия устарела, нажмите /start» никогда не показывается; пользователь
   всегда получает общий `on_unhandled` («Что-то пошло не так»), что **уводит от правильного действия**
   (он не знает, что спасёт /start).
2. **Штатный `_fix_broken_stack` aiogram_dialog НЕ выполняется.** Я проверил по исходнику: фикс стека
   живёт в `IntentErrorMiddleware`, который зарегистрирован **как middleware на `router.errors`**
   (`aiogram_dialog/setup.py:252`), т.е. срабатывает только если событие дошло до `dp.errors`-наблюдателя
   (`intent_middleware.py:479-507`). Раз `dp.errors` закорочен — **сломанный dialog-стек не чинится**.
   Пользователь после протухшей кнопки остаётся с corrupted-стеком и может ловить ту же ошибку повторно
   (poison-loop на уровне UX), пока вручную не нажмёт /start (`RESET_STACK` пересобирает стек).

**Влияние на пользователя:** массовый кейс. Протухшие кнопки — норма после **каждого деплоя** (рестарт
→ FSM-контексты в Redis живут, но `intent_id` старого диалога устаревает) и после TTL. Значит после
каждого релиза часть активных пользователей жмёт старые кнопки и попадает в деградированный UX без
подсказки и без авто-восстановления стека. Это самый частый failure-режим живого бота, и обе сети
защиты от него выключены порядком middleware.

**fix:** в `RecoveryMiddleware.__call__` пропускать наверх ожидаемые dialog-исключения, чтобы они дошли
до `ErrorsMiddleware → dp.errors` (где их разрулят и kit `on_stale`, и `_fix_broken_stack`):
```python
from aiogram_dialog.api.exceptions import OutdatedIntent, UnknownIntent, UnknownState
except (UnknownIntent, OutdatedIntent, UnknownState):
    raise          # пусть dp.errors разрулит (stale-UX + stack-fix)
except Exception as exc:
    ...            # как сейчас: panic-метрика + on_unhandled + swallow
```
Это правка в ките (`tgbotkit/middleware/recovery.py`), back-compat, одна строка логики. До неё — UX и
восстановление на устаревших кнопках сломаны.

---

#### 2. [errors] «mark-before-commit» + проглатывание ошибки доставки → тихая потеря уведомления об оплате (at-most-once вместо заявленного at-least-once)
`KEY=yes | CAT=errors | CONF=high`

Подтверждаю и **синтезирую в один дефект** то, что p-msg, k-tgbot-feat и t-feat-lang-notif нашли с трёх
сторон. Это два **складывающихся** окна потери на одном пути.

**Цепочка (вся в ките + reference-фиче):**
1. `OrderDeliverer.on_order_paid` ставит dedup-маркер **до** отправки: `self._dedup.seen(...)`
   (`deliver.py:29`) = атомарный `SET NX EX` (`notifications/dedup.py:17`) → ключ «доставлено» записан.
2. `delivery.send_message` → `bot.send_message` падает (5xx Telegram / flood-wait / юзер заблокировал
   бота / сетевой блип) → **исключение проглочено** (`delivery.py:50-51`, только лог).
3. Handler возвращается нормально → `JsBus._handle_one` видит «не бросил» → `await msg.ack()`
   (`jetstream.py:144`). Сообщение подтверждено брокеру.

Итог: сообщение **не доставлено**, redis помечен seen, JetStream получил ack → **нет ни одного
механизма ретрая**. Даже если убрать проглатывание (чтобы дать `nak`/redeliver), redelivery всё равно
отбросится дедупом на шаге 1. Два независимых окна потери, и они складываются.

**Влияние на деньги/доверие:** push «оплата заказа получена» — это бизнес-уведомление о платеже.
Регулярные транзиентные сбои Telegram (flood-wait при всплеске, 5xx) → пользователь заплатил, но
подтверждения не получил, и оно никогда не придёт. Доки (`background-updates.md`, docstring'и
`dedup.py`/`deliver.py`) обещают at-least-once — фактически at-most-once.

**fix (на стороне kit):** разнести dedup на `reserve(key, short_ttl)->bool` + `commit(key, long_ttl)`;
`Delivery.send_message` не глотать (или возвращать bool успеха), чтобы handler сделал `raise` → `nak` →
redeliver; `commit` ставить только **после** успешного send. Покрыть тестом «send упал → второе событие
доставлено» (сейчас `FakeDelivery` всегда успешен — регрессия незаметна для `make check`).

---

### HIGH

#### 3. [correctness] Окно потери fulfill: guard ставит ключ ДО `complete`, ошибка fulfill → деньги списаны, выдачи нет, Telegram-redelivery заглушён дедупом
`KEY=yes | CAT=correctness | CONF=high`

Тот же антипаттерн «mark-before-commit», но **про реальные деньги пользователя** (звёзды уже у мерчанта).
Это находка t-feat-payments (HIGH), которую подтверждаю и ставлю в общий ряд.

**Доказательство.** `handlers.py:71-73`:
```python
if await guard_charge(client, sp.telegram_payment_charge_id):  # SET NX — ставит ключ ПЕРВЫМ
    return
await uc.complete(sp.invoice_payload, sp.telegram_payment_charge_id)  # может бросить
```
`guard_charge` (`guard.py:24`) делает `SET NX` сразу. Затем `uc.complete`→`gateway.fulfill` бросает
`PaymentError` при `BackendUnavailable` (breaker-open/5xx/timeout). Исключение не ловится в хендлере →
всплывает в Recovery → проглатывается. Telegram при at-least-once присылает тот же `successful_payment`
повторно — но `guard_charge` теперь вернёт `True` (ключ стоит 7 дней) → хендлер выйдет на `return`,
**выдачи опять нет**. Авто-восстановления нет; дедуп-ключ маскирует ретрай.

**Связь с находкой t-platform (MEDIUM, `BackendConflict` мёртв):** даже когда `fulfill` дошёл и
выполнился, но ответ потерялся, повтор даст 409 → `BackendConflict`, который **ни один gateway не ловит**
(`payments/gateway.py:29-37` ловит только `BackendUnavailable`) → всплывёт как паника. То есть штатный
для идемпотентного повтора ответ бэкенда тоже трактуется как авария. Два дефекта на одном пути
усугубляют друг друга.

**fix:** инвертировать порядок (сначала идемпотентный `complete`, потом dedup-ключ), либо при ошибке
fulfill удалять/не ставить ключ (`DEL tg:charge:*`) для второй попытки; ловить `BackendConflict` в
`payments.fulfill` и трактовать как «уже выполнено». Решение совместное kit (`guard_charge` reserve/commit)
+ шаблон.

#### 4. [async] Polling не дренирует in-flight хендлеры на shutdown; `BOT_SHUTDOWN_DRAIN` — мёртвый конфиг → апдейт застрявшего юзера теряется на каждом деплое
`KEY=no | CAT=async | CONF=high`

Это находка моей линзы (не покрыта смежными агентами).

**Доказательство.** `PollingRunner._serve` зовёт `start_polling(bot, allowed_updates=..., drop_pending_updates=...)`
(`polling.py:13-17`) — **без передачи `shutdown_drain`**. Конфиг `shutdown_drain: float = 10.0`
(`config.py:47`) объявлен, но `grep` по всему `tgbotkit` показывает: он **нигде не используется** —
мёртвая ручка. В самом aiogram на остановке polling (`dispatcher.py:598-625`) в `asyncio.wait` участвуют
только poller-таск и stop-signal; in-flight `_handle_update_tasks` (исполнение хендлеров) — отдельные
fire-and-forget таски, которые **не ждутся**: `grep _handle_update_tasks` → только `.add`/`.discard`,
ни одного `gather`/`await` (подтверждено). После остановки `BotRunner._cleanup` (`runner/base.py:76-89`)
сразу зовёт `container.close()` → закрывает redis/nats/`bot.session` (через yield-провайдеры).

Итог: апдейт, который обрабатывался в момент SIGTERM (деплой/масштабирование), получает разрыв
redis/`bot.session` посреди исполнения хендлера → действие пользователя **тихо теряется** (FSM не
сохранён, ответ не отправлен). Никакого grace-периода нет, хотя конфиг под него заведён.

**Контраст:** webhook-runner на shutdown делает `delete_webhook` + `server.stop()` + `emit_shutdown`
(`webhook.py:62-64`), но тоже не ждёт in-flight `feed_update`-таски; правда там Telegram переотправит
неотвеченный вебхук. В polling переотправки нет — getUpdates уже сдвинул offset на принятых апдейтах.

**Влияние:** деплой — частая штатная операция. Каждый релиз теряет действия тех, кто как раз что-то
делал. Для платёжного/важного действия это сливается с находкой 3.

**fix:** реально использовать `shutdown_drain` — после stop-signal дождаться `dp._handle_update_tasks`
с таймаутом (`asyncio.wait(..., timeout=shutdown_drain)`) **до** `container.close()`; либо документировать,
что drain не реализован, и закрыть мёртвую ручку конфига. Это правка runner'а в ките.

#### 5. [async] Redis-down = тихий отказ всего бота без health-gate (в polling вообще нет health-эндпоинта)
`KEY=no | CAT=async | CONF=high`

Находка моей линзы.

**Доказательство.** `DedupMiddleware` (`dedup.py:34`), `guard_charge` (`guard.py:24`), `DeliveryDedup.seen`
(`dedup.py:17`), identity-резолв через `cache.get` (`identity/provider.py:39`) и FSM-`RedisStorage` —
все делают redis-операции **без try/except и без fail-open**. При недоступности redis `SET`/`GET` бросает
`ConnectionError`. Для `DedupMiddleware` (outer, по умолчанию `dedup_enabled=True`, `config.py:35`) это
значит: **каждый** апдейт падает в дедупе ещё до хендлера → Recovery глотает → `panics_total++`. Бот не
крашится (это плюс), но **полностью нефункционален для всех пользователей**, при этом выглядит как поток
per-update паник, а не как «redis down».

Хуже: в **polling** нет HTTP-health вообще. `probe` (`module.py:136`) «не provide'ится, caller
регистрирует сам», а `PollingRunner` (`polling.py`) не поднимает никакого сервера — только webhook-runner
вешает `_probe` на httpkit-сервер (`webhook.py:39`). Значит в polling-режиме нет readiness/liveness,
который оркестратор мог бы связать со здоровьем redis → деградация redis не приводит к
рестарту/выводу из ротации, бот молча «жив, но мёртв».

**fix:** (а) fail-open в `DedupMiddleware` при redis-ошибке (лог + пропустить апдейт без дедупа — потеря
дедупа лучше полной недоступности; либо явное решение «fail-closed, но с метрикой `redis_down`»);
(б) в polling-режиме поднимать минимальный health-эндпоинт с redis/nats-probe (kit), чтобы orchestrator
видел деградацию. Это PR в kit.

#### 6. [async] NATS-down при старте роняет весь бот (Telegram-polling не стартует), а после исчерпания реконнектов подписки молча мертвы
`KEY=no | CAT=async | CONF=high`

Синтез: связываю находку p-msg #3 (нет reconnect-callback'ов, `max_reconnects=60` → ~2 мин и клиент
закрывается насовсем) с **startup-связностью**, которую вижу в проводке шаблона.

**Доказательство (startup-coupling).** `runner`-провайдер зависит от `bus: OptionalStreamBus`
(`module.py:121`), а в шаблоне `stream_bus` зависит от `StreamBus` → `NatsProvider.stream_bus` →
`conn` → `await nats.connect(...)` (`natskit/module.py:22-28,39`). `app.py` резолвит `runner`, чтобы
вызвать `.run()` → NATS-`conn` резолвится **eagerly при старте**. Если JetStream включён и NATS недоступен
в момент boot, `nats.connect` (или `ensure_streams`, `jetstream.py:77-79`) бросает → контейнер не
собирается → **бот не стартует целиком**, включая Telegram-обработку. NATS-аутэйдж кладёт весь бот, а не
только уведомления.

**Доказательство (runtime-разрыв).** `conn.py:23-28` / `module.py:23-28` задают `reconnect_time_wait` и
`max_reconnect_attempts`, но **не** передают `error_cb`/`disconnected_cb`/`reconnected_cb`/`closed_cb`.
После `max_reconnects` клиент закрывается, подписки молча мертвы (`Conn.healthy` отловит, только если его
дёргает probe — а в polling probe нет, см. находку 5). Push-консьюмер после долгого разрыва не
переустанавливается.

**Влияние:** деплой во время NATS-аутэйджа = бот не поднимется. Длинный разрыв NATS в рантайме =
уведомления тихо выключаются до рестарта.

**fix:** (а) сделать notifications-подписку boot-tolerant (не валить весь бот при недоступном NATS на
старте — лог + деградация только уведомлений; либо чёткое решение «NATS — hard dependency», но тогда это
надо явно задокументировать как INFRA-инвариант); (б) прокинуть nats-callback'и (лог+метрика
`nats_connection_state`), на `reconnected_cb` переустанавливать JS-подписки; рассмотреть
`max_reconnects=-1` для consumer-процесса. PR в natskit + решение по проводке шаблона.

---

### MEDIUM

#### 7. [correctness] Poison-message в любом не-notifications JS-консьюмере уходит в hot-loop редоставки (нет `max_deliver`/backoff/DLQ)
`KEY=no | CAT=correctness | CONF=high`

Находка p-msg #2, включаю как системный resilience-риск. `ConsumerConfig` (`jetstream.py:101-107`) не
задаёт `max_deliver`/`backoff`; `_handle_one` делает `msg.nak()` без delay (`jetstream.py:142`) →
бесконечный tight-loop на одном битом сообщении до `max_age` (7 дней). Для текущего notifications-консьюмера
это **замаскировано** тем, что Delivery глотает ошибку (handler не бросает → `ack`, см. находку 2) — но
это «лечение» одной болезни другой. Любой потребитель, который честно бросает из handler'а (а это
**заявленный** контракт для не-notifications-подписчиков), попадёт в hot-loop. Негибкость: «правильный»
способ обработки ошибки ведёт в вечную редоставку. **fix:** `max_deliver` + `nak(delay)`/`backoff` +
`term()`+DLQ при исчерпании.

#### 8. [observability] Тихие промахи доставки и потери fulfill невидимы: нет метрики успешной выдачи, нет логов промаха доставки
`KEY=no | CAT=observability | CONF=high`

Синтез t-feat-payments (MEDIUM) + t-feat-lang-notif (LOW). `tg_payments_total{stage=paid,result=ok}`
(успешная выдача) **не эмитится нигде** (`metrics.py:37`, есть только `pre_checkout` и `duplicate`) →
нельзя построить алерт «оплат N, выдач M, N>M» — то есть именно инцидент из находки 3 невидим на
дашборде. `OrderDeliverer` вообще без логгера: все ветки промаха (`deliver.py:27,30,33,44`) делают
`return` без лога/метрики → массовая потеря push'ей (напр. неверный `user_ref`, находка 9) абсолютно
невидима. **Каждый** тихий failure-режим из находок 2/3 не наблюдаем — это удваивает их опасность: их не
заметят в проде, пока пользователи не начнут жаловаться. **fix:** эмитить `paid,result=ok` после
успешного complete; прокинуть `logkit.Logger` в `OrderDeliverer`, логировать причину промаха.

#### 9. [correctness] Неявный контракт `orders.paid.user_ref == tg_id`: расхождение → доставка молча теряется без лога
`KEY=no | CAT=correctness | CONF=medium`

Находка t-feat-lang-notif. chat_link пишется по `tg_id` (`start/gateway.py:25`), читается по
`payload.user_ref` (`deliver.py:26,31`). Если бэкенд кладёт в `user_ref` натуральный для себя
`backend_user_id` (а вся остальная архитектура идентифицирует юзера именно так), `_lookup_chat → None` →
уведомление **тихо пропадает** (`deliver.py:32-33`), без лога. Reverse-карты `backend_user_id→chat_id`
нет. Контракт нигде не зафиксирован как INFRA. В связке с находкой 8 (нет логов промаха) — целый класс
потерь push'ей будет невидим. **fix:** задокументировать инвариант `user_ref` как messaging-контракт,
либо писать chat_link по `backend_user_id`; логировать `link_not_found`.

#### 10. [correctness] `resp.json()` без guard на 2xx и непойманный `BackendConflict` → штатные ответы бэкенда всплывают как паника
`KEY=no | CAT=correctness | CONF=medium`

Находки t-platform (LOW+MEDIUM), объединяю как «незакрытые пути в едином маппере транспорт→домен».
`_decode` (`client.py:60-64`) на любом 2xx с телом зовёт `resp.json()` — не-JSON 200 (HTML от прокси,
`text/plain`) → `JSONDecodeError`, не `BackendError` → минует доменную классификацию → паника. И
`BackendConflict` (409) производится (`client.py:67-68`), но **ни одна фича его не ловит** → штатный для
идемпотентной мутации 409 трактуется как авария. Оба — «дыры в сети», которая претендует быть единой
точкой перевода сбоев в UX. **fix:** обернуть `resp.json()` → `BackendUnavailable`; ловить
`BackendConflict` в мутирующих gateway (как минимум `payments.fulfill`).

---

### LOW

#### 11. [errors] ThrottleMiddleware режет фоновые dialog-апдейты и теряет их без лога/метрики
`KEY=no | CAT=errors | CONF=high`

Находка k-tgbot-mw #2. При `throttle_rps>0` (по умолчанию 0) всплеск нотификаций одному юзеру попадает в
тот же per-user bucket → часть доставок **тихо дропается** (`throttle.py:30-31 return None`) без лога/метрики.
Это ложное срабатывание троттла на системном фоне. SEV=low т.к. throttle off по дефолту. **fix:** не
троттлить фон (`if update_id`); скоупить ключ `bot_id`.

#### 12. [async] Throttle INCR без гарантии EXPIRE → возможен «вечный» бан окна при отмене на shutdown
`KEY=no | CAT=async | CONF=high`

Находка k-tgbot-mw #3. `INCR` + (если первый) `EXPIRE` неатомарны; `CancelledError` между ними (drain на
shutdown) оставляет ключ без TTL → юзер залочен навсегда до ручной чистки redis. Не self-healing. **fix:**
`pipeline().incr().expire(key,1,nx=True)` или Lua.

---

## Ранжирование по влиянию на пользователя/деньги

1. **Находка 3 (потеря fulfill)** — реальные деньги пользователя, нет авто-восстановления. Худшее.
2. **Находка 2 (потеря push об оплате)** — бизнес-уведомление о платеже теряется тихо, at-most-once.
3. **Находка 1 (мёртвые сети восстановления кнопки)** — самый частый кейс (каждый деплой), деградирует
   UX и оставляет стек битым; влияет на максимум пользователей.
4. **Находка 4 (недренаж на деплое)** — теряет действия активных юзеров на каждом релизе.
5. **Находки 5/6 (redis/nats down → тихий отказ всего бота, без health в polling)** — операционная
   слепота: деградация инфры не видна оркестратору.
6. **Находка 8 (невидимость всех тихих потерь)** — мультипликатор: делает 2/3/9 незаметными в проде.

Общая нить: **проблема не в отсутствии механизмов, а в их моменте/порядке/наблюдаемости** —
mark-before-commit (2,3), порядок middleware (1), недренаж (4), отсутствие fail-open/health (5,6),
проглатывание без сигнала (2,8,11). Почти всё чинится точечно в ките (recovery-порядок, reserve/commit
dedup, drain, fail-open, nats-callbacks), без слома API шаблона.

---

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Каркас устойчивости заложен правильно и местами выше
среднего (fail-closed на платежах, анти-краш, транзакционный outbox, атомарные дедуп-примитивы). Но
**ровно в момент сбоя** — а это работа resilience-слоя — рвутся три из четырёх сетей защиты: теряется
fulfill (деньги), теряется push (уведомление), не восстанавливается dialog-стек/UX на протухших кнопках,
и почти все эти потери **тихие** (невидимы в телеметрии). Для «нормального» прод-бота с платежами и
push'ами это блокеры: их надо закрыть до прода. Хорошая новость — все они чинятся точечно в `pylibinfra`
(порядок recovery, reserve/commit-дедуп, drain in-flight, fail-open redis, nats-callbacks), без
переписывания шаблона.

**2. Насколько гибкая система?** В части устойчивости гибкость есть для happy-path (флаги
dedup/throttle, override `ErrorUX` через Provider), но **обработка отказов недодумана и негибка**:
дедуп-примитивы дают только «пометил-и-забыл» (нет reserve/commit → строго-безопасную доставку на них
не построить), JS-консьюмер зашит без `max_deliver`/backoff/DLQ (правильный способ обработки ошибки ведёт
в hot-loop), `shutdown_drain` — мёртвая ручка, в polling нет health. Это не «заточка под кейс», а
недо-обобщённость failure-механики.

**3. Несколько backend-клиентов (нерв заказчика).** В моей resilience-проекции это усугубляет картину:
единый breaker `httpclient` (`breaker.py:12`, host-agnostic) — как только появится второй API через тот
же `Client`, деградация одного внешнего сервиса откроет breaker для **всех** (находка t-platform MEDIUM).
То есть «один бэкенд» зашит не только в типе (t-platform HIGH), но и в **контуре отказоустойчивости**:
нет per-host/per-backend изоляции сбоев. Для заказчика с несколькими разными API это означает, что один
тормозящий сервис положит обращения ко всем — и это resilience-аргумент в пользу того, что моно-клиент
здесь именно негибкость, а не чистый by-design.
