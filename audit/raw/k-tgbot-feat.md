# Аудит области k-tgbot-feat — tgbotkit: generic-механика (notifications / payments / webapp / metrics / errorux)

## Что смотрел

Generic-механики kit'а, в которые шаблон вкладывает контент:

- **notifications/**: `dedup.py` (DeliveryDedup), `delivery.py` (Delivery — обёртка над BgManager),
  `router.py` (NotificationRouter), `runner.py` (NotificationRunner).
- **payments/**: `guard.py` (guard_charge), `invoice.py` (build_invoice), `precheckout.py`
  (answer_pre_checkout).
- **webapp/init_data.py** (validate_init_data).
- **metrics.py** (TgInstruments), **errorux.py** (ErrorUX / register_error_handlers).

Смежный контекст, без которого механику не оценить: `middleware/{dedup,recovery,observability,
request_id,throttle}.py`, `module.py` (BotProvider — DI-проводка), `runner/base.py` (lifecycle,
запуск/drain notifications), `i18n/{middleware,resolver}.py` (locale-резолв), нижележащий транспорт
`natskit/jetstream.py` (EXPLICIT-ack, nak-on-error, semaphore-backpressure), а также потребитель в
шаблоне: `features/notifications/{__init__,deliver}.py`, `features/payments/handlers.py`,
`platform/{webapp/init_data,dialogs/errors}.py`.

Запускал тесты kit'а (`test_payments.py`, `test_webapp_init_data.py`, `test_errorux.py` — 15
passed) и отдельные сверки поведения `validate_init_data` через `uv run python`. Сверял алгоритм
initData с актуальной спецификацией Telegram (core.telegram.org/bots/webapps и docs.telegram-mini-apps.com).

## Сильные стороны

- **answer_pre_checkout сделан правильно** (`payments/precheckout.py`): `asyncio.wait_for(decide,
  deadline=9.0)` < 10с-дедлайна Telegram, fail-closed на timeout/исключении (`ok=False`),
  `decide` сверяет цену/валюту на бэкенде (шаблон: `usecase.confirm(payload, total_amount,
  currency)`), а не доверяет `query.total_amount`. Подмена суммы/валюты атакующим тут не проходит,
  если шаблон корректно реализует `decide` (а reference-фича — реализует:
  `features/payments/handlers.py:53-55`). Есть тесты на ok/rejected/timeout/exception. **SEV=info.**
- **validate_init_data спец-корректен** (`webapp/init_data.py`): HMAC по
  `secret=HMAC("WebAppData", token)`, исключается **только** `hash` (поле `signature` остаётся в
  data_check_string — это и есть верное поведение для bot-token-метода; третье-сторонняя Ed25519-
  проверка signature — отдельный метод, тут не нужна), `hmac.compare_digest` (constant-time),
  TTL по `auth_date`. Я специально проверял гипотезу «signature должно исключаться» — спецификация
  Telegram её **опровергает**, kit прав. **SEV=info.**
- **guard_charge / DeliveryDedup — атомарные** `SET NX EX` в общем redis, ключи стабильны по
  бизнес-сущности (`tg:charge:<charge_id>`, `tg:notify:<key>`), TTL разумные (7д / 1д),
  `max(int(ttl),1)` от нуля. Это правильный паттерн идемпотентности.
- **errorux.py — чистый контракт**: Protocol `ErrorUX` + дефолтная прод-безопасная реализация;
  только «ожидаемые» dialog-ошибки (UnknownIntent/State/OutdatedIntent) ловятся в `dp.errors`
  (гасят «часики», `return True`), остальное сознательно проваливается в recovery-middleware ради
  `result=error` в observability. Шаблон override'ит через Provider, не трогая регистрацию. Это
  ровно тот баланс «механика в ките, тексты в шаблоне», который заявлен.
- **Обобщённость хорошая**: `build_invoice` поддерживает и XTR, и фиат (`provider_token`
  сбрасывается только для XTR); `NotificationRouter.on(stream, subject, durable, handler)` — без
  привязки к конкретному событию; `LocaleResolver` — Chain/Cache/Language. Под один кейс не
  заточено.

## Находки

### HIGH — DeliveryDedup метит seen ДО отправки + Delivery глотает ошибку отправки → двойное окно потери уведомления

`notifications/dedup.py:16-18` (`seen` ставит маркер атомарным `SET NX EX` и сразу возвращает
«не дубль»), `notifications/delivery.py:46-53` (`send_message` ловит **любое** исключение
`bot.send_message` и проглатывает — только лог).

Это **подтверждение** того, что нашли смежные агенты, и оно усугублено вторым звеном. Трасса
доставки (`natskit/jetstream.py:123-150` → `OrderDeliverer.on_order_paid` →
`features/notifications/deliver.py:29-36`):

1. JetStream доставляет msg (at-least-once, EXPLICIT-ack, `ack` после успешного хендлера —
   `jetstream.py:144`, `nak` на исключении — `:142`).
2. Хендлер зовёт `dedup.seen("order-paid:<id>")` → **ставит маркер «доставлено»** до фактической
   отправки.
3. Затем `delivery.send_message(...)` → `bot.send_message` падает (сеть/Telegram 5xx/flood-wait/
   chat not found) → **исключение проглочено** (`delivery.py:50-51`), хендлер возвращается
   нормально → `jetstream.py:144` делает `msg.ack()`.

Итог: сообщение **не доставлено**, но и redis помечен seen, и JetStream получил ack → **нет ни
одного механизма ретрая**. Даже если убрать проглатывание (чтобы прокинуть исключение в
`nak`-ретрай natskit'а), `seen`-маркер уже стоит → редоставка дропнется на шаге 2. То есть это
**два независимых окна потери**, и они складываются. Для «оплата заказа получена» это потеря
реального бизнес-уведомления.

Канонический фикс — паттерн **mark-after-success** или **reservation + commit**: `seen()` должно
ставить «in-progress» маркер с коротким TTL, а после успешной отправки апгрейдить его в «done»
(длинный TTL); при падении отправки — пробросить исключение (дать natskit'у `nak`/redeliver) и
**не** оставлять «done». Альтернатива — claim-key с коротким TTL + явный `commit(key)` после
отправки. Сейчас же контракт `DeliveryDedup` физически не даёт шаблону построить безопасную
доставку: `seen()` — единственный примитив, и он meta до отправки. То, что это «фон, at-least-once,
вряд ли задвоится» — не оправдывает потерю.

`fix`: разнести dedup на `reserve(key, short_ttl) -> bool` + `commit(key, long_ttl)`; в `Delivery`
**не** глотать исключение доставки (или возвращать bool успеха), чтобы хендлер мог сделать `raise`
→ `nak` → редоставка; commit ставить только после успешного `send`. Покрыть тестом «send упал →
второе событие доставлено».

### MEDIUM — Delivery заявляет «локаль закрыта», но send_message не локализован, а start_dialog локализуется лишь best-effort

`notifications/delivery.py:1-6` (docstring: «закрывает грабли фона … локаль …»),
`.claude/rules/background-updates.md` («Delivery закрывает: фон вне middleware → request_id/локаль
руками»). По факту:

- `Delivery.send_message` (`delivery.py:46-53`) — сырой `bot.send_message(text)`, **нулевой**
  locale-путь. Текст шаблон строит сам в `deliver_*` (`deliver.py:35` — хардкод-строка), и kit
  **не** даёт ему резолвер локали для фонового пути. Многоязычный бот пошлёт уведомление об оплате
  на дефолтной локали.
- `Delivery.start_dialog` (`delivery.py:38-39`) — `bg.start()` гоняет синтетический апдейт через
  `propagate_event("update")` (`bg_manager.py:173-176`), то есть **через** `I18nMiddleware`. Но
  резолвер `FromUserLanguage` читает `event.from_user.language_code`
  (`i18n/resolver.py:21-25`), а у фонового апдейта `from_user` — это `FakeUser`/результат
  `get_chat_member` (`bg_manager.py:178-196`); Telegram в `getChatMember`/`getChat`, как правило,
  **не** возвращает `language_code`. Значит локаль молча падает на `default_locale`, если бот не
  настроил `FromCachePref` (явный кэш-преференс). Это не сломано, но docstring/rule **переобещают**:
  «локаль закрыта» верно лишь при `FromCachePref` и только для `start_dialog`, не для
  `send_message`.

`request_id` для фона действительно проставлен руками (`delivery.py:36`, `:47`) — тут docstring
честен. Проблема только в локали.

`fix`: либо явно сузить контракт (docstring/rule: «`send_message` — pre-rendered текст, локаль —
ответственность шаблона; для локализованного фона используй `start_dialog` + `FromCachePref`»),
либо добавить в `Delivery` опциональный locale-aware канал (принимать `locale`/резолвер и прогонять
текст через `Translator.for_locale`).

### MEDIUM — нет дедупа по идемпотентному отбрасыванию некорректного payload → бесконечная редоставка («poison message»)

`natskit/jetstream.py:130-143`: любое исключение хендлера → `nak()` → редоставка. В цепочке
notifications нет различия «отравленное сообщение» (битый JSON / отсутствующие поля / неизвестный
`user_ref`) vs «временный сбой». Reference-deliverer мягко глотает битый payload
(`deliver.py:25-33` — `return` при пустых `order_id`/`user_ref`), но это **конвенция шаблона**, не
гарантия kit'а. Если durable-handler шаблона бросит на битом payload (а это легко: `payload[...]`
вместо `.get`), JetStream будет редоставлять его до `max_age` стрима (по умолчанию 7д,
`jetstream.py:67`), забивая consumer. Generic-механика NotificationRouter могла бы это закрывать
(try/except в `_bind` с метрикой `dropped` + `ack`), а не перекладывать на каждый `deliver_*`.

`fix`: в `router._bind` (или `subscribe_stream_json`) разделить «бизнес-ошибку парсинга →
ack+метрика drop» и «инфра-сбой → nak+redeliver»; либо ввести cap на redeliver (max_deliver в
ConsumerConfig). Сейчас `max_deliver` не задан (`jetstream.py:101-107`) → бесконечно.

### LOW — guard_charge ставит ключ ДО complete (как в платежах reference-фичи), но риск тут ниже

`payments/guard.py:23-28` + `features/payments/handlers.py:71-73`: `guard_charge` ставит
`tg:charge:<id>` и при «свежем» возвращает False → шаблон зовёт `uc.complete(...)`. Если
`uc.complete` упадёт **после** проставленного ключа, повторный `successful_payment` (Telegram
at-least-once) увидит дубль и **пропустит** fulfilment. То же окно «mark-before-commit», что в
notifications.

Почему **LOW**, а не HIGH: (1) docstring usecase (`features/payments/usecase.py:5`) требует, чтобы
`complete` сам был идемпотентен по `charge_id` на бэкенде — тогда «потерянный» first-try
довосстановится при следующем входе/реконсиляции; (2) `successful_payment` приходит и как часть
обычного апдейта (покрыт `DedupMiddleware` по `update_id`), и деньги уже у мерчанта (Stars) —
реконсиляция на бэкенде ловит расхождение. Это «mark-before-commit» по форме, но с
компенсирующим контуром. Тем не менее контракт `guard_charge` (единственный примитив — поставил и
забыл) такой же узкий, как `DeliveryDedup.seen`, и не даёт построить строго-безопасный fulfilment
без помощи бэкенда.

`fix`: при желании строгой безопасности на стороне бота — тот же reserve/commit-паттерн; либо явно
задокументировать в docstring `guard_charge`, что идемпотентность `complete` на бэкенде —
**обязательное** условие, а не рекомендация.

### LOW — answer_pre_checkout: исключение `answer_pre_checkout_query` не изолировано

`payments/precheckout.py:46-48`: если сам `bot.answer_pre_checkout_query` бросит (сеть), исключение
улетит наружу из `answer_pre_checkout` в dispatcher-хендлер → recovery-middleware погасит, но
платёж у пользователя **зависнет** (Telegram не получил ответ на pre_checkout). Метрика
`payments_total` тоже не запишется (строка `:49` не достигнута). Edge-кейс (Telegram API down в
момент ответа), но для «fail-closed»-механики стоило бы хотя бы записать метрику в `finally`.
`fix`: обернуть `answer_pre_checkout_query` и эмит метрики в `try/finally`, чтобы метрика всегда
писалась; при сбое ответа — лог + проброс (зависший платёж — это не то, что надо молча глотать).

### LOW — NotificationRunner.drain — пустышка, нет реального graceful-drain подписок

`notifications/runner.py:33-34`: `drain()` только логирует; реальный teardown — `container.close()`
закрывает NATS-соединение (`runner/base.py:76-81`). Это значит, что in-flight durable-доставки в
момент shutdown **не дренируются** упорядоченно: соединение рвётся, незаакраденные msg вернутся по
redelivery после рестарта. Для at-least-once это допустимо (не теряется, передоставится), но
docstring `runner.py:1-3` и комментарий «на shutdown — drain» создают ложное ощущение, что drain
реальный. `BotRunner` дренирует HTTP-апдейты (`shutdown_drain`), а фоновые — нет.
`fix`: либо реализовать `drain` (дождаться `JsBus._tasks`), либо переименовать/убрать иллюзию
(«teardown — через закрытие соединения; in-flight передоставятся»).

### INFO — метрики корректны и консистентны

`metrics.py`: `tg_payments_total{stage,result}` — но в `guard.py:27` лейбл `{stage:"paid",
result:"duplicate"}`, а в `precheckout.py:49` `{stage:"pre_checkout", result:...}`. Имена
консистентны, low-cardinality, описаны в `__init__.py:9-11`. Глобальный `get_meter("app")` с
no-op без telemetry — корректный паттерн. Единственное: `new_instruments()` дублируется (модульные
синглтоны `_instruments` в `guard.py`/`precheckout.py` **отдельные** от DI-инстанса в
`module.py:74`), т.е. метрики платежей идут через свой meter-инстанс мимо инжектированного
`TgInstruments`. Один и тот же meter («app»), так что данные сходятся, но это два пути к одному —
мелкая несимметрия (остальная механика берёт `instruments` из DI). **SEV=info.**

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. Платёжный guard, pre_checkout-валидация и
initData-проверка сделаны грамотно и спец-корректно — это самые security-чувствительные места, и
они закрыты правильно (подмена суммы/валюты не проходит, HMAC constant-time, fail-closed дедлайн).
Error-UX-контракт чистый. Главный риск — **доставка уведомлений теряет сообщения** при сбое
отправки (HIGH-находка): для бота, где push об оплате критичен, это надо чинить до прода. Но это
правится локально в kit без слома API шаблона.

**2. Насколько гибко?** Generic-механики обобщены адекватно: `NotificationRouter` не привязан к
событию, `build_invoice` тянет и XTR, и фиат, `LocaleResolver` композируется (Chain/Cache/Lang),
`ErrorUX`/notifier — точки расширения через Provider. Под один кейс не заточено. Слабое место
гибкости — **дедуп-примитивы слишком узкие**: и `DeliveryDedup.seen`, и `guard_charge` дают только
«пометил-и-забыл», без reserve/commit, поэтому строго-безопасную (без окна потери) доставку/
fulfilment на них не построить — приходится опираться на идемпотентность бэкенда. Это не «заточка
под кейс», а недо-обобщённость одного примитива.

**3. Тревога про один BackendClient** — вне моей области (это `platform/backend`), не оцениваю.
Замечу лишь, что в моей зоне аналогичной жёсткой привязки к одному API нет: payments/notifications
параметризованы (subject/durable/currency/provider_token), мульти-источник тут не упирается.

Вывод: механики корректны и достаточно обобщены, кроме **доставки уведомлений** — там реальный
дефект потери сообщений (HIGH) и переобещанная локаль (MEDIUM), оба чинятся внутри kit'а.
