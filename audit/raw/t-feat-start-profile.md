# Аудит области t-feat-start-profile — фичи `start` + `profile`

## Что смотрел

Полностью прочитал обе фичи (все файлы, не семплинг):

- **start** (сокращённый гексагон): `__init__.py`, `state.py`, `dialogs.py`, `getters.py`,
  `handlers.py`, `usecase.py`, `policy.py`, `ports.py`, `gateway.py`, `provider.py`.
- **profile** (эталон полного гексагона): добавочно `dto.py`, `errors.py`, `views.py`,
  `adapters.py`.

Плюс контекст связности: `platform/dialogs/states.py`, `platform/dialogs/common.py`,
`platform/identity/{identity,provider}.py`, `platform/links.py`, `platform/backend/{client,__init__}.py`,
`shared/{decision,errors}.py`, `extensions.py`, `importlinter.toml`, локали
`locales/{ru,en}/{start,profile,common}.ftl`, тесты `tests/unit/test_profile_policy.py`,
`tests/flows/test_{start,profile}_flow.py`.

Эмпирически прогнал гейты на обеих фичах:

- `lint-imports --config importlinter.toml` → **3 контракта KEPT, 0 broken** (87 файлов, 283 зависимости).
- `mypy src/bot/features/{start,profile}` → **Success, no issues** (24 файла).
- `ruff check` + `ruff format --check` на обеих фичах → **All checks passed / already formatted**.

## Сильные стороны

1. **Заявленные инварианты держатся по-настоящему, а не на словах.** Все 3 контракта import-linter
   зелёные на реальном коде. Чистое ядро действительно чистое: `usecase`/`policy`/`dto`/`state`
   нигде не тянут `httpx`/`aiogram`/`redis`/свой `gateway` напрямую. `aiogram.StatesGroup` ядро
   получает только транзитом через `platform/dialogs/states` (`state.py:11` → `ProfileSG =
   states.Profile`) — это объявленная архитектура, а не утечка.

2. **Cross-feature сделан образцово и однонаправленно.** profile зависит от start (`adapters.py:9`,
   `provider.py:16` импортят `start.usecase`), start от profile — **не** зависит вообще (grep пуст).
   Цикла нет by construction. Порт `OnboardingReader` объявлен в **потребителе** (`profile/ports.py:21`),
   адаптер `OnboardingReaderAdapter` (`profile/adapters.py:12`) мапит чужой `StartUsecase` в свой
   контракт, связывание — только в `provider.py:28`. Это ровно тот anti-corruption-паттерн, который
   декларирует rule `feature-architecture`. Импорт чужой фичи живёт строго в `adapters.py`/`provider.py`.

3. **getter = данные / handler = реакции — разделение соблюдено буквально.** `profile/getters.py`
   только читает (`uc.view`), ловит доменную ошибку и кладёт мягкий `status` (`getters.py:27-31`) —
   окно не падает в recovery. `profile/handlers.py:on_save_name` мутирует (`uc.rename`), берёт данные
   из аргумента виджета `value` (не из getter), навигирует `manager.switch_to(ProfileSG.VIEW)`
   (`handlers.py:36`). getter и handler друг друга не импортят (контракт «один слой» — KEPT).

4. **dialog_data — только JSON-примитивы.** `ProfileDialogData` (`state.py:16`) — `str | None`,
   сериализуемо. Доменная сущность (`ProfileView` с бэкенда) **не** кладётся в state — грузится
   getter'ом по месту (`getters.py:26`). Это ровно то, что требует rule `storage-serialization`
   («храни черновик, не сущность»).

5. **`/start` = `RESET_STACK`, корень = `LaunchMode.ROOT`** — оба грабли учтены: `handlers.py:28`
   (`StartMode.RESET_STACK` с комментарием-WHY про `DialogStackOverflow`), `dialogs.py:29`
   (`launch_mode=LaunchMode.ROOT`). Переходы в другие фичи — по `State` из каталога
   (`open_dialog(..., states.Profile.VIEW, ...)`, `dialogs.py:21`), не импортом модуля фичи.

6. **Маппинг ошибок «единственное место» соблюдён.** `gateway.py` — единственный I/O, мапит
   `BackendNotFound`/`BackendUnavailable` → sentinel'ы фичи (`profile/gateway.py:23-26`). `views.py`
   — единственное место «доменная ошибка → user-текст», причём `error_text` корректно **пробрасывает**
   не-свою ошибку в recovery-middleware (`views.py:31-32` `case _: raise err`), а не глотает её.
   Idempotency-Key на `update_name` (`gateway.py:35`) — защита от двойных кликов, обоснована
   комментарием.

7. **Тонкость не мешает: фасад чистый.** `__init__.py` экспортит ровно `Provider` + `dialog`
   (+ `cmd_spec` у start). `extensions.py:37-42` видит только это. Полное покрытие гейтов на фичах.

## Находки

### info (сильная сторона / by design, не дефект)

**[info] Эталон полного гексагона — это эталон, а не оверинжиниринг конкретного сценария.**
profile несёт 14 файлов на сценарий «показать профиль + переименовать». Для самого сценария это
объективно много церемонии (policy из 2 правил, dto из 3 полей, views на 2 функции). Но это
**референс-фича** — CLAUDE.md прямо называет profile эталоном, который потребитель изучает и потом
прунит через `/de-template`. Налог осознанный и одноразовый (платится один раз при изучении, не на
каждой реальной фиче — реальная фича может быть сокращённой, как start, см. `importlinter.toml:9`
про опциональные слои). Это **не** проблема шаблона. CONF=high.

### low

**[low | CAT=architecture | CONF=high] Cross-feature-цепочка profile→start существует только как
демонстрация — у неё нет живого вызова в presentation.** `ProfileUsecase.is_first_time`
(`usecase.py:37-38`) — единственный потребитель порта `OnboardingReader`. Но `is_first_time`
**не вызывается нигде**: ни в `getters.py`, ни в `handlers.py`, ни в тестах (grep по `src/`+`tests/`
пуст). То есть весь цепочечный аппарат — порт `OnboardingReader` (`ports.py:21`) → адаптер
(`adapters.py:12`) → провайд `onboarding` + зависимость `usecase` от обоих портов (`provider.py:28-33`)
— собран и проверен mypy/import-linter'ом, но в рантайме профиля мёртв. flow-тест профиля гоняет
только view→rename, путь onboarding-reader не покрыт. Это **корректно как reference-scaffold**
(показывает паттерн «как объявить cross-feature-порт»), но честно: связность здесь архитектурная, не
функциональная. Риск: потребитель скопирует паттерн, не поняв, что в его-то фиче порт должен иметь
реального вызывающего. fix: либо добавить живой вызов (напр. getter профиля показывает онбординг-
подсказку первому визиту через `is_first_time`), либо в доке/комментарии явно пометить цепочку как
demo-only, чтобы de-template корректно её прунил.

**[low | CAT=state | CONF=high] `ProfileDialogData`/`draft_name`/`has_unsaved` объявлены, но не
используются.** Модель dialog_data (`state.py:16-20`) не читается и не пишется ни в одном
getter/handler (grep по `src/` находит только определение). Rename-флоу пишет имя напрямую через
usecase, не стейджит черновик в `dialog_data`. То есть пример «правильной JSON-сериализуемой модели
state» — образец без потребителя. Как референс это ок (показывает форму модели), но как «реальная
связность» — нет. fix: либо стейджить ввод через `dialog_data` (тогда `has_unsaved` обретёт смысл —
напр. предупреждение при выходе с несохранённым черновиком), либо пометить как demo-only под прун.

### info (мелкое наблюдение, не баг)

**[info | CAT=correctness | CONF=medium] В `start/getters.py` имя пользователя и статус берутся из
двух разных источников.** `username` — из `kwargs.get("event_from_user")` (`getters.py:28-29`),
а `status` — по `identity.tg_id` (`getters.py:30`). Для апдейтов без `from_user` identity даёт
синтетического юзера `tg_id=0` (`identity/provider.py:31-32`), а `event_from_user` будет `None` →
`username=""`. Источники согласованы по смыслу (оба про «текущего юзера»), рассинхрона на нормальном
апдейте нет; для меню `/start` `from_user` всегда присутствует. Помечаю как наблюдение, не дефект:
getter мог бы брать имя тоже из `identity` ради единого источника, но это стилистика, а не баг.
CONF=medium.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** — Да. Обе фичи — рабочий, проверенный гейтами шаблон
полного и сокращённого гексагона. Разделение getter/handler, маппинг ошибок в одном месте, RESET_STACK/
ROOT, JSON-сериализуемый state, cross-feature через adapters — всё это реальные грабли продакшн-ботов,
и шаблон их закрывает **конвенцией + enforce'ом** (import-linter ловит нарушение слоёв на CI, а не на
ревью). Новичок, копируя profile, получает корректную структуру «бесплатно».

**2. Насколько гибкая система (в этой области)?** — Внутри парадигмы «фича = вертикальный гексагон»
система гибкая и расширяемая: добавить окно/порт/cross-feature-зависимость — аддитивно, по
накатанным точкам. Цена гибкости — церемония: даже флаг в Redis (start) проходит через
ports→gateway→provider (5 косвенностей на один `set`). Для тонкого слоя это оправдано
тестируемостью (порт мокается фейком), но потребителю с простым ботом это будет ощущаться как налог
— смягчается тем, что сокращённый гексагон (start/lang) официально разрешён (`importlinter.toml`
опциональные слои).

**3. Про несколько `BackendClient` к разным API** — в **моей** области виден симптом, релевантный
тревоге: и start, и profile ходят к одному backend (start — в cachekit, profile — в единственный
`BackendClient`, `gateway.py:13`/`provider.py:24`). Порт `BackendGateway` объявлен в фиче
(`profile/ports.py:15`) и возвращает **локальные** DTO — то есть на уровне фичи анти-коррупция уже
есть, и подменить за портом другой клиент архитектурно **можно** без правки ядра. Узкое место не в
фиче, а в том, что `provider.py` инжектит конкретный `BackendClient` (один тип, один APP-провайдер).
Это **не** негибкость самой фичи (фича знает только Protocol), а вопрос к `platform/backend` — он
вне моей области, передаю агенту по platform. By design в фиче — норм; мультиклиентность упрётся в
один `BackendProvider`, а не в гексагон profile.
