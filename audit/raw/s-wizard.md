# Стресс-сценарий s-wizard — тяжёлый многошаговый wizard

**Сценарий.** Регистрационный/анкетный wizard на 10+ окон: динамические виджеты (пагинируемые
списки, мульти-селект, ввод с валидацией), условные ветвления, свободная back-навигация,
промежуточное сохранение черновика. Прогоняю по реальному коду шаблона + конвенциям + механике
aiogram_dialog (из `aiogram-dialog-docs/`), ищу где трещит.

## Что смотрел

Реальный код шаблона (все фичи целиком):
- `platform/dialogs/states.py` — единый каталог `StatesGroup` (4 группы, макс. 2 состояния).
- `platform/dialogs/common.py` — фабрики `open_dialog`/`back_to_menu` (только `Start`/`Cancel`).
- `platform/dialogs/errors.py` — `AppErrorUX` (stale-callback UX).
- `features/profile/{dialogs,getters,handlers,usecase,policy,state}.py` — эталон полного гексагона
  с 2-оконным флоу (VIEW + EDIT_NAME с `TextInput`).
- `features/payments/{dialogs,getters,handlers,state}.py` — единственное окно с динамикой + dispatcher-level.
- `features/start/{dialogs,handlers}.py`, `features/lang/{dialogs,handlers}.py` — single-window.
- `importlinter.toml` — 3 контракта (слои фичи, независимость фич, чистое ядро).

Конвенции/процедуры шаблона:
- `.claude/rules/{dialog-architecture,feature-architecture,storage-serialization,state-lifecycle}.md`.
- `.claude/skills/scaffold/references/{window,dialog}.md` — как шаблон велит добавлять «шаг визарда».
- `.claude/skills/dialog-deep-dive/SKILL.md` — проектирование флоу (включая wizard-состояние).

Механика aiogram_dialog (прочитал целиком, сверка с реализацией библиотеки):
- `reference/04-context-intent-storage-stack.md` — `dialog_data`/`widget_data`/`start_data`, лимиты,
  `Data = dict|list|int|str|float|None`, `_STACK_LIMIT=100`, удаление контекста при `done`.
- `reference/05-transitions-states.md` — `next`/`back`/`switch_to`/`start`/`done`, `StartMode`,
  `LaunchMode`, нецикличность `next/back`, sub-dialogs.
- `reference/11-kbd-select.md` — `Multiselect`/`Radio`/`Toggle`, `widget_data`, callback ≤64б.
- `reference/15-scrolling-listgroup-pager.md` — `ScrollingGroup`/`Pager`/`StubScroll`/`ListGroup`.
- `reference/16-input-widgets.md` — `TextInput`/`MessageInput`, валидация (`ValueError` → `on_error`).
- `reference/19-common-custom-data.md` — поток getter→render, `manager.find`, `update`.
- `guides/building-a-template.md` — wizard-чтение `find().get_value()` в финальном getter.

Опирался на готовые отчёты: `d-state.md` (TTL-пробел, мёртвый `dialog_data`), `k-tgbot-i18n.md`
(локаль), `t-feat-start-profile.md` (гексагон-эталон).

Эмпирически: `grep` по `src/` на `Multiselect|ScrollingGroup|Counter|MessageInput|find(|
update_data|manager.dialog_data|.start_data|next()|.back()|dialog_data[` → **пусто**. То есть в
шаблоне нет ни одного рабочего примера динамического виджета, чтения widget-состояния, записи в
`dialog_data`/`start_data`, или императивной `next/back`-навигации.

---

## Вердикт: **awkward** (сценарий поддерживается механикой, но шаблон не даёт ни образца, ни конвенции под него)

Wizard физически реализуем — вся механика aiogram_dialog под него есть (документирована
исчерпывающе в `aiogram-dialog-docs/`), а гексагон-структура шаблона **не разваливается** на
большом флоу (вертикальный срез масштабируется аддитивно, см. ниже). Но шаблон как **референс**
обрывается ровно там, где начинается тяжёлый wizard: самый сложный его флоу — это 2 окна без
единой записи в `dialog_data`. Потребитель, копирующий шаблон, не находит образца ни для одного из
ключевых wizard-механизмов и вынужден изобретать конвенцию сам — с риском упереться в каждую граблю,
которую механика уже расставила. Плюс две системные дыры (нет TTL на state, нет конвенции
«куда девать промежуточный выбор») делают wizard на проде хрупким.

---

## Сильные стороны (что под wizard уже верно)

1. **Гексагон-структура НЕ разваливается на большом флоу.** Логика шагов раскладывается чисто:
   `policy.py` (`profile/policy.py:18` `validate_name` → `Decision`) — это ровно «валидация шага
   wizard'а», PURE, юнит-тестируется без бота. `usecase.py` оркеструет (`profile/usecase.py:29`
   `rename`: policy-чек → порт). Окна — разметка (`dialogs.py`), данные — getter, реакции/навигация
   — handler. На 10 окон это растёт **аддитивно**: +окно = +State в каталог + getter + handler в те
   же файлы (`scaffold/references/window.md`). Слои не плывут — import-linter держит
   `dialogs→getters|handlers→views→usecase→policy→ports→dto|state` (`importlinter.toml`). Логика
   шага живёт в `policy`/`usecase`, не в presentation — это правильный ответ на «где живёт логика
   шагов».

2. **Свободная back-навигация механически бесплатна.** `switch_to`/`Back` не трогают стек и
   **сохраняют** весь `widget_data`/`dialog_data` (`reference/05` §1). Прыжок назад на 5 окон и
   вперёд — состояние виджетов целое (`Multiselect` хранит `list[str]` в `widget_data[id]`,
   `TextInput` — исходную строку). То есть «вернулся, поправил, пошёл дальше» работает из коробки,
   без ручного сейва. Это сильная сторона именно для wizard.

3. **Валидация ввода + показ ошибки — есть рабочий образец.** `profile/dialogs.py:30` (`TextInput`
   с `on_success`/`on_error`) + `handlers.py:on_save_name` (`uc.rename` → доменная ошибка →
   `views.error_text` без падения окна) + `on_name_error` (`handlers.py:39`, ловит `ValueError` от
   `type_factory`). Это правильный двухуровневый паттерн: синтаксис (`type_factory` → `on_error`),
   семантика/домен (policy в usecase → `error_text`). Для wizard-поля (`int` возраст, диапазон)
   масштабируется: `type_factory=int`, кастомный парсер с `raise ValueError`. Образец один (str), но
   паттерн верный.

4. **JSON-инвариант на `dialog_data` подкреплён тестом-кодеком.** `JsonMemoryStorage` ловит
   несериализуемое тем же json, что прод-Redis (`storage-serialization.md`, отчёт `d-state.md`). Для
   wizard это критично — туда полезет «дата рождения»/«выбранные теги», и flow-тест поймает
   `datetime`/`set` до прода. Guard корректен.

5. **`/start`=RESET_STACK + корень ROOT** учтены (`start/handlers.py:28`, `start/dialogs.py:29`) —
   wizard не упрётся в `DialogStackOverflow` от повторных входов в меню. Вход в wizard — `Start`
   (вложенный диалог поверх корня), выход — `Cancel`/`done` (`common.py`). Стек-дисциплина под
   wizard верная.

---

## BREAKING_POINTS

### [SEV=high] Нет конвенции и образца «куда девать промежуточный выбор/объекты между шагами»

**Evidence:** `grep` по `src/` на `manager.dialog_data|update_data|.start_data|find(` → **пусто**.
Единственная модель данных диалога `ProfileDialogData` (`profile/state.py:16`, `draft_name`,
`has_unsaved()`) **не пишется и не читается нигде** (подтверждено `d-state.md` MEDIUM, grep пуст).
Rename-флоу берёт `value` из аргумента виджета и сразу зовёт usecase (`handlers.py:32`), минуя
`dialog_data`.

**Почему трещит для wizard.** Wizard на 10 окон **обязан** копить промежуточное состояние между
шагами (выбор на шаге 3 нужен для ветвления на шаге 7; финальный submit собирает всё). Механика
aiogram_dialog даёт **два разных** хранилища с разной семантикой, и шаблон не показывает **ни
одного**:
- `widget_data[id]` — состояние самого виджета (`Multiselect.get_checked()→list[str]`,
  `TextInput.get_value()`), читается через `manager.find(id)` (`reference/19` §7). Финальный getter
  собирает: `manager.find("tags").get_checked()` (`building-a-template.md` §6.3).
- `dialog_data` — произвольный рабочий словарь шага (`manager.dialog_data["chosen_plan"]=...`,
  `reference/19` §9), для данных, которых нет за виджетом (вычисленное, пришедшее с бэкенда).

Лимит — **только JSON-примитивы** (`Data = dict|list|int|str|float|None`, `reference/04` §2).
Промежуточные **доменные объекты** (выбранный `Offer`, загруженный `Address`) класть **нельзя** —
их кладут как `model_dump(mode="json")` либо хранят только id и перезагружают getter'ом по месту
(`storage-serialization.md`). Шаблон декларирует это правило, но **не показывает рабочего пути**:
потребитель видит `ProfileDialogData` как форму-образец, копирует, кладёт туда `datetime`
(«когда заполнил шаг») и узнаёт о падении только если **не забыл** flow-тест на это поле
(`d-state.md` MEDIUM). Для 10-шагового wizard'а это не теоретический риск, а первая же стена.

**workaround:** есть, но самодельный — потребитель сам выбирает между `widget_data` (через
`find()` в финальном getter) и `dialog_data` (через `manager.dialog_data[...]` в handler), сам
следит за `model_dump(mode="json")` для не-примитивов, сам покрывает flow-тестом. Конвенции
«стандартный способ нести черновик wizard'а» в шаблоне нет — `dialog-deep-dive` спрашивает «что
держим в `dialog_data`/`widget_data`», но образца-ответа нет.

---

### [SEV=high] Динамические виджеты (списки/пагинация/мульти-селект/счётчик) — ноль образцов; каждая грабля механики не закрыта примером

**Evidence:** `grep` по `src/` на `Multiselect|ScrollingGroup|Counter|MessageInput|Radio|
ListGroup|StubScroll` → **пусто**. Импортируются в шаблоне только `Button|Column|Row|Cancel|Start|
SwitchTo|Back|TextInput|Format|Const|I18NFormat` (статика + один `TextInput`). Самый «динамический»
виджет в шаблоне — `Format("{title}...")` в `payments/dialogs.py:15` (плоская подстановка из
getter).

**Почему трещит.** Wizard со «списком с пагинацией» и «мульти-селектом» требует именно тех
виджетов, которых в шаблоне нет, а у каждого — нетривиальная грабля, описанная в доке, но не
снятая образцом:
- `ScrollingGroup(height=0)` → `ZeroDivisionError` (`reference/15` §8.1) — дефолт ломающий, легко
  пропустить.
- `Select`/`Multiselect`: `callback_data = f"{widget_id}:{item_id}"` ≤ 64 байт (`reference/11` §11.2)
  — длинный item_id (UUID/путь) обрежется Telegram'ом; нужен суррогатный короткий id + маппинг.
- `id` виджета — `^[a-zA-Z0-9_.]+$`, без `:`/пробелов/кириллицы (`reference/11` §8). Шаблонные id
  (`to_profile`, `lang_ru`) этому следуют, но потребитель на динамике (`item_id_getter`) обязан
  обеспечить это сам.
- `Multiselect` помнит исчезнувшие при пагинации id (`reference/11` §11.6) — `get_checked()` вернёт
  «осиротевшие».
- Дефолтные значения `Radio`/`Multiselect` ставятся в `on_start`, не параметром виджета
  (`building-a-template.md` §6.3) — неинтуитивно.

**workaround:** есть — вся механика подробно документирована в `aiogram-dialog-docs/`, потребитель
реализует с нуля по reference. Но шаблон тут перестаёт быть **шаблоном** (копируй-адаптируй) и
становится «читай доку библиотеки» — для не-питониста-заказчика (вопрос брифа) это резкий обрыв
кривой обучения ровно на самой нужной для wizard'а части.

---

### [SEV=medium] Промежуточное сохранение черновика брошенного wizard'а живёт в Redis вечно (нет TTL)

**Evidence:** `build_storage` в ките строит `RedisStorage` без `state_ttl`/`data_ttl` (отчёт
`d-state.md` HIGH, `k-tgbot-runtime`). Контекст диалога (`dialog_data`/`widget_data`/`start_data`)
**не удаляется** при брошенном wizard'е — `done`/`Cancel` удаляют контекст (`reference/04` §11), но
**брошенный** (юзер ушёл на шаге 6 и не вернулся) остаётся в стеке навсегда.

**Почему трещит для wizard.** Wizard — самый «бросаемый» флоу (длинный, юзер устаёт на середине).
Каждый недозаполненный wizard оставляет полный `widget_data` (все выборы) + `dialog_data` в Redis
**без экспирации**. На аудитории это монотонный рост в том же Redis, что кэш/идемпотентность
(`d-state.md` HIGH). Хуже: задокументированная процедура «дождись истечения TTL, потом удали
deprecated State» (`state-lifecycle.md` Чек) для wizard'а **неисполнима** — без TTL живые брошенные
сессии не истекают, а у wizard'а на 10 State любая правертка флоу (убрать шаг) упирается в
state-migration, которая зависит от несуществующего TTL (`d-state.md` MEDIUM).

**workaround:** «нет» на уровне шаблона. TTL правится в ките (`build_storage` + env `BOT_STATE_TTL`)
— это PR в tgbotkit, не шаблон. До него брошенные черновики wizard'а копятся вечно.

---

### [SEV=medium] Условное ветвление флоу: `next/back` нецикличны и завязаны на порядок окон в `Dialog` — для wizard это хрупко, образца ветвления нет

**Evidence:** `manager.next()` на последнем окне → `ValueError`; `back()` на первом → `ValueError`
(`reference/05` §1, нецикличны). `next/back` берут порядок из `self.dialog().states()` = порядок
передачи `Window` в `Dialog` (`reference/05` §1). В шаблоне `next/back` **не используются** ни разу
(grep пуст) — навигация только `switch_to`-эквивалентами (`SwitchTo`/`Back`/`Cancel`/`Start`).
`scaffold/references/window.md:91` прямо отмечает «порядок окон не важен для роутинга — важен
state=», что верно для `switch_to`, но **ломается** для `Next/Back` (там порядок = навигация).

**Почему трещит.** Wizard с «условными ветвлениями» (если на шаге 3 выбрал A → шаги 4-5, если B →
шаг 6) плохо ложится на линейный `Next/Back`: пропуск окна, разные хвосты, динамическая длина —
всё это `reference/05` §12.3 прямо называет краевым случаем для динамических визардов («проверяйте
границы или используйте `switch_to`»). Правильный ответ — императивная навигация в handler
(`if decision: manager.switch_to(SG.STEP_A) else manager.switch_to(SG.STEP_B)`), где целевой State
вычисляется из собранного `dialog_data`/widget-состояния. Шаблон не показывает **ни** условного
`switch_to` из handler по данным, **ни** работы с `dialog_data` для принятия решения о ветке.
Образец навигации в шаблоне — только безусловные `SwitchTo(state=...)`/`Cancel`/`done`.

**workaround:** есть — `switch_to(target)` с `target`, вычисленным в handler по
`manager.find()`/`manager.dialog_data`. Архитектурно чисто (решение о ветке — `policy`, возвращает
целевой шаг). Но это снова самодельно: ни scaffold, ни dialog-deep-dive не дают паттерна
«ветвление wizard'а», только перечисляют переходы как опции.

---

### [SEV=low] Свободный текстовый ввод в wizard поверх вложенного диалога требует reply; одно окно = один input-слот

**Evidence:** `reference/16` §7.1: обычное сообщение грузит контекст только из `DEFAULT_STACK_ID`;
диалог в дочернем/именованном стеке получит ввод лишь при **reply** на сообщение бота с
inline-кнопками. Окно держит **один** input-слот; несколько input → `CombinedInput`, порядок =
объявление, первый принявший выигрывает (`reference/16` §5).

**Почему слегка трещит.** Wizard обычно запускается как вложенный диалог из меню (`Start`, как
`payments`/`profile` в шаблоне) — это **дефолтный стек** в личке (`storage.py:_fixed_stack_id`),
так что ввод работает без reply. Проблема всплывает только если wizard уйдёт в `NEW_STACK`/именованный
стек (параллельная нить) — тогда `TextInput` молча не сработает без reply. Шаблон вложенные wizard'ы
в не-дефолтный стек не показывает, так что на типовом пути это не выстрелит — но и предупреждения нет.

**workaround:** держать wizard в дефолтном стеке (как все reference-фичи) — тогда ок.

---

## REQUIRED_CHANGES (чтобы wizard стал чистым)

1. **Reference-wizard как фича шаблона (или scaffold-образец).** Добавить хотя бы один многошаговый
   флоу (3-4 окна), демонстрирующий: запись/чтение `dialog_data` между шагами (с
   `model_dump(mode="json")` для не-примитива), `Multiselect`/`Select` + чтение `find().get_checked()`
   в финальном getter, валидируемый `TextInput(type_factory=int)`, условный `switch_to` из handler по
   собранным данным, финальный submit (usecase собирает весь черновик). Это закрывает HIGH-1, HIGH-2,
   MEDIUM-ветвление одним рабочим образцом. Иначе шаблон молчит ровно про то, под что заказчик его
   берёт. *(Альтернатива форвард-онли: пометить wizard как «вне reference, см. `aiogram-dialog-docs/`»
   — но тогда «нормальных ботов с анкетами» строить по шаблону, а не по доке библиотеки, не выйдет.)*

2. **Конвенция «черновик wizard'а» в rule `storage-serialization` / `dialog-deep-dive`.** Явно:
   widget-состояние (выбор/ввод) читай через `find()` в финальном getter; вычисленное/доменное —
   в `dialog_data` через `model_dump(mode="json")`; не клади доменную сущность, храни id +
   перезагружай. Сейчас правило говорит «только JSON», но не «вот так несут черновик через 10 шагов».

3. **TTL на storage (PR в tgbotkit).** `build_storage` пробрасывает `state_ttl`/`data_ttl` из env
   `BOT_STATE_TTL`/`BOT_DATA_TTL` (default ~30 дней) — иначе брошенные черновики wizard'ов копятся в
   Redis вечно, и state-migration на wizard'е неисполнима (см. `d-state.md` HIGH/MEDIUM, тот же fix).

4. **Образец условной навигации.** В `scaffold/references/window.md` / `dialog-deep-dive` — паттерн
   «ветка wizard'а»: решение о целевом State — в `policy` (по собранным данным), `switch_to(target)`
   в handler; явно предупредить, что `Next/Back` нецикличны и завязаны на порядок окон (для линейных
   визардов ок, для ветвящихся — `switch_to`).

5. **error-UX, возвращающий в корень.** `AppErrorUX.on_unknown_state` (`errors.py:22`) только гасит
   часики тостом, не сбрасывает стек. Для длинного wizard'а после сломавшего деплоя юзер залипает в
   петле тостов на старой кнопке до ручного `/start` (`d-state.md` LOW). Опционально: сброс в корень
   через `BgManager` (как в `building-a-template.md` §5).

---

## FINDINGS

- **[SEV=high | CAT=state | CONF=high | KEY=yes] Нет конвенции/образца переноса промежуточного
  состояния между шагами wizard'а.** `ProfileDialogData` (`profile/state.py:16`) мёртв, ни одной
  записи в `dialog_data`/`widget_data`/`start_data` во всём `src/` (grep пуст). Механика даёт два
  хранилища с разной семантикой (`reference/04` §2, `reference/19` §7) и лимитом «только JSON»
  (`Data=dict|list|int|str|float|None`) — шаблон не показывает ни одного. fix: reference-wizard с
  живым `dialog_data`/`find()`-сбором + конвенция в `storage-serialization`.

- **[SEV=high | CAT=dx | CONF=high | KEY=yes] Динамические виджеты (Multiselect/ScrollingGroup/
  Pager/Counter/MessageInput) — ноль образцов в шаблоне.** grep по `src/` пуст; импортируются только
  статические kbd + один `TextInput`. Каждый виджет несёт граблю (`ScrollingGroup(height=0)`→
  ZeroDivision `reference/15` §8.1; callback ≤64б `reference/11` §11.2; id-паттерн §8), не снятую
  примером. fix: добавить wizard-фичу с пагинируемым списком + мульти-селектом как reference.

- **[SEV=medium | CAT=state | CONF=high | KEY=no] Брошенный черновик wizard'а живёт в Redis вечно
  (нет TTL).** `build_storage` без `state_ttl`/`data_ttl` (`d-state.md` HIGH). Wizard — самый
  бросаемый флоу; недозаполненные `widget_data`+`dialog_data` копятся бесконечно в общем с кэшем
  Redis; state-migration на wizard-State неисполнима без TTL. fix: TTL из env — PR в tgbotkit.

- **[SEV=medium | CAT=architecture | CONF=high | KEY=no] Условное ветвление флоу не показано;
  `Next/Back` нецикличны и завязаны на порядок окон.** `next/back` → `ValueError` на краях,
  порядок = порядок `Window` в `Dialog` (`reference/05` §1, §12.3). В шаблоне навигация только
  безусловная (`SwitchTo`/`Cancel`/`Start`), условного `switch_to` из handler по данным — нет
  (grep `next()|.back()|find(` пуст). fix: паттерн «ветка wizard'а» (решение в `policy` → `switch_to`)
  в scaffold/dialog-deep-dive.

- **[SEV=low | CAT=correctness | CONF=high | KEY=no] Текстовый ввод wizard'а в не-дефолтном стеке
  требует reply; один input-слот на окно.** `reference/16` §7.1, §5. На типовом пути (вложенный
  диалог в дефолтном стеке, как все reference-фичи) не выстрелит; всплывёт при `NEW_STACK`. fix:
  держать wizard в дефолтном стеке; предупредить в доке про не-дефолтный.

- **[SEV=info | CAT=architecture | CONF=high | KEY=no] Гексагон-структура НЕ разваливается на
  большом флоу — это сильная сторона.** Логика шагов раскладывается чисто: валидация → `policy`
  (`profile/policy.py:18`, `Decision`), оркестрация → `usecase`, окна → разметка, +окно аддитивно
  (`scaffold/window.md`). import-linter держит слои на 10 окнах так же, как на 2. Свободная
  back-навигация (`switch_to`/`Back`) сохраняет `widget_data` бесплатно (`reference/05` §1).
  Валидация ввода имеет рабочий образец (`profile` `TextInput`+`on_error`+policy). Где живёт логика
  шагов — ответ верный (policy/usecase, не presentation).
