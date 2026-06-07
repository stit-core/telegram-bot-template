# Аудит области t-feat-lang-notif — фичи lang + notifications + контент локалей

## Что смотрел

- **lang** (выбор локали): `src/bot/features/lang/{__init__,dialogs,handlers,policy,ports,provider,state,usecase}.py`.
- **notifications** (NATS-router + доставка): `src/bot/features/notifications/{__init__,deliver}.py`.
- **Контент локалей**: `src/bot/locales/{ru,en}/*.ftl` (common, start, profile, payments, lang).
- **Связанная инфра в kit** (чтобы судить «не сломана ли механика»):
  `pylibinfra/tgbotkit/notifications/{dedup,delivery,router,runner}.py`,
  `pylibinfra/tgbotkit/i18n/resolver.py`, `pylibinfra/natskit/jetstream.py`.
- **Проводка**: `src/bot/extensions.py` (RouterBundle/CommandBundle/NotifierBundle/resolver),
  `src/bot/platform/links.py`, `src/bot/features/start/gateway.py` (кто пишет chat_link).
- **Тесты**: `tests/unit/test_notifications.py`, `tests/unit/test_i18n.py`, `tests/_fakes/delivery.py`.
- Прогнал: `pytest` (notifications+i18n — 5 passed), `lint-imports --config importlinter.toml`
  (3 контракта KEPT), `mypy src/bot/features/lang src/bot/features/notifications` (clean).

## Сильные стороны

- **Консистентность .ftl ключей идеальна.** Множества ключей `ru` и `en` совпадают пофайлово
  (`common/lang/payments/profile/start` — `keys identical` по каждому). Все ключи, на которые
  ссылается код, присутствуют в обоих каталогах:
  - `lang-choose` (`features/lang/dialogs.py:15`),
  - `common-back` (`platform/dialogs/common.py` фабрики, используется в profile/lang),
  - `start-btn-{profile,buy,lang}` (`features/start/dialogs.py:21-23`),
  - `start-welcome-{new,back}` (`features/start/policy.py:13` через getter),
  - `payments-buy` (`features/payments/dialogs.py:16`),
  - `profile-{edit-name,enter-name}` (`features/profile/dialogs.py:21,29`).
  Пропавших/лишних ключей нет. Параметры (`{ $username }`) согласованы между локалями.
  `test_i18n.py` дополнительно проверяет реальный парс через `FluentTranslator` из kit.
- **lang-флоу архитектурно чист и тонок.** Полный мини-гексагон: `policy` (PURE, источник
  `SUPPORTED_LOCALES`), `usecase` (знает только порт + policy, защищается от невалидной локали —
  `usecase.py:21-24`), `ports.LocaleStore` (узкий Protocol, один метод `set`), `provider`
  связывает порт с `tgbotkit.LocalePrefStore`. Инфра (хранилище предпочтения, резолвер) — в kit,
  шаблон только декларирует и пишет контент. Это ровно «by design» из брифа, не негибкость.
- **Смена языка применяется мгновенно и без рассинхрона ключей.** `LangUsecase.choose` пишет через
  тот же `LocalePrefStore`, что читает резолвер `FromCachePref` (`extensions.py:54`,
  `tgbotkit/i18n/resolver.py:35-42` — общий ключ `locale:<user_id>`). Приоритет явного выбора над
  `language_code` Telegram выставлен правильно (`ChainResolver(FromCachePref, FromUserLanguage)`).
- **notifications корректно вынесена из диалог-гексагона.** Не dishka-Provider, а
  `build_router(cache, redis) → NotificationRouter`, собирается `ExtensionProvider`'ом
  (`extensions.py:42-45`), т.к. нужны cache+redis из контейнера. `stream/subject/durable` и
  `deliver_*` — в шаблоне (`notifications/__init__.py:21`), механика подписки/ack/drain — в kit.
  Соответствует rule `background-updates`.
- **Грабли фона в основном закрыты.** Доставка идёт через `Delivery` (а не сырой `BgManager`/`bot`),
  дедуп — стабильный по событию (`order-paid:<order_id>`, `deliver.py:29`), резолв `chat_id` по
  link tg→chat с тихим пропуском при отсутствии (`deliver.py:32-33`), `deliver_*` быстрый
  (дедуп→резолв→отправка). `Delivery` изолирует `request_id` и глотает исключения send, чтобы не
  валить consumer (`tgbotkit/notifications/delivery.py:46-53`). Тесты покрывают «доставлено»,
  «второе событие — нет», «нет link — нет отправки».
- **import-linter / mypy зелёные** на обеих фичах; `notifications` корректно вне трёх контрактов
  (NATS-router, не гексагон) и это не ломает слоистость.

## Находки

### MEDIUM — Фоновые уведомления игнорируют локаль пользователя (текст захардкожен по-русски)

- **Доказательство:** `src/bot/features/notifications/deliver.py:34-36` —
  `text=f"✅ Оплата заказа {order_id} получена. Спасибо!"`. Текст не проходит через i18n, нет
  ключа в `*.ftl`. `Delivery.send_message` (`tgbotkit/notifications/delivery.py:46`) не имеет
  locale-aware варианта; резолвер локали работает только на incoming-Update (middleware), а фон
  идёт мимо него.
- **Почему важно:** это прямое противоречие смыслу области. Юзер, выбравший `en` через фичу lang,
  на фоновую доставку всё равно получит русский текст. Вся машинерия `LocalePrefStore`/`FluentTranslator`
  бессмысленна для push'ей. Для реального бота с не-русскоязычной аудиторией — баг UX.
- **Усугубляет:** docstring `deliver.py:4` и `delivery.py:5` заявляют, что «локаль закрыта в
  Delivery». Это неверно — `Delivery` ресетит только `request_id` (delivery.py:36,47), локаль не
  трогает. Документация вводит в заблуждение (forward-only тут описывает несуществующее свойство).
- **Fix:** добавить в kit locale-aware путь доставки (резолв предпочтения через `LocalePrefStore` +
  `Translator.for_locale` по `chat_id`/`user_id`, отдать `fmt` в `deliver_*`) — это инфра-механика,
  значит PR в `tgbotkit`, не локальный костыль; в шаблоне — ключ `notifications-order-paid` в
  `*.ftl` и рендер по нему. До этого хотя бы убрать ложное «локаль закрыта» из docstring.

### MEDIUM — Неявный кросс-системный контракт `user_ref == tg_id`, иначе доставка молча теряется

- **Доказательство:** chat_link пишется ключом по `tg_id` — `start/gateway.py:25`
  `await self._cache.set(chat_link_key(tg_id), ...)` (комментарий `:24` «user_ref(=tg_id)»). А
  читается ключом из payload-поля `user_ref` события `orders.paid` — `deliver.py:26,31,39`
  `chat_id = await self._lookup_chat(user_ref)`. Совпадает **только** если бэкенд кладёт в
  `user_ref` именно Telegram `tg_id`.
- **Почему важно:** остальная архитектура идентифицирует юзера на бэкенде через `backend_user_id`
  (`profile/gateway.py:20,29`, `identity` маппит `tg_id→backend_user_id`, `links.py:5`). Реверс-карты
  `backend_user_id→chat_id`/`→tg_id` нет. Натуральный для бэкенда payload (`user_ref =
  backend_user_id`) даст `_lookup_chat → None` и уведомление **тихо** пропадёт (`deliver.py:32-33`)
  — без ошибки, без лога. Потребитель шаблона легко напорется: всё «работает», но push'и не доходят.
- **Это reference-фича** (упрощение допустимо), но контракт `orders.paid.user_ref == tg_id` нигде
  не зафиксирован как messaging/INFRA-контракт с бэкендом.
- **Fix:** либо явно задокументировать инвариант поля `user_ref` в messaging-контракте/INFRA-HANDOFF
  и в docstring `deliver.py`, либо (честнее) писать chat_link по `backend_user_id` при линковке
  аккаунта и резолвить по нему. Плюс — логировать «link not found» (см. ниже), чтобы тихий промах
  стал диагностируемым.

### LOW — Дедуп помечает событие «seen» ДО фактической отправки → возможна потеря при сбое send

- **Доказательство:** порядок в `deliver.py:29-34` — сперва `self._dedup.seen(...)` (атомарный
  `SET NX EX`, `tgbotkit/notifications/dedup.py:16-18` — помечает доставленным), затем
  `delivery.send_message`. `Delivery.send_message` глотает любое исключение отправки
  (`tgbotkit/notifications/delivery.py:48-53`) и **не** перевыбрасывает, значит handler не падает,
  значит jetstream делает `msg.ack()` (`natskit/jetstream.py:144`), а не `nak`.
- **Почему важно:** если send упал транзиентно (сетевой сбой, временный 5xx Telegram), событие уже
  «seen» и уже ack'нуто → redelivery не будет, сообщение потеряно. Фактическая семантика send —
  at-most-once, хотя durable JetStream даёт at-least-once на доставку события. Тест
  `test_dedup_skips_second_delivery` это не ловит: `FakeDelivery` всегда успешен.
- **CONF=medium** (это намеренный trade-off «не валить consumer», но цена — молчаливая потеря).
- **Fix:** либо помечать `seen` ПОСЛЕ успешного send (тогда при провале — `nak` и повтор; но тогда
  send должен уметь сигналить провал, а сейчас глотает), либо признать at-most-once явно в доке.
  Поскольку и `Delivery`, и дедуп — kit, корректная семантика — решение на стороне kit (PR), не
  шаблона.

### LOW — Тихий промах доставки без лога мешает диагностике в проде

- **Доказательство:** `deliver.py:27,30,33,44` — все ветки «нет данных / уже видели / нет link /
  битый chat_id» возвращают `return` без единого лог-вызова. У `OrderDeliverer` вообще нет логгера.
- **Почему важно:** в связке с находкой про `user_ref==tg_id` это значит, что массовая потеря
  push'ей (неверный payload) будет абсолютно невидимой — ни метрики, ни лога на стороне фичи.
  Observability фоновой доставки на нуле в самом частом классе багов.
- **CONF=medium.** **Fix:** прокинуть `logkit.Logger` в `OrderDeliverer` и логировать причину
  пропуска (`link_not_found user_ref=...`, `dedup_hit`). Логи — только через `pylibinfra.logkit`.

### LOW — Окно выбора языка: подписи кнопок захардкожены, не из .ftl

- **Доказательство:** `features/lang/dialogs.py:17-18` — `Const("🇷🇺 Русский")` / `Const("🇬🇧 English")`.
  Сам заголовок окна i18n-айзед (`I18NFormat("lang-choose")`), а кнопки — нет.
- **Почему важно:** для языкового свитчера эндонимы («Русский»/«English») как раз корректно
  показывать на своём языке, так что это, скорее всего, **осознанно ок** (info-уровня). Но
  список языков продублирован между `policy.SUPPORTED_LOCALES` (`policy.py:8`), кнопками в dialogs
  и каталогами `locales/`. Добавление 3-го языка требует правки в 3+ местах синхронно — мелкий DX-риск.
- **Fix:** не критично; при росте числа локалей — генерировать кнопки из `SUPPORTED_LOCALES` (или
  getter'а) вместо статичной разметки.

### INFO — Рассинхрон docstring и реального ключа в `LocalePrefStore` (kit)

- **Доказательство:** `links.py:5` и docstring `tgbotkit/i18n/resolver.py:29` говорят про ключ
  `link:locale:<user_id>`, фактический ключ — `locale:<user_id>` (`resolver.py:36,42`).
- На lang-флоу **не влияет** (get/set симметричны, оба — `locale:<id>`), но дока врёт. Это kit, не
  шаблон. **Fix:** поправить docstring в kit. CONF=high (что код пишет `locale:`), но severity info.

## Ответ на вопросы заказчика в этой области

1. **Получится ли строить нормальных ботов?** Да, для i18n и базовой смены языка — фундамент
   крепкий: ключи консистентны, флоу выбора локали чистый и тонкий, инфра честно в kit. Главная
   практическая дыра — **фоновые уведомления не локализованы** (всегда русский текст) и **доставка
   завязана на необъявленный контракт `user_ref==tg_id`** с тихим промахом без логов. На «нормальном»
   боте с push-ами это всплывёт сразу. Чинится, но это не «допилить в шаблоне» — локаль в доставке
   и семантика дедупа/send живут в `tgbotkit`, т.е. требуют PR в kit.

2. **Насколько гибкая система?** lang гибок по дизайну (добавить локаль = каталог `locales/<x>/` +
   строка в `SUPPORTED_LOCALES`; резолвер цепочечный, легко вставить новый источник предпочтения).
   notifications гибок в части «какие stream/subject/handler» (`router.on(...)`), но **жёсткий** в
   двух местах: (а) нет locale-aware пути доставки вообще; (б) маппинг user→chat прибит к `tg_id`
   без реверс-карты по `backend_user_id`. Оба ограничения — в граничном слое к kit, а не в самой
   фиче, поэтому «гибкость» здесь упирается в точки расширения kit, что согласуется с философией
   репо, но конкретно для нотификаций точки расширения недостаточны (нет locale-хука в `Delivery`).

3. **Про множественные BackendClient'ы** — вне этой области (платформа/backend). В рамках lang/notif
   прямой зависимости от единственного `BackendClient` нет: lang ходит только в cachekit,
   notifications — в cachekit+redis+NATS, бэкенд не дёргают. Так что симптом негибкости из вопроса 3
   тут не проявляется.
