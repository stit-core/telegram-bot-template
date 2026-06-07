---
Зона: "№02 — DialogManager: полный интерфейс и реализации"
Изученные файлы:
  Источники:
    - src/aiogram_dialog/api/protocols/manager.py        # протоколы BaseDialogManager / DialogManager / BgManagerFactory / UnsetId
    - src/aiogram_dialog/manager/manager.py              # ManagerImpl — основная реализация (foreground)
    - src/aiogram_dialog/manager/sub_manager.py          # SubManager — обёртка для ListGroup-строк
    - src/aiogram_dialog/manager/bg_manager.py           # BgManager / BgManagerFactoryImpl + coalesce_* хелперы
    - src/aiogram_dialog/api/internal/manager.py         # DialogManagerFactory (Protocol)
    - src/aiogram_dialog/api/entities/context.py         # Context, Data, DataDict
    - src/aiogram_dialog/api/entities/stack.py           # Stack, DEFAULT_STACK_ID, GROUP_STACK_ID, генераторы id
    - src/aiogram_dialog/api/entities/modes.py           # ShowMode, StartMode
    - src/aiogram_dialog/api/entities/launch_mode.py     # LaunchMode
    - src/aiogram_dialog/api/entities/access.py          # AccessSettings
    - src/aiogram_dialog/api/entities/events.py          # ChatEvent, EventContext, EVENT_CONTEXT_KEY
    - src/aiogram_dialog/api/entities/update_event.py    # DialogAction, DialogUpdateEvent и подклассы, DialogUpdate
    - src/aiogram_dialog/api/internal/middleware.py      # CONTEXT_KEY/STACK_KEY/STORAGE_KEY/EVENT_SIMULATED/CALLBACK_DATA_KEY
    - src/aiogram_dialog/api/internal/fake_data.py       # FakeUser, FakeChat, ReplyCallbackQuery
    - src/aiogram_dialog/manager/manager_middleware.py   # ManagerMiddleware / BgFactoryMiddleware
    - src/aiogram_dialog/manager/manager_factory.py      # DefaultManagerFactory
    - src/aiogram_dialog/manager/update_handler.py       # handle_update — диспетчеризация bg-событий
    - src/aiogram_dialog/manager/updater.py              # Updater — рассылка DialogUpdate
    - src/aiogram_dialog/api/protocols/dialog.py         # DialogProtocol (process_start/result/close, render, states)
    - src/aiogram_dialog/widgets/kbd/list_group.py       # где создаётся SubManager
    - src/aiogram_dialog/tools/preview.py                # FakeManager (is_preview == True)
  Доки/примеры/тесты:
    - docs/bg/index.rst, docs/transitions/index.rst (+ start.py/done.py/switch.py/startmode.py)
    - docs/how_are_messages_updated/index.rst (+ example.py)
    - docs/widgets/passing_data/index.rst (+ data_in_handlers.py)
    - docs/widgets/keyboard/list_group/index.rst
    - docs/widgets/text/progress/bg_manager_example.py
    - tests/test_fg.py, tests/test_click.py
Коммит: develop 08abdf0 (2026-05-02), aiogram >= 3.14.0
---

# Зона №02 — DialogManager: полный интерфейс и реализации

## 0. Обзор и иерархия

В aiogram_dialog есть **три уровня менеджеров** + одна фабрика + один фейк для preview:

| Тип | Класс / файл | Когда вы его получаете | Что умеет |
|-----|--------------|------------------------|-----------|
| `BaseDialogManager` | Protocol, `api/protocols/manager.py:24` | базовый контракт | только `done/start/switch_to/update/bg/fg` |
| `DialogManager` | Protocol, `api/protocols/manager.py:99` | в хэндлерах диалога (foreground) | полный интерфейс (всё + чтение контекста) |
| `ManagerImpl` | `manager/manager.py:72` | реальная реализация `DialogManager`, инжектится в `middleware_data["dialog_manager"]` | полный интерфейс |
| `SubManager` | `manager/sub_manager.py:26` | внутри `ListGroup` (передаётся вместо `DialogManager` в `on_click` строки) | полный `DialogManager`, но `dialog_data`/`current_context` подменены на data строки |
| `BgManager` | `manager/bg_manager.py:73` (реализует `BaseDialogManager`) | через `manager.bg(...)` или `BgManagerFactory.bg(...)` | только базовый набор; асинхронная отправка событий |
| `BgManagerFactoryImpl` | `manager/bg_manager.py:288` | через `setup_dialogs()` / `middleware_data["dialog_bg_factory"]` | только `.bg()` (нужен `bot`) |
| `FakeManager` | `tools/preview.py:75` | только при генерации preview диалога | `is_preview() == True`, ничего не отправляет |

Ключевые факты:
- `ManagerImpl` создаётся `DefaultManagerFactory` (`manager/manager_factory.py:14`) на КАЖДЫЙ апдейт через `ManagerMiddleware` (`manager/manager_middleware.py:20`). Менеджер живёт ровно один апдейт и в `finally` вызывается `close_manager()` (см. §6).
- `DialogManager` наследует `BaseDialogManager` (`api/protocols/manager.py:99`), поэтому методы `start/done/switch_to/update/bg/fg` есть у обоих, но у `ManagerImpl` они работают синхронно «здесь и сейчас», а у `BgManager` — через рассылку события (см. §5).

---

## 1. Свойства (properties)

Все свойства — у `DialogManager`/`ManagerImpl`/`SubManager`. У `BgManager` их НЕТ (он только `BaseDialogManager`).

| Свойство | Тип | Откуда берёт | Источник |
|----------|-----|--------------|----------|
| `event` | `ChatEvent` | `self._event` (то, что пришло в апдейте) | `manager.py:103` / proto `manager.py:100` |
| `middleware_data` | `dict` | `self._data` — это и есть aiogram-словарь `data` из middleware (мутабельный, общий) | `manager.py:107` / proto `manager.py:109` |
| `dialog_data` | `dict` | `self.current_context().dialog_data` | `manager.py:112` / proto `manager.py:115` |
| `start_data` | `Data` | `self.current_context().start_data` | `manager.py:117` / proto `manager.py:121` |
| `show_mode` | `ShowMode` (get/set) | `self._show_mode`, дефолт `ShowMode.AUTO` | `manager.py:93,98` / proto `manager.py:127`+setter `:133` |

Подробности:

### `event -> ChatEvent`
Текущий обрабатываемый event. `ChatEvent = CallbackQuery | ChatJoinRequest | ChatMemberUpdated | DialogUpdateEvent | ErrorEvent | Message` (`api/entities/events.py:16`). Один и тот же window может перерисовываться разными типами событий — будьте осторожны, проверяйте `isinstance` (док `passing_data/index.rst`).

### `middleware_data -> dict`
Прямая ссылка на словарь aiogram `data`. Содержит всё, что положили middleware: `bot`, `event_chat`, `event_from_user`, `dialog_manager`, `dialog_bg_factory`, а также внутренние ключи aiogram_dialog: `aiogd_storage_proxy` (`STORAGE_KEY`), `aiogd_stack` (`STACK_KEY`), `aiogd_context` (`CONTEXT_KEY`), `aiogd_event_context` (`EVENT_CONTEXT_KEY`), `aiogd_event_simulated` (`EVENT_SIMULATED`). В `test_click.py:30` пример: `manager.middleware_data["usecase"]()`.

### `dialog_data -> dict`  (МУТАБЕЛЬНО, см. §7)
Словарь данных текущего диалога (`Context.dialog_data`). **Возвращает живую ссылку** — изменения по месту сохранятся (контекст сериализуется в FSM-storage в конце обработки). Доступен на ВСЕХ окнах одного диалога, недоступен родительским/дочерним диалогам. Бросает `NoContextError`, если диалога нет (через `current_context()`).

### `start_data -> Data`
Данные, переданные в `start(state, data=...)`. Read-only по смыслу (это «вход» диалога, как аргументы функции — см. `transitions/index.rst`). `Data = dict | list | int | str | float | None` (`context.py:7`).

### `show_mode -> ShowMode` (get/set)
Режим отрисовки для СЛЕДУЮЩЕГО показа. Можно присвоить напрямую (`manager.show_mode = ShowMode.SEND`, `how_are_messages_updated/example.py:2`) или передать параметром в методы. **ВАЖНО:** действует только на ближайший show, затем `new_message.show_mode` пересчитывается, но само поле `self._show_mode` НЕ сбрасывается автоматически в коде `show()` — фактический сброс к AUTO происходит потому, что менеджер пересоздаётся на следующий апдейт (§7, подводный камень).

---

## 2. Чтение/состояние контекста и стека

### `current_context() -> Context`
`manager.py:154` / proto `:155`. Возвращает текущий `Context`. Сначала `check_disabled()` (бросит `IncorrectBackgroundError`, если менеджер `disabled`), затем читает `self._data[CONTEXT_KEY]`. Если контекста нет — логирует warning и бросает **`NoContextError`**. У `SubManager` (`sub_manager.py:58`) переопределён: берёт контекст родителя, лезет в `context.widget_data[widget_id][item_id]` и возвращает `dataclasses.replace(context, widget_data=row_data)` — то есть `widget_data` подменён на данные конкретной строки.

`Context` (`api/entities/context.py:11`, `@dataclass(unsafe_hash=True)`):
- `_intent_id: str` (доступ через `.id`), `_stack_id: str` (через `.stack_id`) — участвуют в hash/eq.
- `state: State`, `start_data: Data`, `dialog_data: DataDict={}`, `widget_data: DataDict={}`, `access_settings: AccessSettings|None=None` — `compare=False`.

### `has_context() -> bool`
`manager.py:167` / proto `:163`. `bool(self._data[CONTEXT_KEY])`. Безопасная проверка перед обращением к `dialog_data`/`current_context()`. После `check_disabled()`.

### `current_stack() -> Stack`
`manager.py:171` / proto `:169`. Возвращает `self._data[STACK_KEY]`. У `SubManager` делегирует родителю.

`Stack` (`api/entities/stack.py:38`): `_id` (через `.id`), `intents: list[str]`, `last_message_id`, `last_reply_keyboard`, `last_media_id`, `last_media_unique_id`, `last_income_media_group_id`, `content_type`, `access_settings`, `has_protected_content`. Методы: `push(state, data) -> Context` (бросает `DialogStackOverflow` при ≥100 интентов, `_STACK_LIMIT`), `pop()`, `last_intent_id()`, `empty()`, `default()`. `DEFAULT_STACK_ID = ""`, `GROUP_STACK_ID = "<->"`.

### `load_data() -> dict`  (async)
`manager.py:130` / proto `:202`. Собирает полный data-dict для рендера: вызывает глобальный getter (если задан в `setup_dialogs`), затем накладывает `{"dialog_data", "start_data", "middleware_data", "event", **getter_result}`. Требует наличия контекста (`current_context()`). Это «глобальный» getter уровня менеджера; getter'ы Dialog/Window применяются отдельно при `render`.

---

## 3. Навигация и жизненный цикл диалога

> Таблица сигнатур (foreground, `ManagerImpl`):

| Метод | Сигнатура | Возврат |
|-------|-----------|---------|
| `start` | `async start(state: State, data: Data=None, mode: StartMode=StartMode.NORMAL, show_mode: ShowMode\|None=None, access_settings: AccessSettings\|None=None)` | `None` |
| `done` | `async done(result: Any=None, show_mode: ShowMode\|None=None)` | `None` |
| `switch_to` | `async switch_to(state: State, show_mode: ShowMode\|None=None)` | `None` |
| `next` | `async next(show_mode: ShowMode\|None=None)` | `None` |
| `back` | `async back(show_mode: ShowMode\|None=None)` | `None` |
| `update` | `async update(data: dict\|None=None, show_mode: ShowMode\|None=None)` | `None` |
| `show` | `async show(show_mode: ShowMode\|None=None)` | `None` (у `SubManager` аннотирован `Message`, фактически делегирует) |
| `reset_stack` | `async reset_stack(remove_keyboard: bool=True)` | `None` |
| `mark_closed` | `async mark_closed()` | `None` |
| `answer_callback` | `async answer_callback()` | `None` |
| `find` | `find(widget_id) -> Any \| None` | managed-адаптер виджета |
| `bg` | `bg(user_id=None, chat_id=None, stack_id=None, thread_id=UnsetId.UNSET, business_connection_id=UnsetId.UNSET, load=False) -> BaseDialogManager` | `BgManager` |
| `fg` | `fg() -> AbstractAsyncContextManager[DialogManager]` | сам менеджер (для bg) |
| `close_manager` | `async close_manager()` | `None` |
| `is_preview` | `is_preview() -> bool` | `False` (у ManagerImpl всегда) |

### `start(...)` — `manager.py:241`
Добавляет новый диалог в стек и показывает его. Шаги: `check_disabled()`; `self.show_mode = show_mode or self.show_mode`; ветвление по `mode`:
- `StartMode.NORMAL` → `_start_normal` (`manager.py:284`).
- `StartMode.RESET_STACK` → `reset_stack(remove_keyboard=False)` затем `_start_normal`.
- `StartMode.NEW_STACK` → `_start_new_stack` — создаёт новый `Stack()` и стартует через `self.bg(stack_id=stack.id).start(...)` (т.е. через bg-событие, см. §5!). Иначе `ValueError`.

`_start_normal` детали (важно для прод):
- если стек не пуст и текущий диалог `LaunchMode.EXCLUSIVE` → `ValueError` («Cannot start dialog on top of one with launch_mode==SINGLE»).
- `_process_launch_mode` (`manager.py:315`): для нового диалога `EXCLUSIVE|ROOT` → `reset_stack(remove_keyboard=False)`; для `SINGLE_TOP`, если он же на вершине → снимает текущий контекст (replace).
- наследование `access_settings`: если `None`, берётся из текущего контекста, иначе из стека; кладётся в новый контекст через `deepcopy`.
- `stack.push(state, data)` создаёт новый `Context` с новым `intent_id`; вызывается `dialog().process_start(self, data, state)`; затем если контекст не сменился внутри хука — `show()`.

Пример: `docs/transitions/start.py` (`manager.start(SubDialogSG.second, data={"key": "value"})`), `Start`-кнопка делает то же.

### `done(...)` — `manager.py:196`
Закрывает текущий диалог, показывает нижележащий. Шаги: `check_disabled()`; `show_mode = show_mode or self.show_mode`; `dialog().process_close(result, self)`; запоминает `old_context`; `mark_closed()` (снимает с вершины стека); если стек опустел → `_process_last_dialog_result` (просто убирает клавиатуру `_remove_kbd`); иначе `dialog().process_result(old_start_data, result, self)` (родитель ловит результат в `on_process_result`), и если контекст после этого тот же — `show()`. Пример `docs/transitions/done.py` (`manager.done(result={"name": "Tishka17"})`).

### `switch_to(...)` — `manager.py:355`
Переключает окно ВНУТРИ текущего диалога (контекст тот же, данные сохраняются). `check_disabled()`; проверка `context.state.group == state.group` иначе `ValueError` («Cannot switch to another state group»); `show_mode`; `context.state = state`. **NB:** сам `switch_to` НЕ вызывает `show()` — перерисовка происходит у вызывающего (`Window`/handle_update делает `show()` отдельно: `update_handler.py:29`). Но `next/back` ниже вызывают `switch_to` и затем НЕ делают show сами — show идёт через стандартный поток обработки клика. Кнопка `SwitchTo` инкапсулирует это.

### `next(...)` — `manager.py:327`  /  `back(...)` — `manager.py:341`
Берут `dialog().states()` (упорядоченный список), находят индекс текущего `state` и переходят на `+1`/`-1` через `switch_to`. На границах бросают `ValueError` (нельзя за пределы списка). Кнопки `Next`/`Back` — обёртки. Пример: `docs/transitions/switch.py`, `test_click.py:31` (`await manager.next()`).

### `update(data=None, show_mode=None)` — `manager.py:529`
Если `data` непустой — `self.current_context().dialog_data.update(data)` (мерж в текущий dialog_data), затем `show(show_mode)`. Используется для перерисовки с обновлением данных. У `SubManager` (`sub_manager.py:142`) — то же, но `current_context()` указывает на data строки. Пример `data_in_handlers.py`.

### `reset_stack(remove_keyboard=True)` — `manager.py:261`
Сбрасывает ТЕКУЩИЙ стек: в цикле `pop` + `remove_context` для каждого интента, `save_stack`, по флагу `_remove_kbd()`, `CONTEXT_KEY=None`. **Колбэки не вызываются**, контексты просто стираются из storage (док `manager.py:194`). Используется внутри `StartMode.RESET_STACK` (с `remove_keyboard=False`).

### `mark_closed()` — `manager.py:229`
Низкоуровнево снимает текущий контекст с вершины: `storage.remove_context(stack.pop())`; если стек пуст → `CONTEXT_KEY=None`, иначе грузит предыдущий контекст по `last_intent_id`; `save_stack`. Вызывается внутри `done()`. Прямой вызов — редкий случай (закрыть без `process_close/process_result`).

### `show(show_mode=None)` — `manager.py:380`
Рендерит и отправляет/редактирует сообщение. Если `self.show_mode is ShowMode.NO_UPDATE` → выходит сразу. Иначе `dialog().render(self)` → `NewMessage`, проставляет `new_message.show_mode = show_mode or self.show_mode`, если `AUTO` → `_calc_show_mode()` (см. §4). Чинит кешированный `file_id` медиа, проверяет совместимость со стеком (`_ensure_stack_compatible`: `ReplyKeyboardMarkup` запрещён в не-дефолтном стеке → `InvalidKeyboardType`), отправляет через `message_manager.show_message`. При `MessageNotModified` — ничего не сохраняет. Сохраняет id сообщения/медиа в стек, кеширует media_id. На исключении (Python ≥3.11) добавляет note со state. Побочка: пишет `last_*` поля стека и кеш медиа.

### `answer_callback()` — `manager.py:219`
Если `event` не `CallbackQuery` или событие симулировано (`EVENT_SIMULATED`) → `None`. Иначе `message_manager.answer_callback(...)` (гасит «часики» на кнопке). Обычно вызывается фреймворком автоматически.

### `find(widget_id) -> Any | None` — `manager.py:538`
Ищет виджет в текущем диалоге по id; возвращает **managed-адаптер** (`widget.managed(self)`) — урезанный интерфейс без необходимости передавать manager (proto `:184`). У `SubManager` (`sub_manager.py:88`) ищет внутри своего `ListGroup`-виджета; есть доп.метод `find_in_parent(widget_id)` (`sub_manager.py:94`) — ищет в родительском `DialogManager` (вне строки). Семантика: `.find` — внутри строки, `.find_in_parent` — снаружи (`list_group/index.rst`).

### `is_preview() -> bool` — `manager.py:144`
`ManagerImpl` всегда `False`. `True` только у `FakeManager` (`tools/preview.py:157`) при генерации превью. Используйте, чтобы пропустить реальные I/O при рендере превью.

---

## 4. ShowMode — режимы показа

`ShowMode(Enum)` (`api/entities/modes.py:4`):
- `AUTO` (`"auto"`) — дефолт. `SEND` на сообщении от пользователя, `EDIT` на прочих апдейтах.
- `EDIT` (`"edit"`) — редактировать текущее сообщение диалога.
- `SEND` (`"send"`) — отправить новое сообщение.
- `DELETE_AND_SEND` (`"delete_and_send"`) — удалить старое и отправить новое. **Внимание:** Telegram не даст удалить сообщение старше 48 часов.
- `NO_UPDATE` (`"no_update"`) — вообще не перерисовывать (`show()` сразу выходит).

Где принимается параметр `show_mode`: `start`, `done`, `switch_to`, `next`, `back`, `update`, `show`. Также сеттер `manager.show_mode`. **`ShowMode` действует только на следующий апдейт, затем возвращается к AUTO** (док `how_are_messages_updated/index.rst`).

`_calc_show_mode()` (`manager.py:510`) — логика AUTO:
1. если `show_mode != AUTO` → как есть;
2. чат не приватный → `EDIT`;
3. на экране была reply-клавиатура (`last_reply_keyboard`) → `DELETE_AND_SEND`;
4. стек не дефолтный → `EDIT`;
5. событие `Message`: нет media_group → `SEND`; media_group тот же, что у прошлого входящего → `EDIT`; иначе `SEND`;
6. иначе → `EDIT`.

---

## 5. BgManager — фоновый менеджер (BaseDialogManager)

`BgManager` (`manager/bg_manager.py:73`) реализует ТОЛЬКО `done/start/switch_to/update/bg/fg`. Все они **не выполняют действие сразу**, а формируют `DialogUpdateEvent` и рассылают через `Updater.notify` (планируется через `loop.call_soon`, `updater.py:18`) — то есть выполнение происходит асинхронно в отдельном таске обработки апдейта (`update_handler.handle_update`, `update_handler.py:16`).

Зачем нужен: когда у вас НЕТ корректного `dialog_manager` (фоновые задачи, http/broker-хэндлеры, действия для другого чата/пользователя — `bg/index.rst:5`). Нельзя использовать обычный `dialog_manager` вне dialog-хэндлера.

Сигнатуры bg-операций (`bg_manager.py`):
- `async start(state, data=None, mode=StartMode.NORMAL, show_mode=None, access_settings=None)` → `_load()` + событие `DialogStartEvent`.
- `async done(result=None, show_mode=None)` → `DialogUpdateEvent(action=DONE)`.
- `async switch_to(state, show_mode=None)` → `DialogSwitchEvent` (data={}).
- `async update(data=None, show_mode=None)` → `DialogUpdateEvent(action=UPDATE, data=data or {})`.

### `bg(...)` — получение фонового менеджера
У `ManagerImpl` (`manager.py:564`) и `BgManager` (`bg_manager.py:111`) сигнатура:
```python
def bg(user_id=None, chat_id=None, stack_id=None,
       thread_id=UnsetId.UNSET, business_connection_id=UnsetId.UNSET,
       load=False) -> BaseDialogManager
```
- `user_id`/`chat_id`: если совпадают с текущими — берётся реальный `User`/`Chat`, иначе подставляется `FakeUser`/`FakeChat` (`fake_data.py`). Для событий без чата явный `chat_id` обязателен (иначе `ValueError`, `manager.py:557`).
- `thread_id`/`business_connection_id`: сентинел `UnsetId.UNSET` (`api/protocols/manager.py:20`) означает «унаследовать из текущего EventContext, если чат и юзер те же» (`coalesce_*`, `bg_manager.py:41,57`). Явный `None` → сбросить.
- `stack_id`: если `None` и event_context не изменился — берётся текущий стек (+ `intent_id` текущего контекста); если изменился — `DEFAULT_STACK_ID`.
- `load=True`: при первом обращении догрузит `Chat`/`User` через `bot.get_chat`/`get_chat_member` (`bg_manager.py:178`) — нужно, если у вас только id (FakeChat/FakeUser).

Возвращает новый `BgManager`. Примеры: `tests/test_fg.py:36` (`dialog_manager.bg(user_id=2, chat_id=-1)`), `docs/widgets/text/progress/bg_manager_example.py` (`manager.bg(user_id=..., chat_id=..., stack_id="progress_stack", load=True)` → `bg.start(...)` → фоновая задача).

### `fg()` — вход в полноценный менеджер из bg
`ManagerImpl.fg` (`manager.py:617`) — тривиальный `@asynccontextmanager`, `yield self`.
`BgManager.fg` (`bg_manager.py:265`) — рассылает `DialogFgEvent` с futures `entered/exited`, дожидается, пока обработчик войдёт в контекст и вернёт настоящий `DialogManager`, затем `yield manager`. Использование (`bg/index.rst:29`, `test_fg.py:36`):
```python
async with dialog_manager.bg(user_id=2, chat_id=-1).fg() as manager:
    await manager.start(MainSG.start, mode=StartMode.RESET_STACK)
    # тут есть dialog_data, current_context() и т.д.
```
Это единственный способ получить ПОЛНЫЙ `DialogManager` для другого чата/фоновой задачи. Исключение внутри `with` пробрасывается в `exited.set_exception` и поднимается.

### `BgManagerFactory` / `BgManagerFactoryImpl`
`api/protocols/manager.py:83` / `bg_manager.py:288`. Метод `bg(bot, user_id, chat_id, stack_id=None, thread_id=None, business_connection_id=None, load=False)` — отличается тем, что требует явный `bot` и работает только с id (FakeChat/FakeUser), `stack_id` по умолчанию `DEFAULT_STACK_ID`. Получить фабрику: возврат `setup_dialogs(dp)`, либо в хэндлере `dialog_bg_factory: BgManagerFactory`, либо `manager.middleware_data["dialog_bg_factory"]` (`bg/index.rst`).

**Подводный камень bg:** свои middleware на bg-события по умолчанию НЕ срабатывают; зарегистрируйте их на `DIALOG_EVENT_NAME`: `dispatcher.observers[DIALOG_EVENT_NAME].middleware(...)` (`bg/index.rst:90`).

---

## 6. close_manager и disabled-механика

### `close_manager()` — `manager.py:621`
`check_disabled()`; ставит `self.disabled = True`; удаляет `media_id_storage`, `message_manager`, `_event`, `_data`. Вызывается автоматически в `ManagerMiddleware.__call__` в `finally` (`manager_middleware.py:57`). После этого почти любой метод бросит `IncorrectBackgroundError` через `check_disabled()` (`manager.py:122`).

**Подводный камень:** нельзя сохранять `dialog_manager` и обращаться к нему из фоновой задачи/после завершения хэндлера — он будет `disabled`. Сообщение об ошибке прямо рекомендует `manager.bg()` (`manager.py:124`). Для фоновых сценариев захватывайте только id и используйте `bg()`/`bg(...).fg()`.

`check_disabled()` стоит в: `done, mark_closed, start, reset_stack, switch_to, current_context, has_context, current_stack, dialog, close_manager`. Заметьте: `show`, `update`, `next`, `back`, `find` напрямую `check_disabled()` не зовут, но падают косвенно (через `current_context`/`dialog`).

---

## 7. dialog_data: где брать и как менять (мутабельность)

- Чтение: `manager.dialog_data` или `manager.current_context().dialog_data` — это одна и та же живая ссылка (`manager.py:113-115`).
- Изменение «по месту»: `manager.dialog_data["k"] = v` — РАБОТАЕТ и сохранится, т.к. это ссылка на dict внутри `Context`, который в конце обработки апдейта сериализуется в FSM-storage (`StorageProxy`).
- Изменение через API: `manager.update({"k": v})` — мержит в `dialog_data` и перерисовывает (`manager.py:534`).
- Внутри bg-`update`: данные применяются в `handle_update` поэлементно (`update_handler.py:38`).
- В `SubManager` `dialog_data` фактически указывает на `widget_data[widget_id][item_id]` строки ListGroup, НЕ на общий dialog_data диалога (`sub_manager.py:51,58`). Чтобы достучаться до общего — берите родителя или `find_in_parent`.

**Краевой случай:** обращение к `dialog_data` без открытого диалога → `NoContextError`. Всегда проверяйте `has_context()` в хэндлерах, которые могут срабатывать без активного диалога.

---

## 8. SubManager — детали (ListGroup / вложенность)

`SubManager(widget: Widget, manager: DialogManager, widget_id: str, item_id: str)` (`sub_manager.py:27`). Реализует полный `DialogManager`, но **делегирует почти всё** родителю (`event`, `middleware_data`, `start_data`, `show`, `next`, `back`, `done`, `start`, `switch_to`, `reset_stack`, `load_data`, `bg`, `fg`, `show_mode`, `has_context`, `is_preview`, `current_stack`, `close_manager`, `answer_callback`).

Что переопределено:
- `current_context()` (`:58`) — подменяет `widget_data` на `widget_data[widget_id][item_id]` через `setdefault` + `dataclasses.replace`.
- `dialog_data` (`:49`) и `update()` (`:142`) — работают через этот подменённый контекст (т.е. с data строки).
- `find()` (`:88`) — ищет внутри виджета строки; `find_in_parent()` (`:94`) — в родителе.

Создаётся в `widgets/kbd/list_group.py` (`:87,124,139,150,170`): при рендере строки, при обработке клика и в `managed()/find_for_item()`. `item_id` берётся из `item_id_getter`. Доступ из хэндлера: `manager.item_id` (это атрибут SubManager, не DialogManager-протокола) — так определяют, какая строка кликнута (`list_group/index.rst:8`). Вложенный ListGroup → родитель тоже SubManager (`list_group/index.rst:19`).

---

## 9. Связи с остальной библиотекой

- **Создание менеджера:** `ManagerMiddleware` (`manager_middleware.py:20`) на каждый поддерживаемый апдейт (`STORAGE_KEY in data`) вызывает `DialogManagerFactory` (`api/internal/manager.py:13`, дефолт `DefaultManagerFactory` `manager_factory.py:14`) → `ManagerImpl`, кладёт в `data["dialog_manager"]`, в `finally` `close_manager()`.
- **Storage:** `manager.storage()` → `StorageProxy` (`context/storage.py`), методы `load_context/save_context/remove_context/save_stack` — используются в `start/done/mark_closed/reset_stack`. Ключи в `data`: `STACK_KEY`, `CONTEXT_KEY`, `STORAGE_KEY`.
- **Dialog:** `manager.dialog()` (`manager.py:147`) → `DialogProtocol` через `registry.find_dialog(state)` (`setup.py:61`). Менеджер дёргает у диалога `process_start/process_result/process_close/render/states/find` (`api/protocols/dialog.py`). Менеджер ПЕРЕДАЁТСЯ в эти хуки первым/третьим аргументом.
- **Widgets:** `find()` → `widget.managed(manager)` — у каждого виджета свой managed-адаптер (например `ManagedListGroup`). Стейтфул-виджеты хранят данные в `Context.widget_data`.
- **BgManager поток:** `bg()` → `BgManager` → `Updater.notify` → `Dispatcher.propagate_event` (тип `aiogd_update`) → `handle_update` → уже обычный `DialogManager`. `StartMode.NEW_STACK` и `bg()` тесно связаны: новый стек стартует ИМЕННО через bg-событие (`manager.py:272`).
- **EventContext** (`events.py:27`) в `data["aiogd_event_context"]` — источник chat/user/bot/thread_id/business_connection_id для `bg()` и формирования OldMessage.

---

## 10. Подводные камни (сводка для прод-шаблона)

1. **`dialog_manager` живёт один апдейт.** После хэндлера `close_manager()` делает его `disabled`. Любой доступ из фоновой задачи → `IncorrectBackgroundError`. Для фона: захватывайте `chat_id/user_id`, используйте `manager.bg(...)` или `bg(...).fg()`.
2. **`dialog_data`/`current_context` без активного диалога → `NoContextError`.** Защищайтесь `has_context()`.
3. **`ShowMode` одноразовый** — действует на следующий show и «сбрасывается» (за счёт пересоздания менеджера). Не полагайтесь на «залипание» режима между апдейтами.
4. **`switch_to` не перерисовывает сам** (как и просто `context.state=...`); рассчитывайте, что show идёт следующим шагом потока обработки. `next/back` тоже делегируют в `switch_to`. В ручных сценариях после `switch_to` вызывайте `show()` сами (см. `update_handler.py:29`).
5. **`StartMode.NEW_STACK` и bg идут через очередь событий** (`call_soon`/таск) — не синхронно. Не ждите результата немедленно после вызова.
6. **`EXCLUSIVE`-диалог нельзя перекрыть** (`start` → `ValueError`); `ROOT`/`EXCLUSIVE` сбрасывают стек; `SINGLE_TOP` заменяет себя на вершине. Лимит стека — 100 (`DialogStackOverflow`). Не забывайте чистить стек (`RESET_STACK`/`reset_stack`), иначе утечка памяти (`transitions/index.rst:28`).
7. **`ReplyKeyboardMarkup` запрещён в не-дефолтном стеке** (`InvalidKeyboardType`, `manager.py:375`).
8. **bg-события не проходят обычные middleware** — регистрируйте на `DIALOG_EVENT_NAME`.
9. **SubManager.dialog_data ≠ общий dialog_data** — это data строки ListGroup. Для общего используйте `find_in_parent` / родительский менеджер.
10. **`reset_stack`/`mark_closed` не вызывают колбэков** (`on_process_result` и т.п.). Для корректного закрытия с результатом используйте `done()`.
