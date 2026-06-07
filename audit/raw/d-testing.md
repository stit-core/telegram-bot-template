# Аудит области d-testing — стратегия тестов и покрытие (сквозной синтез)

## Что смотрел

Сквозная оценка тестовой стратегии шаблона + опора на pylibinfra-тесты и смежные отчёты.

- **Прогон покрытия шаблона**: `uv run pytest -m "not integration" --cov=bot --cov-report=term-missing -q`
  → **32 passed, TOTAL 84%** (833 stmts / 113 miss / 58 branch / 9 BrPart).
- **Раскладка тестов шаблона** (8 файлов, 697 LOC): `tests/unit/` (8 файлов — policy/config/i18n/
  webapp/notifications/payments/smoke), `tests/flows/` (4 — start/profile/payments/composition через
  `BotClient`+`MockMessageManager`+`JsonMemoryStorage`), `tests/backend/` (1 — транспорт через `respx`).
- **Фейки шаблона**: `tests/_fakes/{delivery,redis,backend,cache,harness}.py` — что и как маскируют.
- **Тесты pylibinfra** под боевую механику доставки: `tests/natskit/`, `tests/outboxkit/`,
  `tests/tgbotkit/` — что покрыто на стороне kit, что НЕТ.
- Сверял дыры в тестах с критичными находками смежных агентов (`p-msg.md` CRITICAL #1, `k-tgbot-feat.md`
  HIGH, `p-testkit.md` M1) — прошли бы ли они `make check` незамеченными именно из-за фейков/пробелов.

Инструментально подтверждено grep'ом:
- `get_error`/`patch_error` в `FakeBackendClient` — **0 тестов** их используют (только определение фейка).
- `AppErrorUX`/`on_unknown_*`/`ErrorEvent`/`UnknownIntent` — **0 тестов** (`grep tests/` → NONE).
- `pre_checkout`/`send_invoice`/`guard_charge`/`.complete(` в flow — только в **docstring**, объясняющем,
  почему они НЕ тестируются.
- natskit integration-тест дёргает только core-NATS roundtrip; `JsBus`/`subscribe_stream`/ack/nak/
  redelivery — **0 тестов** во всём pylibinfra.
- Ни одного теста на `Delivery`/`NotificationRunner`/`NotificationRouter`/`BotRunner` в `tests/tgbotkit/`.

## Сильные стороны

1. **Пирамида правильная и дисциплина «мокаем порт, не транспорт» соблюдена.** Unit бьёт по
   `policy`/`usecase`/валидаторам (чистое ядро), flow гоняет реальный пайплайн диспетчера, backend —
   намеренно транспорт-границу. `tests/backend/test_backend_client.py:26-59` мокает `httpx` через
   `respx` (легитимное исключение из правила) и проверяет маппинг **всех** HTTP-статусов в
   транспорт-ошибки (200→dict, 404→NotFound, 409→Conflict, 503→Unavailable) + проброс `Idempotency-Key`.
   Это образцовый transport-contract-тест.

2. **`JsonMemoryStorage` — честный паритет с прод-Redis-кодеком** (см. `p-testkit.md`): flow-тест
   round-трипит `dialog_data` тем же stdlib-`json`, что прод-`RedisStorage`, → ловит несериализуемый
   state (`datetime`/`Decimal`/`set`/ORM) **до** прода. Правило `tests-pipeline` явно запрещает
   подменять его dict'ом. Это закрывает реальный класс багов.

3. **flow-харнес 1:1 повторяет прод-проводку.** `tests/_fakes/harness.py:86` → `bind_dialogs`
   (`setup_dishka`→`setup_dialogs` строго последним) идентичен `runner/base.py:56-61`. То есть
   `test_composition.py` — настоящий startup-smoke: ловит коллизии `StatesGroup`, проверяет, что
   контейнер собирается и `Dispatcher` резолвится со всей middleware/i18n/command-проводкой.

4. **Платёжная безопасность (самое чувствительное) покрыта на уровне usecase.** `test_payments.py:38-56`
   проверяет «не доверять клиенту»: confirm сверяет сумму/валюту с бэкендом, fail-closed на
   backend-error. Это правильный фокус — подмена суммы атакующим не проходит.

5. **Фейки структурно совместимы с боевыми портами** (mypy-strict зелёный): `FakeBackendClient`,
   `FakeCache`, `FakeRedis` удовлетворяют Protocol'ам структурно — подмена на боевую реализацию не
   ломает типы. `# type: ignore[arg-type]` в `harness.py:63`/`test_notifications.py:18` — на
   nominal-границе DI, не на структурной.

6. **Кодовая гигиена тестов чистая**: маркеры `--strict-markers`, все тесты помечены слоем,
   контейнер закрывается в `finally` (нет утечки), нет `skip`/закомментированного кода.

## Находки

### HIGH

#### [H1] Критичный баг потери уведомлений (p-msg #1 / k-tgbot-feat HIGH) проходит `make check` зелёным — ровно из-за того, что `FakeDelivery` никогда не падает

`KEY=yes. CAT=testing, CONF=high.`

Это центральная связка «дыра в тестах ↔ найденный баг». Цепочка:

- Боевой баг (подтверждён `p-msg.md:60-92`, `k-tgbot-feat.md:54-89`): `DeliveryDedup.seen` метит ключ
  **до** отправки, а `Delivery.send_message` (`tgbotkit/notifications/delivery.py:46-53`) **глотает
  любое исключение** `bot.send_message`. На сбое отправки (Telegram 5xx / flood-wait / бот заблокирован)
  handler не бросает → `JsBus` делает `ack` → уведомление **потеряно навсегда**, at-most-once вопреки
  заявленному at-least-once.
- **Почему тест этого не ловит**: единственный тест доставки шаблона (`tests/unit/test_notifications.py`)
  гоняет `OrderDeliverer` поверх `FakeDelivery` (`tests/_fakes/delivery.py:13-17`), который **только
  аккумулирует** сообщения и **физически не умеет упасть**. Три теста проверяют ровно три happy/skip-
  ветки: «доставлено при link» (`:21-27`), «дедуп → второе не доставлено» (`:30-37`), «нет link →
  пропуск» (`:40-43`). Ветки «send упал → событие должно пережить» **нет и не может быть** — фейк не
  даёт инъекции ошибки.
- Хуже: тест `test_dedup_skips_second_delivery` **закрепляет дефектное поведение как корректное** —
  он зелёный именно потому, что dedup-before-send «работает». То есть тест-набор не просто пропускает
  баг, он его **узаконивает**: после правильного фикса (mark-after-success) этот тест придётся
  переписывать.

Итог: самый дорогой класс багов (потеря бизнес-уведомления об оплате) **гарантированно** проходит гейт
зелёным. `make check` даёт ложную уверенность ровно в том месте, где она дороже всего стоит.

*Fix:* `FakeDelivery` должен уметь инъекцию сбоя (`fail_on(chat_id)` / счётчик попыток, бросать
исключение) — тогда можно написать RED-тест «send упал → исключение пробрасывается / событие не
помечено done». Каноническое место фейка — testkit (`p-testkit.md` M1), а не template-local. До фикса
бага этот тест должен быть golden-regression на потерю.

#### [H2] Error-пути доставки бизнес-логики не покрыты ни одним тестом, хотя точки инъекции в фейках уже есть

`KEY=yes. CAT=testing, CONF=high.`

Систематический пробел: тестируется **только happy/skip-path**, error-mapping — нигде.

- `FakeBackendClient` имеет готовые `get_error`/`patch_error` (`tests/_fakes/backend.py:16-17,22,30,38`)
  — **их не использует ни один тест** (grep `tests/` → только определение фейка). То есть инфраструктура
  для error-теста заложена, но не задействована.
- Следствие: маппинг транспорт→домен в gateway'ях **не покрыт сквозь usecase/view**.
  `profile/gateway.py:23-26,37-40` (`BackendNotFound→ProfileNotFound`, `BackendUnavailable→ProfileError`)
  — покрытие 70%, непокрыты ровно except-ветки. `payments/gateway.py` — 67%, непокрыты строки 23-37
  (mapping/ошибки). `views.py` (единственное место «доменная ошибка → user-текст») — `profile/views.py`
  **32%** (непокрыто 24-32 — весь `error_text`/`to_window`-маппинг). Цепочка «бэкенд упал → домен-ошибка
  → текст пользователю» — заявленный ключевой контур фичи (`feature-architecture.md`: «views — единственное
  место превращения ошибки в текст») — **не проходится ни одним тестом**.
- flow-тесты (start/profile/payments) — все три **только happy-path** (grep error/fail в `tests/flows/`
  → только `test_composition`). Ни один не кликает в окно при упавшем бэкенде.

*Fix:* в каждый flow добавить error-ветку через `backend.get_error = BackendUnavailable(...)` и
ассерт, что окно показывает нейтральный текст, а не падает; unit-тест gateway-маппинга
(`BackendNotFound→ProfileNotFound` и т.д.) поверх `FakeBackendClient` с инъекцией.

#### [H3] Глобальный error-handler (`AppErrorUX`) — «сеть последней надежды» — покрыт на 36%, тестов 0

`KEY=yes. CAT=testing, CONF=high.`

`platform/dialogs/errors.py` — **36%** (непокрыто 20,23,26-32,36-38 — практически все ветки).
`AppErrorUX.on_unknown_intent`/`on_unknown_state`/`on_unhandled` — это инфра-сеть, которая ловит
`UnknownIntent`/`UnknownState` после рестарта/TTL и гасит «часики» callback'а. grep `tests/` по
`AppErrorUX`/`on_unknown`/`ErrorEvent`/`UnknownIntent` → **NONE**.

Связь с рисками: `state-migration` и `dialog-architecture` называют error-handler **критической сетью**
против `UnknownState` у живых юзеров на деплое (удаление/переименование `State`). Эта сеть не оттестирована
ни в шаблоне (0 тестов), ни сквозным flow-тестом на устаревшую кнопку. Регрессия в ней (кто-то правит
`on_unhandled`, ломает ветку callback vs message) пройдёт гейт зелёной. При этом сама `BotClient` это
позволяет: можно прогнать клик по кнопке из «протухшего» диалога и проверить, что answer на callback
сработал — инструмент есть, тест не написан.

*Fix:* flow-тест «протухшая кнопка → UnknownIntent → `AppErrorUX` гасит часики и подсказывает /start»
(старый message с callback после смены StatesGroup); unit-тест каждой ветки `AppErrorUX` с фейком
`ErrorEvent`/`Bot`.

### MEDIUM

#### [M4] Ноль integration-тестов в шаблоне при заявленном и проводном testcontainers-слое

`CAT=testing, CONF=high.`

Маркеры `integration`/`e2e` объявлены (`pyproject.toml:107-112`), `make test-integration` существует
(`Makefile:41-42`), testkit даёт `start_redis()`/`start_nats()`-контейнеры (`p-testkit.md`) — но
`pytest -m integration --collect-only` → **0 собрано**. Заявленный testcontainers-слой в шаблоне
**пуст**: все 32 теста гоняются без Docker. Покрытие 84% — это **полный** доступный сюит, не урезанный.

Почему это medium, а не info (в отличие от формулировки `_toolchain.md`): не сам факт «0 тестов», а
**что именно** остаётся непроверенным из-за этого. Все фейки шаблона **расходятся с боевой семантикой**,
и именно integration-лейн ловил бы дрейф:
- `FakeRedis` (`tests/_fakes/redis.py:25-27`) **молча игнорирует `ex` (TTL)** → «дедуп протух по TTL →
  доставилось второй раз» и «guard_charge истёк → повторный fulfilment» **непроверяемы** (боевой —
  `SET NX EX`, `notifications/dedup.py:17`).
- `FakeCache` (`tests/_fakes/cache.py:5,23,35`) **игнорирует TTL и tags** (`invalidate_by_tag` — pass).
- `JsonMemoryStorage` не воспроизводит TTL/`RedisEventIsolation`-гонки реального FSM-стораджа.

То есть на боте, где доставка/дедуп — заявленная фишка, **вся redis-семантика TTL/NX и весь
JetStream-ack-путь не проходятся ни одним тестом**: unit-фейки её игнорируют, integration-лейн пуст.
`make test-integration` сейчас гонять нечего.

*Fix:* минимум 2-3 integration-теста на боевом redis-контейнере: (а) `DeliveryDedup` с реальным TTL —
ключ протухает → повторная доставка; (б) `guard_charge` TTL; (в) flow со `start_redis()` вместо
`FakeCache`/`FakeRedis`, чтобы хотя бы один сценарий шёл против боевой redis-семантики.

#### [M5] ack/nak/redelivery JetStream — самая хрупкая механика доставки — не покрыта во ВСЁМ pylibinfra

`CAT=testing, CONF=high.`

Дублирует `p-msg.md` #4, но это сквозная дыра, бьющая по уверенности шаблона: единственный
natskit-integration-тест (`pylibinfra/tests/natskit/test_integration.py`) гоняет **core-NATS** roundtrip
(`NatsBus`/`subscribe_json`), а `JsBus`/`subscribe_stream`/`_handle_one`/ack/nak/redelivery — **0 тестов**
(подтверждено grep'ом по всему `pylibinfra/tests/`). Ни одного теста на `Delivery`/`NotificationRunner`/
`NotificationRouter`/`BotRunner` в `tests/tgbotkit/`. То есть **весь фоновый async-lifecycle доставки**
(подписка → ack/nak → drain на shutdown → at-least-once-гарантия) не проверен ни в ките, ни в шаблоне.
Именно здесь живут CRITICAL/HIGH-баги смежных агентов — и они не ловятся, потому что ветка вообще не
исполняется в тестах.

*Fix:* integration-тест на `NatsContainer` с JetStream в pylibinfra: handler бросает → `nak` →
redelivery; handler глотает ошибку → golden-regression на потерю; `max_deliver` исчерпан → не вечный цикл.

#### [M6] Платёжный end-to-end (invoice → pre_checkout → successful_payment) flow-тест-китом не проходится

`CAT=testing, CONF=high.`

`BotClient` гоняет диспетчер с `MockMessageManager`, но без боевого `Bot`, поэтому `send_invoice`/
`answer_pre_checkout_query` недоступны. Шаблонный flow честно это фиксирует **в docstring**
(`tests/flows/test_payments_flow.py:3-5`): клик «Купить» не делается. Покрытие `payments/handlers.py` —
**47%** (непокрыто 36-46,53-57,67-73 — ровно invoice/pre_checkout/successful_payment-ветки + guard_charge).
То есть самый ответственный денежный путь (счёт → pre_checkout-валидация → fulfilment с
`guard_charge`-дедупом) **end-to-end не тестируется**: раскидан по unit'ам usecase. А `guard_charge`
mark-before-commit (`k-tgbot-feat.md` LOW) — то же окно потери, что в notifications, — не проверяется
вовсе. Для not-питониста ограничение неочевидно: «BotClient есть, почему оплату не докликать до конца».

*Fix:* тонкий фейк-`Bot`, ловящий `send_invoice`/`answer_pre_checkout_query` в список вызовов (канонически —
в testkit, `p-testkit.md` L2), чтобы продуктовый код вокруг счёта и pre_checkout-decide тестировался без
сети; либо явно документировать границу и компенсировать unit'ами на guard_charge-дедуп.

### LOW / INFO

#### [L7] Покрытие 84% концентрирует пробелы ровно на error/UI-edge — структурный, а не случайный перекос

`CAT=testing, CONF=high.` Зелёное ядро (policy/usecase/dto — 90-100%), просадки кучно на error-handling и
UI-рендере: `dialogs/errors.py` 36%, `profile/views.py` 32%, `payments/handlers.py` 47%, `lang/usecase.py`
47%, `profile/gateway.py` 70%, `payments/gateway.py` 67%, `backend/client.py` 86% (непокрыты
декод/ошибки-ветки 52,55-56,62,70). Паттерн один: **happy-path зелёный, sad-path дыра**. Часть — reference-
фичи под `/de-template`, но `dialogs/errors.py` (H3) и `backend/client.py` остаются в любом боте. Это не
«низкое число», а системный профиль уверенности: код уверенно работает, когда всё хорошо, и не проверен,
когда что-то ломается.

#### [I8] `mypy` разъезжается по мажору между репо — type-уверенность общего API tgbotkit не сквозная

`CAT=build, CONF=high.` (Дубль `_toolchain.md`, но это часть тестовой/верификационной уверенности.) Шаблон
лочит mypy **1.20.2**, pylibinfra — **2.1.0** (`pyproject.toml:21` vs kit). Общий API tgbotkit
type-check'ается под разными мажорами strict-mypy → зелёный mypy в ките не гарантирует зелёный в шаблоне.
Статическая верификация границы kit↔шаблон не сквозная. *Fix:* согласовать диапазон, перелочить.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Для **типового** inline-диалогового бота — да: пирамида
правильная, flow-харнес гоняет настоящий пайплайн, платёжная безопасность и сериализация state покрыты
честно, гейт строгий и зелёный. **Но** уверенность системно перекошена в happy-path: error-пути доставки
(H2), глобальный error-handler (H3) и весь фоновый JetStream-lifecycle (M5) — **слепая зона**. Самое
опасное — `make check` даёт **ложную зелёную уверенность** там, где она дороже всего: критичный баг потери
уведомлений (потеря бизнес-пуша об оплате) проходит гейт зелёным **именно потому, что `FakeDelivery`
физически не умеет упасть** (H1), и существующий тест дедупа даже **узаконивает** дефектное поведение.
Заказчик прочитает «32 passed, 84%, at-least-once в доках» и будет уверен в надёжной доставке — а её нет.

**2. Насколько гибкая система?** Тестовая инфра гибкая **по форме** (async-CM, структурные фейки,
порт-моки), но **узкая по покрытию отказов**. Фейки реалистичны для happy-path и **систематически
нереалистичны на сбоях**: `FakeDelivery` никогда не падает, `FakeRedis`/`FakeCache` игнорят TTL — то есть
маскируют ровно те баги, которые смежные агенты нашли (потеря на сбое отправки, дедуп-протухание). Каждый
бот переписывает эти дрейфующие полу-реализации руками (нет переиспользуемых фейков в testkit), и они
расходятся с боевой семантикой. Плюс integration-лейн объявлен, проводен (testcontainers), но **пуст** —
вся redis-TTL/NX и JetStream-ack-семантика не проходится **ничем**.

**3. Про несколько BackendClient к разным API.** На тестовом уровне ограничения нет: `FakeBackendClient`
структурно-типизирован (Protocol, mypy-strict), параметризуется данными — «несколько разных клиентов»
тестируются независимыми фейками без проблем. Тестовая инфра синглтонность бэкенда **не закладывает**;
если негибкость есть — она в `platform/`, не в тестах. `CONF=medium` (сужу только по тестовой границе).

---
Итог: тестовая стратегия по форме образцовая (правильная пирамида, мок порта не транспорта, честный
JSON-кодек, реальный пайплайн в flow) — и при этом **стратегически уязвима в одном измерении: отказоустойчивость
не тестируется**. Три HIGH сходятся в одну точку — `make check` зелёный не означает, что бот переживёт сбой
бэкенда, упавшую отправку push'а или протухшую кнопку. Критичные баги доставки смежных агентов проходят гейт
незамеченными **по конструкции фейков**, а заявленный integration-слой, который бы их поймал, пуст.
