# Аудит области d-state — state и хранилище (сквозной синтез)

## Что смотрел

Линза сквозная: всё, что касается состояния пользователя — где живёт, как сериализуется,
как изолируется, как переживает деплой и как растёт/чистится.

Шаблон:
- `src/bot/platform/dialogs/states.py` — единый каталог `StatesGroup` всех фич.
- `src/bot/features/*/state.py` (start/profile/payments/lang) — модели `dialog_data` + re-export SG.
- `src/bot/features/*/{dialogs,handlers,getters}.py` — реальные записи/чтения state (`.start`,
  `switch_to`, `done`, `start_data`, getters).
- `src/bot/platform/dialogs/{common,errors}.py` — фабрики переходов (`open_dialog`/`Start`),
  `AppErrorUX` (сеть под `UnknownState`/`UnknownIntent`).
- `src/bot/platform/links.py` + `src/bot/features/start/{gateway,usecase}.py` +
  `src/bot/features/lang/provider.py` — **не-FSM** user-state в Redis (флаг онбординга, link tg→chat,
  локаль-преференс).

Kit (`pylibinfra/tgbotkit`):
- `storage.py` (`build_storage`/`build_isolation`), `module.py:84-85` (provide storage), `config.py`
  (env-поверхность), `errorux.py` (дефолтный error-UX), `i18n/resolver.py` (`LocalePrefStore`),
  `notifications/delivery.py` (`Delivery.start_dialog` — единственный фоновой писатель в FSM).
- `cachekit/cache.py` (сигнатура `Cache.set` с `ttl`).

Тесты: `tests/_fakes/harness.py` (`JsonMemoryStorage`), `pylibinfra/testkit/bottest/storage.py`.

Эмпирически:
- `mypy` + `ruff` на всех `state.py` + `states.py` — **чисто** (5 файлов, 0 issues).
- Интроспекция `DefaultKeyBuilder(with_bot_id=True, with_destiny=True)` на установленном aiogram
  3.28 — проверил реальные ключи (см. ниже).
- Grep `state_ttl|data_ttl|BOT_STATE_TTL|shutdown_drain` по **обоим** репо.

Опирался на готовые отчёты: `k-tgbot-runtime.md` (TTL-находка, `shutdown_drain`),
`t-feat-start-profile.md` (мёртвые `ProfileDialogData`/cross-feature), `t-platform.md`
(states.py как каталог, identity).

## Сильные стороны

- **Изоляция ключей сделана правильно и подтверждается эмпирически.** `with_destiny=True`
  разводит FSM-стейт aiogram (`destiny=default`) и контекст aiogram_dialog (`destiny=aiogd:*`):
  ```
  fsm:1:10:20:default:data       # aiogram FSM
  fsm:1:10:20:aiogd:default:data # aiogram_dialog контекст того же юзера
  ```
  Без `with_destiny` aiogram_dialog даже не стартует — `DefaultKeyBuilder.build` **бросает**
  `ValueError` на non-default destiny (проверил). `with_bot_id=True` разводит мульти-бот
  (`fsm:1:...` vs `fsm:2:...`). То есть оба флага не косметика, а необходимость, и выбраны верно
  (`storage.py:17`). Покрыто `tests/tgbotkit/test_storage.py:11-12`.

- **Мультиворкер-безопасность через `RedisEventIsolation`** (`storage.py:21-22`), не
  `SimpleEventIsolation` (in-memory, не синхронизирует процессы). При ≥2 воркерах два апдейта
  одного чата не войдут в гонку за контекст. Это правильный выбор для горизонтального масштаба.

- **JSON-сериализуемость state ловится тем же кодеком, что и прод.** `JsonMemoryStorage`
  (`testkit/bottest/storage.py:17-22`) на каждом `set_data` гоняет `json.loads(json.dumps(data))`
  и бросает `TypeError`, если внутри `datetime`/`Decimal`/`set`/ORM. Flow-тесты обязаны его
  использовать (`harness.py:78`), rule `tests-pipeline` прямо запрещает подменять его dict'ом. Это
  настоящий guard, а не декларация: несериализуемое падает в тесте до прода.

- **Централизация `StatesGroup` соблюдена буквально.** Все 4 группы (`Start`/`Profile`/`Payments`/
  `Lang`) — только в `platform/dialogs/states.py`; фичи делают локальный re-export
  (`ProfileSG = states.Profile`, `state.py:13`). Переходы между фичами — по `State` из каталога
  (`open_dialog(..., states.Profile.VIEW, ...)`, `common.py`/`start/dialogs.py`), не импортом модуля
  чужой фичи. Циклов импорта между диалогами нет by construction. Import-linter держит «чистое
  ядро»: `state.py` тянет `aiogram.StatesGroup` только транзитом через каталог.

- **dialog_data — действительно только примитивы.** Единственная модель данных диалога —
  `ProfileDialogData` (`profile/state.py:16`): `draft_name: str | None`. По всем фичам — ноль
  `datetime`/`Decimal`/`dataclass`/pydantic-объектов в том, что уезжает в Redis. `OnboardingStatus`
  (`start/state.py:16`) — pydantic, но это **возврат usecase**, не кладётся в `dialog_data`.
  Доменные сущности (`ProfileView`, `Order`) грузятся getter'ом по месту, не стейджатся в стейт —
  ровно как требует rule `storage-serialization` («храни черновик, не сущность»).

- **Deprecation-дисциплина задокументирована и подкреплена инструментом.** Docstring
  `states.py:3-4` + rule `state-lifecycle` + skill `state-migration` дают процедуру: не удалять/не
  переименовывать живой `State`, выводить через deprecation, версионировать при breaking,
  startup-smoke (`emit_startup`) как гейт. Error-handler на `UnknownIntent/UnknownState/OutdatedIntent`
  (`errorux.py:register_error_handlers`, override через `AppErrorUX`) — заявленная сеть.

- **Фоновая запись в FSM локализована и безопасна.** Единственный писатель стейта вне апдейта —
  `Delivery.start_dialog(data=...)` (`notifications/delivery.py:24-46`), и он берёт `data:
  dict[str, Any] | None`. В шаблоне `OrderDeliverer` его **не** использует — шлёт только
  `send_message` (`features/notifications/deliver.py:38`), FSM из фона не трогает. То есть на
  текущем коде фон не может занести несериализуемое в стейт.

## Находки

### HIGH — Безлимитный рост стейта пользователей в Redis: ни FSM/dialog, ни не-FSM user-state не имеют TTL

**CAT=state, CONF=high, KEY=yes**

Это системная, а не точечная проблема: **ни один** из видов состояния пользователя не истекает,
и все они лежат в **одном общем** Redis (cachekit-инстанс, тот же, что dedup/throttle/idempotency).

1. **FSM + dialog-контекст.** `build_storage` (`storage.py:14-18`) строит
   `RedisStorage(client, key_builder=...)` **без** `state_ttl`/`data_ttl`. aiogram 3.28 оба
   параметра поддерживает (params: `state_ttl`, `data_ttl`). Каждый когда-либо начавший диалог
   юзер оставляет `fsm:<bot>:<chat>:<user>:...:state` и `:data` навсегда.
2. **Флаг онбординга + link tg→chat.** `CacheOnboardingStore.mark_onboarded` (`start/gateway.py:25-28`)
   пишет `onboard:tg:<id>` и `link:chat:<id>` через `cache.set(...)` **без `ttl`** — хотя
   `Cache.set` принимает `ttl: timedelta | None` (`cachekit/cache.py:21-25`). Ключи вечные.
3. **Локаль-преференс.** `lang/provider.py:18` создаёт `LocalePrefStore(cache)` без ttl;
   `LocalePrefStore.__init__(cache, ttl=None)` → `cache.set("locale:<id>", ..., None)`
   (`i18n/resolver.py:31-42`). Тоже вечный.
4. **Нет env-ручки.** В `tgbotkit/config.py` нет `BOT_STATE_TTL`/`BOT_DATA_TTL` (grep по обоим репо
   пуст). Оператор не может включить экспирацию, не правя kit.

Последствие: на проде с заметной аудиторией Redis монотонно растёт по числу **уникальных
пользователей за всё время**, без авто-сборки — это тот же инстанс, что кэш/идемпотентность, так
что переполнение положит и их. Заказчик-не-питонист этого не увидит, пока Redis не упрётся в память.

**fix:** в `build_storage` пробросить `state_ttl`/`data_ttl` из нового `BOT_STATE_TTL`/`BOT_DATA_TTL`
(default, напр., 30 дней) — PR в kit, аддитивно. В шаблоне `mark_onboarded`/`LocalePrefStore`
вызывать с осмысленным `ttl` (это уже доступно сейчас, правка только шаблона). Связано с
`k-tgbot-runtime` MEDIUM (та же первопричина по FSM-половине).

### MEDIUM — Документация обещает TTL-экспирацию стейта, которой в коде нет (две точки)

**CAT=state, CONF=high, KEY=yes**

И kit, и шаблон объясняют «устаревшие кнопки» через TTL, которого на сторадже нет:
- `errorux.py:2-3`: «UnknownIntent/UnknownState (устаревшие кнопки после рестарта/**TTL**)».
- `platform/dialogs/errors.py:5`: «после рестарта/**TTL**».
- rule `state-lifecycle` (Чек): «Удалить deprecated State можно, только когда … **TTL storage
  истёк** / плановое окно».
- rule `storage-serialization`: «TTL на storage задаёт kit; … мёртвые ключи живут **до TTL**».

Поскольку TTL не выставлен (HIGH выше), TTL-ветка устаревания **невозможна** — стейл-стейт
возникает только от рестарта/деплоя/ручного reset, не от истечения. Это рассинхрон документа и
кода, и он опасен именно в state-migration: процедура «дожидаемся истечения TTL живых сессий,
потом удаляем deprecated State» (`state-lifecycle` Чек) **не сработает** — без TTL живые сессии не
истекают сами **никогда**, deprecated State нельзя безопасно удалить вообще. То есть HIGH-пробел
ломает заявленную миграционную дисциплину, а не только UX-формулировку.

**fix:** выставить TTL (см. HIGH) — тогда обещание станет правдой и окно для удаления deprecated
State обретёт смысл; либо переписать доки на «истекает только при выставленном `BOT_STATE_TTL`».

### MEDIUM — `ProfileDialogData` (единственная модель dialog_data) мертва: guard сериализации фактически не нагружен на проде

**CAT=state, CONF=high, KEY=no**

`ProfileDialogData`/`draft_name`/`has_unsaved` (`profile/state.py:16-20`) **не пишется и не
читается** ни одним getter/handler (подтверждено grep'ом и отчётом `t-feat-start-profile`).
Rename-флоу (`profile/handlers.py:on_save_name`) берёт `value` из аргумента виджета и сразу зовёт
`uc.rename`, минуя `dialog_data`. По остальным фичам `dialog_data`/`start_data` тоже **никто не
пишет**: `open_dialog`/`Start` создаётся без `data=` (`common.py:17-19`), `.start(...)` зовётся без
`data=` (`start/handlers.py:28`, `lang/handlers.py:36`). aiogram_dialog кладёт в Redis свой
служебный контекст, но **прикладной** `dialog_data` на всех текущих флоу пуст.

Следствие для линзы: единственная содержательная проверка «реально ли соблюдается
JSON-сериализуемость» (`JsonMemoryStorage`) на проде сейчас **не нагружена прикладными данными** —
ловить нечего, потому что в `dialog_data` ничего не кладут. Guard корректен и сработает, как только
появится первый реальный `update_data`/`data=`, но сегодня это «зелено, потому что пусто», а не
«зелено, потому что проверено на боевых данных». Риск: потребитель скопирует `ProfileDialogData`
как образец, добавит туда `datetime` (типичный «когда отредактировал») и узнает о падении только
если **не забудет** написать flow-тест, кладущий это поле. Образец молчит о том, что его надо
покрывать.

**fix:** либо оживить хотя бы один флоу через `dialog_data` (стейджить `draft_name`, тогда
`has_unsaved` обретёт смысл — предупреждение при выходе с черновиком) — чтобы `JsonMemoryStorage`
реально гонял прикладной state; либо пометить модель demo-only под `de-template` и в
`scaffold`/`storage-serialization` явно сказать «добавил поле в dialog_data → обязателен flow-тест,
кладущий его».

### LOW — Error-UX на `UnknownState` только гасит «часики», но не возвращает юзера в рабочий корень

**CAT=errors, CONF=high, KEY=no**

`AppErrorUX.on_unknown_state`/`on_unknown_intent` (`platform/dialogs/errors.py:21-28`) делают только
`cq.answer(_STALE)` — тост «Сессия устарела, нажмите /start». Они **не** вызывают
`dialog_manager.reset_stack`/не стартуют корневой диалог. После сломавшего флоу деплоя (удалён/
переименован State вопреки дисциплине) у юзера в Redis остаётся протухший стек, и каждый его клик
по старой кнопке снова даёт `UnknownState` → снова тост, пока он сам не нажмёт `/start`
(`/start` = `RESET_STACK`, чинит). Это **приемлемая** сеть (rule прямо разрешает error-handler как
сеть, а не авто-recovery), и без TTL (HIGH) сам стек не уберётся — но «сеть» здесь только
подсказывает, не восстанавливает. Усугубляется тем, что rule `state-lifecycle` называет
error-handler «сетью под ломающиеся переходы»: фактически сеть = текстовая подсказка, не сброс.

**fix:** в `on_unknown_state` дополнительно сбрасывать в корень (если есть `BgManager`/
`dialog_manager` в контексте error-event — стартовать `Start.MENU` с `RESET_STACK`), чтобы юзер не
залипал в петле тостов до ручного `/start`. Опционально; текущее поведение не ломающее.

### LOW — `DEMO_OFFER_ID` в `payments/state.py` мимикрирует под state, но это константа модуля

**CAT=dx, CONF=medium, KEY=no**

`payments/state.py:13` держит `DEMO_OFFER_ID = "premium-30d"` в файле `state.py`. Docstring честно
поясняет, что это демо и «в реальном боте оффер приходит из start_data/диалога». Само по себе не
баг (PURE-константа, разрывает импорт getters↔handlers), но в файле, чьё имя обещает «состояние»,
лежит хардкод-константа, а реальный механизм передачи оффера (`start_data`) в шаблоне **не
показан** — `Start`/`.start` нигде не зовётся с `data=`. Потребитель не увидит рабочего примера, как
прокинуть выбранный оффер в диалог через `start_data` (а это ровно та точка, где сериализуемость
`start_data` станет важна). fix: либо мини-пример `open_dialog(..., data={"offer_id": ...})` +
чтение из `start_data` в getter, либо явная пометка «оффер хардкожен для демо; в проде — `start_data`».

### INFO — Мультибот: ключи изолированы, но один процесс = один `Bot`/`Config.token`

**CAT=state, CONF=medium, KEY=no**

`with_bot_id=True` корректно изолирует стейт по `bot_id` на уровне Redis-ключей (проверено), так что
несколько ботов на **общем** Redis не пересекутся по стейту. Но `BotProvider` (`module.py:78-79`)
provide'ит ровно один `Bot` из единственного `cfg.token` — мультибот в одном процессе не
предусмотрен (это норма для бота, не дефект). То есть изоляция-по-bot_id — задел на «несколько
инстансов одного деплоя / разные боты на общем Redis», а не на multi-tenant в одном процессе.
Фиксирую как факт границы, не как проблему.

## Ответ на вопросы заказчика в этой области

**1. Получится ли строить нормальных ботов?** По части state — да, фундамент верный: изоляция
ключей (destiny + bot_id) сделана правильно и эмпирически подтверждена, RedisEventIsolation даёт
мультиворкер, `JsonMemoryStorage` ловит несериализуемый стейт в тестах тем же кодеком, что прод,
централизованный каталог `StatesGroup` + deprecation-дисциплина (rule + skill) закрывают главную
прод-граблю эволюции состояний. Но до «нормального прод-бота» не хватает **TTL на состоянии** — это
не косметика: без него (а) Redis растёт безлимитно по всем уникальным юзерам за всё время в общем
с кэшем инстансе, (б) задокументированная процедура безопасного удаления deprecated State («дождись
истечения TTL живых сессий») физически неисполнима. Это аддитивно чинится в ките.

**2. Насколько гибкая система?** В части state — гибкость правильной формы: добавить State —
аддитивно в каталог; новый диалог — новая `StatesGroup`; `dialog_data` расширяется моделью
(сериализуемость ловит тест). Жёсткие места: TTL вообще не настраиваемый (нет env), и образцы
(`ProfileDialogData`, `DEMO_OFFER_ID`/`start_data`) показывают **форму**, но не **живой** путь
данных через стейт — потребитель копирует структуру, не видя боевого примера записи/чтения, и
рискует узнать о несериализуемом поле только если сам напишет flow-тест.

**3. Про несколько клиентов к разным API.** Вне моей линзы (это `platform/backend`, разобрано в
`t-platform`). Со стороны state замечу лишь: не-FSM user-state (онбординг-флаг, chat-link,
локаль) живёт в одном cachekit-Redis с плоскими ключами без неймспейса по «сервису», так что
мультибэкенд это никак не структурирует и не мешает — стейт пользователя backend-агностичен. Связи
с тревогой нет. CONF=medium.

## Вердикт области

State-слой спроектирован грамотно в части **корректности**: изоляция ключей (destiny+bot_id) верна
и проверена, мультиворкер закрыт RedisEventIsolation, JSON-сериализуемость реально ловится тестом,
`StatesGroup` централизованы, deprecation-дисциплина задокументирована и подкреплена skill'ом. Слабое
место — **жизненный цикл/объём**: на всём состоянии пользователя (FSM, dialog, онбординг-флаг,
chat-link, локаль) нет TTL, всё в одном общем Redis → безлимитный рост и сломанная процедура
удаления deprecated State; документация при этом обещает TTL-экспирацию, которой нет. Плюс
прикладной `dialog_data`/`start_data` нигде не нагружен — guard сериализации зелёный «по пустоте»,
а образцы показывают форму без живого пути данных. Риск потери/порчи стейта при деплое прикрыт
дисциплиной + error-handler'ом (но handler только подсказывает `/start`, не восстанавливает);
главный реальный прод-риск — раздувание Redis и невозможность безопасно дочистить старые State.
