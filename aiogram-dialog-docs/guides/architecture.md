---
title: "Архитектура aiogram_dialog"
description: "Связный обзор архитектуры aiogram_dialog: как Dialog/Window/Widget/State/Context/Stack/Manager собираются в единую систему, жизненный цикл апдейта, модель данных, навигация, foreground/background и рендеринг сообщений."
source_repo: "aiogram_dialog (develop @ 08abdf0, 2026-05-02)"
aiogram_min: ">=3.14.0"
based_on:
  - reference/01-setup-registration.md
  - reference/02-dialog-manager.md
  - reference/03-window-dialog.md
  - reference/04-context-intent-storage-stack.md
  - reference/05-transitions-states.md
  - reference/06-bgmanager-updates.md
  - reference/07-message-manager-media.md
  - reference/19-common-custom-data.md
status: guide
---

# Архитектура aiogram_dialog

Этот документ — **обзорный нарратив**. Он соединяет в одну картину то, что в
референсах (`reference/01`–`reference/07`, `reference/19`) разложено по отдельным
зонам: классы, протоколы, middleware, хранилище, рендер. Здесь нет таблиц
параметров — за ними идите в соответствующую главу `reference/`. Здесь —
**как всё это работает вместе** и **почему так устроено**.

Ключевая идея библиотеки в одном предложении: `aiogram_dialog` — это
**слой над aiogram FSM**, который превращает «состояние пользователя» из плоского
`State` в **стек открытых экранов с собственными данными**, маршрутизирует входящие
апдейты к нужному экрану, рендерит этот экран в одно сообщение Telegram и держит
это сообщение «живым» (редактирует/пересоздаёт), пока экран не сменится.

---

## 1. Ментальная модель: что есть что

Семь сущностей, из которых собран весь фреймворк. Их полезно держать в голове
парами «декларация ↔ рантайм».

- **Dialog** — *декларация*. Контейнер окон, привязанный к одной `StatesGroup`.
  Технически `Dialog` **является aiogram `Router`** (`class Dialog(Router, DialogProtocol)`,
  `dialog.py:36`), поэтому регистрируется обычным `include_router`. Подробнее —
  [reference/03 §2](../reference/03-window-dialog.md), [reference/01 §3](../reference/01-setup-registration.md).
- **Window** — *декларация*. Один экран = одно `State` FSM. Описывает, **что** рендерить
  (текст/клавиатура/медиа/link preview) и как реагировать на ввод. `Window` собирает
  разнородные виджеты по «слотам» через `ensure_widgets` (`widgets/utils.py:97`).
  Подробнее — [reference/03 §1](../reference/03-window-dialog.md).
- **Widget** — *декларация*. Кирпичики окна: `Text`, `Keyboard`, `Input`, `Media`,
  `LinkPreview`. Каждый умеет `render_*` (нарисовать себя из данных) и/или
  `process_*` (обработать клик/сообщение). Stateful-виджеты (`Checkbox`, `Counter`,
  `Select`…) хранят своё состояние в `Context.widget_data`. Подробнее —
  [reference/19](../reference/19-common-custom-data.md).
- **State** — *идентификатор*. Обычный `aiogram.fsm.state.State`. В мире
  `aiogram_dialog` он адресует конкретное **окно** внутри диалога. Группа состояний
  (`StatesGroup`) адресует **диалог**: одна `StatesGroup` ⇄ ровно один `Dialog`.
- **Context** — *рантайм-состояние одного экземпляра диалога*. «Локальные переменные»
  одного запуска: `state` (какое окно открыто), `start_data` (вход), `dialog_data`
  (рабочие данные), `widget_data` (состояния виджетов), `access_settings`. Каждый
  `start` рождает новый `Context` с уникальным `intent_id`. Подробнее —
  [reference/04 §2](../reference/04-context-intent-storage-stack.md).
- **Stack** — *рантайм-структура навигации*. Список `intents: list[str]` — стек
  открытых диалогов в одном «канале». Верхний элемент — активный диалог. Стек также
  хранит метаданные последнего отрисованного сообщения (`last_message_id`, `last_media_id`…),
  потому что **одно сообщение приходится на стек, а не на контекст**. Подробнее —
  [reference/04 §3](../reference/04-context-intent-storage-stack.md).
- **Manager** (`DialogManager`) — *фасад/драйвер*. Единственный объект, через который
  хендлер и виджеты управляют всем: `start/done/switch_to/next/back/update/show`, чтение
  `dialog_data`/`current_context()`, `find(id)`. Живёт ровно один апдейт. Подробнее —
  [reference/02](../reference/02-dialog-manager.md).

### Схема иерархии

```
StatesGroup  (один к одному)  Dialog ── Router ── include_router(dp)
   │                            │
   │ State (на окно)            ├── Window (state=A)
   ▼                            │     ├── Text widgets      → render_text → str
 Window                         │     ├── Keyboard widgets  → render_keyboard → RawKeyboard
                                │     ├── Input widgets      → process_message
                                │     ├── Media (max 1)      → render_media
                                │     └── LinkPreview (max 1)
                                ├── Window (state=B)
                                └── Window (state=C)

РАНТАЙМ (хранится в FSM storage, адресуется по chat/user/thread):

  Stack(_id)                         «канал» навигации
    intents = [ intent_1, intent_2, intent_3 ]   ← верхний = активный
                 │          │          │
                 ▼          ▼          ▼
            Context     Context     Context        по одному на открытый диалог
            { state,    { ... }     { ... }
              start_data,
              dialog_data,
              widget_data,
              access_settings }

  DialogManager  ── обёртка вокруг текущего (Stack, Context, StorageProxy)
                    создаётся на каждый апдейт, в конце close_manager()
```

Связь «декларация ↔ рантайм»: `Dialog`/`Window`/`Widget` — это **неизменяемые
объекты-описания**, создаваемые один раз при старте бота. `Context`/`Stack` — это
**данные пользователя**, которые живут в FSM storage и пересоздаются/мутируются на
каждом апдейте. `DialogManager` — мост между ними на время обработки одного апдейта.

---

## 2. Жизненный цикл апдейта (request lifecycle)

Это центральный раздел. Понимание порядка middleware объясняет почти все «магические»
свойства библиотеки: почему `dialog_manager` иногда не инжектится, где сохраняются
изменения `dialog_data`, почему «протухшие» кнопки не валят бота.

Вся цепочка навешивается в `_register_middleware` (`setup.py:103`). aiogram различает
**outer**-middleware (на «сырое» событие, до фильтров) и **inner**-middleware (после
фильтров, ближе к хендлеру). Порядок навешивания (для каждого из observers `message`,
`business_message`, `callback_query`, `aiogd_update`, `my_chat_member`,
`chat_join_request`):

```
outer:  intent_middleware.process_*     ← грузит Stack+Context, берёт lock, кладёт STORAGE_KEY
outer:  context_unlocker_middleware     ← finally: снимает lock стека
outer:  BgFactoryMiddleware             ← кладёт dialog_bg_factory (на ВСЕ observers)
inner:  manager_middleware              ← создаёт DialogManager (если STORAGE_KEY есть)
inner:  context_saver_middleware        ← после handler: сохраняет Context+Stack
        [ фильтры окон: IntentFilter ]
        [ хендлер: Dialog._callback_handler / _message_handler ]
```

Пошагово, на примере нажатия inline-кнопки (`callback_query`):

1. **intent_middleware** (`intent_middleware.py:392`, см.
   [reference/01 §5.3](../reference/01-setup-registration.md),
   [reference/04 §7](../reference/04-context-intent-storage-stack.md)):
   - строит `EventContext` (chat/user/thread/business) и кладёт его в
     `data[EVENT_CONTEXT_KEY]`;
   - вынимает `intent_id` из callback_data (`remove_intent_id`, `utils.py:220`); чистый
     payload без служебного префикса кладётся в `CALLBACK_DATA_KEY`;
   - создаёт `StorageProxy` и через него **грузит** контекст по `intent_id`
     (`_load_context_by_intent`) либо дефолтный стек (`_load_default_context`,
     `DEFAULT_STACK_ID = ""`);
   - **берёт lock на ключ стека** (`load_stack` → `events_isolation.lock`,
     `storage.py:74`) — отсюда сериализация параллельных апдейтов одного стека;
   - проверяет `_check_outdated` (intent совпадает с верхушкой стека?) и
     `access_validator.is_allowed`;
   - при успехе кладёт в `data`: `STORAGE_KEY`, `STACK_KEY`, `CONTEXT_KEY`. При запрете —
     ставит `FORBIDDEN_STACK_KEY`, снимает lock и `STORAGE_KEY` **не** кладёт.
2. **context_unlocker_middleware** (`intent_middleware.py:446`): оборачивает остаток в
   try/finally — гарантирует `proxy.unlock()`, даже если хендлер упал.
3. **BgFactoryMiddleware** (`manager_middleware.py:62`): кладёт `dialog_bg_factory`
   в data, чтобы фоновые старты были доступны из любого хендлера.
4. **manager_middleware** (`manager_middleware.py:37`): **только если `STORAGE_KEY in data`**
   создаёт `DialogManager` через фабрику (`DefaultManagerFactory` → `ManagerImpl`) и кладёт
   в `data["dialog_manager"]`. В `finally` зовёт `close_manager()`.
   > **Ключевой инвариант:** `dialog_manager` инжектится **тогда и только тогда**, когда
   > intent-middleware успешно загрузил контекст и доступ разрешён. На «чужих»/запрещённых
   > апдейтах менеджера в хендлере нет. См. [reference/01 §5.3](../reference/01-setup-registration.md).
5. **Фильтры окон** (`IntentFilter`, `intent_filter.py`): пропускают событие к хендлерам
   диалога, **только если** `context.state.group` совпадает с `StatesGroup` этого диалога.
   Так событие маршрутизируется в нужный `Dialog` по активному состоянию.
6. **Хендлер диалога** (`Dialog._callback_handler`, `dialog.py:141`): срезает intent_id,
   зовёт `window.process_callback(...)`, который дёргает каждый виджет дерева
   (`process_callback` → `True`, если «моё»). Виджет вызывает `on_click`, который, в свою
   очередь, может позвать `manager.switch_to/next/done/...`. После — `_need_refresh` решает,
   нужен ли `show()`, и всегда `answer_callback()`.
7. **Рендер** (если был `show()`): `Dialog.render` → `Window.render` собирает данные через
   getter-цепочку и строит `NewMessage`. Подробно — §4 и §7.
8. **MessageManager** (`message_manager.py:168`): получает `NewMessage` + восстановленный из
   стека `OldMessage` и решает send/edit/delete. Подробно — §7.
9. **context_saver_middleware** (`intent_middleware.py:437`): **после** хендлера достаёт
   `STORAGE_KEY` и сохраняет `Context` (`save_context`) и `Stack` (`save_stack`). Именно здесь
   мутации `dialog_data`/`widget_data`/`state`, сделанные в хендлере и виджетах, попадают в
   storage. Нет `STORAGE_KEY` → ничего не сохраняется.
10. **context_unlocker** в finally снимает lock стека.

```
Update ──► [intent] load Stack+Context, lock ──► [unlocker] ──► [bg_factory]
              │ кладёт STORAGE/STACK/CONTEXT_KEY
              ▼
           [manager] new DialogManager  ──► [saver(после)]
              ▼
           IntentFilter ──► Dialog handler ──► widget.process_* ──► on_click
              │                                                        │
              │                                              manager.switch_to/next/done
              ▼                                                        ▼
           Dialog.render ──► Window.render ──► NewMessage ──► MessageManager.show_message
              ▲                                                        │ send/edit/delete
              └──────────────── show() ◄───────────────────────────────┘
           ───► [saver] save Context+Stack ──► [unlocker] unlock
```

Этот же конвейер обслуживает и фоновые апдейты — через шестой observer `aiogd_update`
(см. §6).

---

## 3. Модель данных и хранилище

Чтобы не путать пять разных «данных», держите в голове, **где** каждое живёт и **на какой
срок**.

| Сущность | Где лежит | Срок жизни | Кто пишет/читает |
|---|---|---|---|
| `Stack.intents` | `aiogd:stack:<stack_id>` | пока не очищен (`done`/`reset`) | `start`/`done`/`reset_stack` |
| `Context` целиком | `aiogd:context:<intent_id>` | от `start` до `done` диалога | менеджер автоматически |
| `start_data` | внутри `Context` | вся жизнь диалога | вход в `start(data=...)`, read-only по смыслу |
| `dialog_data` | внутри `Context` | вся жизнь диалога | мутабельно: `manager.dialog_data[...]`, `manager.update(...)` |
| `widget_data` | внутри `Context`, по `widget_id` | вся жизнь диалога | stateful-виджеты (`get/set_widget_data`) |

Все эти данные сериализуются в **aiogram FSM storage** через `StorageProxy`
(`context/storage.py`). Два логических ключа:

```
StorageKey(destiny="aiogd:stack:<stack_id>")    → Stack  { intents:[...], last_message_id, ... }
StorageKey(destiny="aiogd:context:<intent_id>") → Context{ state, start_data, dialog_data, widget_data, access_settings }
```

Здесь два важных нюанса реализации (см. [reference/04 §5](../reference/04-context-intent-storage-stack.md)):

- **`user_id` в `StorageKey` подменяется на `chat_id`.** Реальная идентификация закодирована
  в `destiny`. Это сделано намеренно: в групповом чате контекст/стек не должен быть привязан к
  конкретному `user_id` на уровне FSM-ключа; разделение по пользователям — логическое, через
  `stack_id` и `access_settings`.
- **Дефолтный стек в группе становится персональным.** `_fixed_stack_id` (`storage.py:140`):
  в личке `""` остаётся `""`, а в группе/бизнес-чате превращается в `"<user_id>"`. Поэтому в
  группе каждый по умолчанию работает в своём изолированном стеке.

**`intent_id` — сквозной идентификатор экземпляра диалога.** Он не только адресует контекст в
storage, но и **вшивается в callback_data каждой inline-кнопки** окна (`add_intent_id`,
`utils.py:211`, разделитель `CB_SEP="\x1D"`). Когда приходит callback, middleware грузит контекст
по этому `intent_id` и сверяет с верхушкой стека (`_check_outdated`). Клик по кнопке старого,
уже закрытого экрана даёт `OutdatedIntent`, и `IntentErrorMiddleware` тихо чинит стек, а не
роняет бота. См. [reference/04 §4](../reference/04-context-intent-storage-stack.md).

### Что обязано быть JSON-сериализуемым

Тип-контракт — `Data = dict | list | int | str | float | None` (`context.py:7`). Всё, что вы
кладёте в **`dialog_data`, `widget_data`, `start_data` и `result` из `done()`**, должно
сериализоваться вашим backend'ом. На JSON/Redis-backend `datetime`/`Decimal`/`set`/pydantic-модель/
ORM-объект упадут с `TypeError` **при сохранении** (то есть уже после ответа пользователю).
`MemoryStorage` из aiogram это маскирует (хранит python-объекты в RAM) — и взрывается при переезде
на персистентный storage. **Кладите ISO-строки/числа/простые dict.** См.
[reference/04 §8 и §16](../reference/04-context-intent-storage-stack.md).

---

## 4. Поток данных в рендер (getter pipeline)

Когда нужно нарисовать окно, библиотека собирает **один плоский словарь** `data` и прогоняет его
через все `render_text`/`render_keyboard`/`render_media`. Этот словарь собирается тремя слоями,
**снизу вверх**, где каждый следующий `dict.update` перекрывает предыдущий при коллизии ключей.

```
manager.load_data()              manager.py:130   — СИСТЕМНЫЙ слой
  { dialog_data, start_data, middleware_data, event, **global_getter(...) }
        │ data.update(dialog.getter(**middleware_data))
        ▼
dialog.load_data(manager)        dialog.py:115    — слой ДИАЛОГА (общее для всех окон)
        │ data.update(window.getter(**middleware_data))
        ▼
window.load_data(dialog, manager)  window.py:113  — слой ОКНА (конкретный экран)
        ▼
   итоговый data → render_text / render_keyboard / render_media / when-предикаты
```

**Приоритет при конфликте ключей (поздний побеждает):**

```
manager.load_data()  <  global getter (setup_dialogs)  <  Dialog.getter  <  Window.getter
```

Системный слой (`manager.load_data`, [reference/02 §2](../reference/02-dialog-manager.md),
[reference/19 §9](../reference/19-common-custom-data.md)) всегда кладёт четыре зарезервированных
ключа: `dialog_data`, `start_data`, `middleware_data`, `event`. Глобальный getter из
`setup_dialogs(getter=...)` подмешивается в этот же слой.

Тонкости, которые стоит запомнить:

- **Все getter-ы вызываются с `**manager.middleware_data`, а не с собранным `data`.** Внутри
  getter доступны `dialog_manager`, `event_chat`, `event_from_user`, `bot` и любые ваши
  middleware-ключи — но не результаты других getter-ов. Канонический вид:
  `async def getter(dialog_manager, **kwargs) -> dict`. **Обязательно оставляйте `**kwargs`** —
  иначе новый ключ в middleware уронит getter с `TypeError`.
- **Можно затереть системные ключи.** Window-getter имеет высший приоритет; getter, вернувший
  ключ `event` или `dialog_data`, перетрёт системный. Не называйте поля getter-а зарезервированными
  именами.
- **`getter=` принимает не только функцию**, но и готовый `dict` (статика), и список/кортеж
  getter-ов (мердж по порядку, `CompositeGetter`). См.
  [reference/19 §9](../reference/19-common-custom-data.md).
- **`preview_data` / `PreviewAwareGetter`:** в режиме генерации превью (`manager.is_preview()`)
  вместо боевого getter вызывается `preview_data`. В рантайме `is_preview()` всегда `False`.
- **В обработчиках (`on_click`/`on_message`) собранного словаря НЕТ** — данные там берут из
  `manager.dialog_data` / `manager.start_data` / `manager.middleware_data`.

Дальше итоговый `data` доходит до виджетов: `Text.render_text(data, manager) → str`,
`Keyboard.render_keyboard(data, manager) → RawKeyboard`, `Media.render_media → MediaAttachment`.
Здесь же работает `when`: скрытый текст возвращает `""`, скрытая клавиатура — пустой ряд (см.
[reference/19 §4](../reference/19-common-custom-data.md)).

---

## 5. Навигация и стеки

Все переходы делятся на **две оси**: внутри одного диалога (меняем `state`) и между диалогами
(меняем стек). Это разные механизмы с разными гарантиями.

### Ось 1 — внутри диалога (тот же Context)

`switch_to(state)` / `next()` / `back()` (`manager.py:355/327/341`). Меняют только
`context.state`, **не трогают стек и не пересоздают Context** — все `dialog_data`/`widget_data`
сохраняются. Ограничения:

- `switch_to` только внутри своей `StatesGroup` (иначе `ValueError`) — между диалогами это уже
  `start`/`done`.
- `next`/`back` ходят по `dialog.states()` (порядок = порядок `Window` в `Dialog`), **не
  цикличны**: на краях — `ValueError`.
- `switch_to` **сам не вызывает `show()`** — перерисовку обеспечивает обёртка (хендлер клика
  через `_need_refresh`, либо `update_handler` для фона). См.
  [reference/05 §1](../reference/05-transitions-states.md).

Кнопки `SwitchTo`/`Next`/`Back` — тонкие обёртки над этими методами.

### Ось 2 — между диалогами (стек Context'ов)

- **`start(state, data, mode)`** (`manager.py:241`) — кладёт новый диалог в стек:
  `stack.push` создаёт новый `Context` с новым `intent_id`, дочерний получает `data` как
  `start_data` и **свою пустую** `dialog_data`. К родительскому контексту доступа нет.
- **`done(result)`** (`manager.py:196`) — закрывает верхний диалог: `on_close` → `mark_closed`
  (pop + удаление контекста из storage) → если стек не пуст, нижележащий диалог ловит результат
  в `on_process_result(child_start_data, result, manager)`.

Так строятся **вложенные диалоги (sub-dialogs)**: вложенность здесь — это не дерево виджетов, а
стек. Общение строго через `start_data` (вниз) и `result` (вверх). См.
[reference/05 §3, §7](../reference/05-transitions-states.md),
[reference/03 §4](../reference/03-window-dialog.md).

### Три «модификатора», которые легко перепутать

- **`StartMode`** (параметр `start`, [reference/05 §2](../reference/05-transitions-states.md)):
  `NORMAL` (поверх стека), `RESET_STACK` (очистить стек, затем старт — типично для `/start`),
  `NEW_STACK` (создать **отдельный** стек и стартовать в нём через background-менеджер).
- **`LaunchMode`** (свойство `Dialog`, [reference/03 §3](../reference/03-window-dialog.md),
  [reference/05 §4](../reference/05-transitions-states.md)): политика диалога **при его старте**.
  `STANDARD` (без ограничений), `ROOT` (всегда корень, сбрасывает стек), `EXCLUSIVE` (единственный
  в стеке, поверх него старт запрещён → `ValueError`), `SINGLE_TOP` (не дублируется на вершине —
  повторный старт заменяет себя).
- **`ShowMode`** (параметр почти всех переходов, [reference/05 §5](../reference/05-transitions-states.md)):
  как обновить сообщение — `AUTO`/`EDIT`/`SEND`/`DELETE_AND_SEND`/`NO_UPDATE`. Это про рендер,
  а не про навигацию; действует на **ближайший** show и «сбрасывается» (за счёт пересоздания
  менеджера на следующий апдейт).

Запомнить просто: `StartMode` — *как лечь в стек*, `LaunchMode` — *как этот диалог себя ведёт в
стеке вообще*, `ShowMode` — *как нарисовать результат*.

### Диаграмма состояний стека

```
            start(NORMAL)             start(NORMAL)
   [ A ] ───────────────► [ A, B ] ──────────────► [ A, B, C ]
     ▲                       ▲   │                       │
     │ done()                │   │ done(result)          │ done()
     │                       └───┴───────────────────────┘
     │
  пустой стек ── start(RESET_STACK | LaunchMode.ROOT/EXCLUSIVE) ──► [ X ]
                                                  (старый стек стёрт молча, без on_close)

  start(NEW_STACK) ──► создаётся независимый Stack(_id=random),
                       старт идёт через BgManager (см. §6)

  start(LaunchMode.SINGLE_TOP) того же диалога на вершине:
   [ A, P ] ──► [ A, P ]   (верхний P снят и заменён свежим, без накопления)
```

Лимит стека — 100 (`_STACK_LIMIT`), переполнение → `DialogStackOverflow`. Поэтому для «корневых»
меню используют `RESET_STACK`/`ROOT`, иначе повторные `start` копят контексты и текут память
storage. См. [reference/04 §11](../reference/04-context-intent-storage-stack.md),
[reference/05 §12](../reference/05-transitions-states.md).

---

## 6. Foreground vs Background

Внутри хендлера у вас есть **полноценный** `DialogManager` (реализация `ManagerImpl`), привязанный
к текущему апдейту. Он живёт ровно один апдейт: `ManagerMiddleware` создаёт его на входе и в
`finally` зовёт `close_manager()`, обнуляя `_data`/`_event` (`manager.py:621`). Любое обращение к
нему из фоновой задачи после завершения хендлера → `IncorrectBackgroundError`. См.
[reference/02 §6](../reference/02-dialog-manager.md).

Для всего, что **снаружи** хендлера (фоновая `asyncio.Task`, webhook платёжки, брокер, действие
для **другого** чата/пользователя), нет «текущего апдейта» — и нужен **`BgManager`**
(`bg_manager.py:73`). Он реализует узкий протокол `BaseDialogManager`
(`start/done/switch_to/update/bg/fg`) и **ничего не делает синхронно**: каждый метод формирует
искусственный апдейт `DialogUpdate(aiogd_update=DialogUpdateEvent)` и через `Updater.notify`
ставит его в loop. См. [reference/06](../reference/06-bgmanager-updates.md).

### Как фоновый апдейт доезжает (DIALOG_EVENT_NAME)

```
BgManager.start/done/switch_to/update
        │ формирует DialogUpdate(aiogd_update=...)   event_type == "aiogd_update"
        ▼
Updater.notify  ── loop.call_soon ──► dp.propagate_event(update)   (на следующей итерации loop)
        ▼
observer router.observers["aiogd_update"]   (зарегистрирован в setup_dialogs)
        ▼
та же middleware-цепочка (intent → manager → ...) поднимает ПОЛНОЦЕННЫЙ DialogManager
        ▼
handle_update (update_handler.py:16)  ── мапит DialogAction → методы менеджера:
   START → start ;  DONE → done ;  SWITCH → switch_to+show ;  UPDATE → dialog_data+show ;  FG → fg
        ▼
обычный рендер → MessageManager.show_message
```

`DIALOG_EVENT_NAME = "aiogd_update"` (`update_event.py:20`). Observer и `handle_update`
регистрируются в `setup_dialogs` (`setup.py:39-47`). Корень роутера обязан быть `Dispatcher`,
иначе `Updater` бросит `TypeError("Root router must be Dispatcher.")`.

Три реализации менеджера и когда какой:

- **`ManagerImpl`** (foreground) — внутри хендлера, синхронный, прямой доступ к стеку и контексту.
- **`BgManager`** (background) — снаружи хендлера, асинхронный через очередь событий. Получается
  через `manager.bg(...)` (bot известен) или `BgManagerFactory.bg(bot, ...)` (bot обязателен;
  фабрику возвращает `setup_dialogs` и она же лежит в `data["dialog_bg_factory"]`).
- **`SubManager`** (`sub_manager.py:26`) — обёртка для строк `ListGroup`: почти всё делегирует
  родителю, но подменяет `dialog_data`/`current_context()` на данные **конкретной строки**
  (`widget_data[widget_id][item_id]`). Поэтому `SubManager.dialog_data` ≠ общий `dialog_data`
  диалога; для общего — `find_in_parent` или родитель.

Чтобы из фона получить **полноценный** менеджер (с доступом к `dialog_data`), есть `fg()`:
`async with bg_manager.fg() as manager:` эмитит `DialogFgEvent`, дожидается, пока обработчик
поднимет реальный `DialogManager`, и отдаёт его в `with`. Пока вы внутри `with`, стек заблокирован
на вас — держите тело коротким. См. [reference/06 §6](../reference/06-bgmanager-updates.md).

Два следствия, важных для прода:

- **Обычные middleware не видят фоновые апдейты.** `aiogd_update` — кастомное событие; чтобы ваша
  auth/i18n/throttling-middleware сработала на фоновом рендере, навесьте её на
  `dispatcher.observers[DIALOG_EVENT_NAME]`.
- **`BgManager` не валидирует адресацию.** Неверные `user_id`/`chat_id`/`stack_id` дают тихий
  промах: для `UPDATE` без контекста `handle_update` только пишет `warning("No context found")`.
  Для чужого чата `stack_id` по умолчанию `""` — это **другой** стек, чем у текущего юзера.

---

## 7. Рендеринг сообщений

Рендер — это превращение декларации окна в одно сообщение Telegram и поддержание его «живым».
Цепочка: `DialogManager.show()` → `Dialog.render` → `Window.render` → `NewMessage` →
`MessageManager.show_message`.

### Сборка NewMessage

`Window.render` (`window.py:147`, [reference/03 §1.4](../reference/03-window-dialog.md)):
собирает `data` через getter-pipeline (§4), рендерит текст/клавиатуру/медиа/link preview и
конструирует `NewMessage` (`new_message.py:41`) — датакласс «что хотим показать»: chat,
thread_id, business_connection_id, text, reply_markup, parse_mode, protect_content, media,
link_preview_options. Окно **не** проставляет `show_mode` — это делает `DialogManager.show()`
непосредственно перед отправкой (`manager.py:390`), вычисляя `AUTO` через `_calc_show_mode`.

### Решение send / edit / delete

`MessageManager.show_message` (`message_manager.py:168`,
[reference/07 §3](../reference/07-message-manager-media.md)) получает `NewMessage` (с уже
конкретным `show_mode`, не `AUTO`) и `OldMessage | None` — лёгкий снимок того, что сейчас на
экране, **восстановленный из полей `Stack`** (`last_message_id`, `last_media_id`,
`content_type`…). Дерево решений по порядку:

```
1. show_mode == NO_UPDATE                  → MessageNotModified (ничего не делаем)
2. old есть И show_mode == DELETE_AND_SEND → удалить старое + послать новое
                                             (порядок оптимизирован «чтобы не моргало»)
3. old нет ИЛИ show_mode == SEND           → снять старую клавиатуру + послать новое
4. _message_changed() == False             → ничего не трогаем, вернуть old
5. _can_edit() == False                    → удалить + послать заново
6. иначе                                   → edit_message_safe (edit_text/caption/media)
```

`_message_changed` — приблизительный дифф (текст, наличие любой клавиатуры, link preview,
protect_content, медиа). `_can_edit` запрещает редактирование, если появилось/исчезло медиа,
есть voice или есть/нужна reply-клавиатура — такие случаи всегда идут через delete+send.
`edit_message_safe` при `"message can't be edited"`/`"message to edit not found"` делает
**fallback на send**. Отсюда важный вывод: **`EDIT` — это намерение, а не гарантия**; при
отсутствии старого сообщения или отказе Telegram он фактически пошлёт новое.

### `_calc_show_mode` (логика AUTO)

```
show_mode != AUTO              → как есть
event_chat.type != PRIVATE     → EDIT
last_reply_keyboard            → DELETE_AND_SEND
stack.id != DEFAULT_STACK_ID   → EDIT
event — Message, нет media_group        → SEND
event — Message, та же media_group      → EDIT
иначе (callback / фоновое событие)      → EDIT
```

Практический итог: на **сообщение** пользователя бот по умолчанию шлёт новое (`SEND`), на
**нажатие кнопки** — редактирует (`EDIT`). Подробнее —
[reference/05 §5](../reference/05-transitions-states.md),
[reference/06 §9](../reference/06-bgmanager-updates.md).

### Кеш медиа

Чтобы не перезаливать один и тот же файл, `MediaIdStorage` (`media_storage.py:16`, LRU на 10240)
кеширует `file_id` по ключу `(path, url, type)`. **Перед** показом `_fix_cached_media_id`
подставляет кешированный `file_id` в `MediaAttachment`, если его нет; **после** показа сохраняет
выданный Telegram `file_id`. Сравнение медиа в диффе идёт по `file_unique_id`, когда он известен
(`MediaId.__eq__`), потому что `file_id` у Telegram нестабилен между чатами — **всегда сохраняйте
оба id**. Для `path` кеш инвалидируется по `mtime` файла; для `url` — бессрочен. См.
[reference/07 §4, §8](../reference/07-message-manager-media.md).

`MessageManager` и `MediaIdStorage` целиком подменяются через
`setup_dialogs(message_manager=..., media_id_storage=...)` — это штатная точка для ретраев,
троттлинга (`TelegramRetryAfter`) и кастомных источников медиа (`get_media_source`). При этом
**нельзя глушить `MessageNotModified`** в обёртке — ядро строит на нём логику «не сохранять id».

---

## 8. Карта модулей

Краткий справочник «куда смотреть». Все пути относительно
`src/aiogram_dialog/`.

| Модуль / пакет | За что отвечает | Reference |
|---|---|---|
| `setup.py` | `setup_dialogs`, `DialogRegistry`, регистрация middleware и observer `aiogd_update` | [01](../reference/01-setup-registration.md) |
| `dialog.py` | `Dialog` (он же `Router`): окна, фильтр, хендлеры, lifecycle-хуки | [03](../reference/03-window-dialog.md) |
| `window.py` | `Window`: сборка виджетов, `render` → `NewMessage` | [03](../reference/03-window-dialog.md) |
| `manager/manager.py` | `ManagerImpl` (foreground `DialogManager`): навигация, `show`, `load_data` | [02](../reference/02-dialog-manager.md) |
| `manager/bg_manager.py` | `BgManager` / `BgManagerFactoryImpl`: фоновые операции через события | [06](../reference/06-bgmanager-updates.md) |
| `manager/sub_manager.py` | `SubManager`: контекст строки `ListGroup` | [02](../reference/02-dialog-manager.md) |
| `manager/manager_middleware.py` | `ManagerMiddleware` (создание менеджера), `BgFactoryMiddleware` | [01](../reference/01-setup-registration.md) |
| `manager/manager_factory.py` | `DefaultManagerFactory` → собирает `ManagerImpl` на апдейт | [01](../reference/01-setup-registration.md) |
| `manager/update_handler.py` | `handle_update`: `DialogAction` → методы менеджера | [06](../reference/06-bgmanager-updates.md) |
| `manager/updater.py` | `Updater`: мост в `Dispatcher.propagate_event` для фоновых событий | [06](../reference/06-bgmanager-updates.md) |
| `manager/message_manager.py` | `MessageManager`: send/edit/delete, источники медиа | [07](../reference/07-message-manager-media.md) |
| `context/intent_middleware.py` | load/save/lock контекста, `IntentErrorMiddleware` | [01](../reference/01-setup-registration.md), [04](../reference/04-context-intent-storage-stack.md) |
| `context/intent_filter.py` | `IntentFilter`: маршрутизация апдейта в нужный диалог | [01](../reference/01-setup-registration.md), [04](../reference/04-context-intent-storage-stack.md) |
| `context/storage.py` | `StorageProxy`: ключи `aiogd:stack`/`aiogd:context`, lock, (де)сериализация | [04](../reference/04-context-intent-storage-stack.md) |
| `context/access_validator.py` | `DefaultAccessValidator`: доступ к стеку/контексту | [04](../reference/04-context-intent-storage-stack.md) |
| `context/media_storage.py` | `MediaIdStorage`: LRU-кеш `file_id` | [07](../reference/07-message-manager-media.md) |
| `api/entities/context.py` | `Context`, `Data`, `DataDict` | [04](../reference/04-context-intent-storage-stack.md) |
| `api/entities/stack.py` | `Stack`, `DEFAULT_STACK_ID`, `GROUP_STACK_ID`, генерация id | [04](../reference/04-context-intent-storage-stack.md) |
| `api/entities/modes.py` | `ShowMode`, `StartMode` | [05](../reference/05-transitions-states.md) |
| `api/entities/launch_mode.py` | `LaunchMode` | [03](../reference/03-window-dialog.md), [05](../reference/05-transitions-states.md) |
| `api/entities/new_message.py` | `NewMessage`, `OldMessage`, `UnknownText` | [07](../reference/07-message-manager-media.md) |
| `api/entities/update_event.py` | `DialogUpdate`, `DialogUpdateEvent`, `DialogAction`, `DIALOG_EVENT_NAME` | [06](../reference/06-bgmanager-updates.md) |
| `api/entities/events.py` | `ChatEvent`, `EventContext`, `EVENT_CONTEXT_KEY` | [02](../reference/02-dialog-manager.md), [04](../reference/04-context-intent-storage-stack.md) |
| `api/protocols/*` | контракты: `DialogManager`, `MessageManagerProtocol`, `DialogRegistryProtocol`, `StackAccessValidator`, `MediaIdStorageProtocol` | соответствующие зоны |
| `widgets/common/*` | `BaseWidget`, `Actionable`, `Whenable`, `ManagedWidget`, `Selector` | [19](../reference/19-common-custom-data.md) |
| `widgets/utils.py` | `ensure_widgets`, `ensure_data_getter`, `GetterVariant` | [03](../reference/03-window-dialog.md), [19](../reference/19-common-custom-data.md) |
| `widgets/data/data_context.py` | `CompositeGetter`, `StaticGetter`, `PreviewAwareGetter` | [03](../reference/03-window-dialog.md), [19](../reference/19-common-custom-data.md) |
| `widgets/widget_event.py` | `WidgetEventProcessor`, нормализация `on_click`/`on_*` | [19](../reference/19-common-custom-data.md) |
| `utils.py` | `intent_id` ↔ callback_data (`add_intent_id`/`remove_intent_id`), `get_media_id` | [04](../reference/04-context-intent-storage-stack.md), [07](../reference/07-message-manager-media.md) |
| `tools/preview.py`, `tools/transitions.py` | `FakeManager`/web-preview, граф переходов | [03](../reference/03-window-dialog.md), [05](../reference/05-transitions-states.md) |

---

## Резюме «сквозных» инвариантов

- **`dialog_manager` инжектится только при успешно загруженном контексте и разрешённом доступе**
  (`STORAGE_KEY in data`). В не-диалоговых/запрещённых сценариях его нет или контекст пуст —
  проверяйте `manager.has_context()`.
- **Изменения данных сохраняются `context_saver`-middleware после хендлера**, не сразу. Мутируйте
  `dialog_data` по месту или через `update()` — и не обращайтесь к менеджеру после завершения
  апдейта (он `disabled`).
- **Одно сообщение на стек.** `EDIT` — намерение, фактический результат решает `MessageManager` по
  состоянию старого сообщения.
- **Фоновые операции едут через `aiogd_update`** и тот же конвейер; адресация и обычные middleware
  здесь работают иначе, чем в foreground.
- **Только JSON-примитивы в `dialog_data`/`widget_data`/`start_data`/`result`**; персистентный
  storage и распределённый `events_isolation` — обязательны для прода с несколькими воркерами.
