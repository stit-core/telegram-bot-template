---
zone: "03 — Window и Dialog: конструкция, рендеринг, lifecycle-хуки"
library: aiogram_dialog
ref: develop @ 08abdf0 (2026-05-02)
aiogram: ">=3.14.0"
files:
  - src/aiogram_dialog/window.py
  - src/aiogram_dialog/dialog.py
  - src/aiogram_dialog/api/internal/window.py
  - src/aiogram_dialog/api/protocols/dialog.py
  - src/aiogram_dialog/api/entities/launch_mode.py
related:
  - src/aiogram_dialog/widgets/utils.py
  - src/aiogram_dialog/widgets/data/data_context.py
  - src/aiogram_dialog/manager/manager.py
  - src/aiogram_dialog/api/entities/new_message.py
tags: [window, dialog, getter, launch_mode, hooks, lifecycle, preview, render]
---

# Зона 03 — Window и Dialog

`Window` — единица отображения (один экран = одно состояние FSM). `Dialog` —
контейнер окон, привязанный к одному `StatesGroup`, одновременно являющийся
aiogram `Router`. Совместно они описывают **что** рендерить (`Window`),
**когда переключать** (`Dialog`/`DialogManager`) и **как реагировать** на
жизненный цикл (хуки).

---

## 1. Window — `src/aiogram_dialog/window.py:41`

### 1.1. Полная сигнатура `__init__` (`window.py:42-84`)

```python
class Window(WindowProtocol):
    def __init__(
        self,
        *widgets: WidgetSrc,
        state: State,                                  # обязательный, keyword-only
        getter: GetterVariant = None,
        on_process_result: OnResultEvent | None = None,
        markup_factory: MarkupFactory = _DEFAULT_MARKUP_FACTORY,   # InlineKeyboardFactory()
        parse_mode: str | None = UNSET_PARSE_MODE,
        disable_web_page_preview: bool | None = None,  # DEPRECATED
        protect_content: bool | None = None,
        preview_add_transitions: list[Keyboard] | None = None,
        preview_data: GetterVariant = None,
    ): ...
```

> ВАЖНО: все параметры после `*widgets` — **keyword-only**. `state` обязателен.
> В исходном develop-коде **нет** отдельного `disable_web_page_preview` как
> рабочей опции — он deprecated и при ненулевом значении транслируется в
> `LinkPreview(is_disabled=True)`. (В формулировке задачи фигурирует
> `disable_web_page_preview=` — он существует, но как deprecated-shim.)

| Параметр | Тип | Дефолт | Назначение |
|---|---|---|---|
| `*widgets` | `WidgetSrc` (см. §1.2) | — | виджеты окна; раскладываются по ролям через `ensure_widgets` |
| `state` | `aiogram.fsm.state.State` | — (обяз.) | идентифицирует окно внутри диалога; FSM-состояние |
| `getter` | `GetterVariant` | `None` | поставщик данных окна для рендера (`getter(**middleware_data) -> dict`) |
| `on_process_result` | `OnResultEvent \| None` | `None` | хук окна: вызывается при возврате результата дочернего диалога (`done()`), если активно это окно |
| `markup_factory` | `MarkupFactory` | `InlineKeyboardFactory()` | превращает `RawKeyboard` (list[list[button]]) в `reply_markup` |
| `parse_mode` | `str \| None` | `UNSET_PARSE_MODE` | parse_mode сообщения; `UNSET_PARSE_MODE` означает «брать из `Bot.default`» |
| `disable_web_page_preview` | `bool \| None` | `None` | **DEPRECATED**; используйте виджет `LinkPreview` |
| `protect_content` | `bool \| None` | `None` | Telegram protect_content (запрет пересылки/сохранения) |
| `preview_add_transitions` | `list[Keyboard] \| None` | `None` | подсказка для генерации графа переходов и web-preview: «виртуальные» кнопки-переходы (`Next`, `Cancel`, ...), которых нет в боевой клавиатуре |
| `preview_data` | `GetterVariant` | `None` | данные, подставляемые вместо `getter` в режиме preview (`manager.is_preview()`) |

Поля, выставляемые в `__init__`: `self.text`, `self.keyboard`,
`self.on_message`, `self.media`, `self.link_preview` (результат
`ensure_widgets`), `self.getter` (обёрнут в `PreviewAwareGetter`), `self.state`,
`self.on_process_result`, `self.markup_factory`, `self.parse_mode`,
`self.protect_content`, `self.preview_add_transitions`.

### 1.2. `WidgetSrc` и раскладка виджетов по ролям

`WidgetSrc` (`widgets/utils.py:17-25`):
```python
WidgetSrc = str | TextWidget | Keyboard | MessageHandlerFunc | Media | BaseInput | LinkPreviewBase
```

`ensure_widgets(widgets)` (`widgets/utils.py:97-135`) разбирает `*widgets`
**по типу** и возвращает кортеж из 5 единиц
`(text, keyboard, input, media, link_preview)`:

| Роль (атрибут Window) | Что кладётся | Если несколько | Если ни одного |
|---|---|---|---|
| `text` (`TextWidget`) | `str` → `Format`; экземпляры `Text` | оборачиваются в `Multi(*texts)` | `Multi()` (пустой текст) |
| `keyboard` (`Keyboard`) | экземпляры `Keyboard` (Button, Group, Row, Start, ...) | оборачиваются в `Group(*kbds)` | `Group()` (пустая клавиатура) |
| `on_message` (`BaseInput`) | `BaseInput` или `Callable` (→ `MessageInput`) | оборачиваются в `CombinedInput(*inputs)` | `None` |
| `media` (`Media`) | экземпляр `Media` | **`ValueError("Only one media widget is supported")`** | `Media()` (пустой) |
| `link_preview` (`LinkPreviewBase`) | экземпляр `LinkPreview` | **`ValueError("Only one link preview widget is supported")`** | `None` |

- Распознавание типа: `str`/`Text` → текст; `Keyboard` → клавиатура;
  `BaseInput` **или любой `Callable`** → input; `Media` → медиа;
  `LinkPreviewBase` → link preview (`widgets/utils.py:112-128`).
- Неизвестный тип → `InvalidWidgetType` («Only str, Text, Keyboard, BaseInput
  and Callable are supported»). На медиа/link preview лимит — **строго один**.
- Поскольку голый `Callable` трактуется как input-хендлер, передача функции в
  `*widgets` означает обработчик сообщений, а не getter. Getter передаётся
  только через `getter=`.

### 1.3. `disable_web_page_preview` (deprecated, `window.py:72-84`)

При `disable_web_page_preview is not None`:
1. если уже есть виджет `LinkPreview` → `ValueError` (конфликт);
2. `DeprecationWarning`;
3. `self.link_preview = LinkPreview(is_disabled=True)`.

`True` и `False` оба считаются «не None» — поэтому даже `False` вызовет
warning и принудительно создаст `LinkPreview(is_disabled=True)` (краевой случай).

### 1.4. Методы рендера/обработки Window

| Метод | Сигнатура | Возврат / эффект |
|---|---|---|
| `render` | `async render(dialog: DialogProtocol, manager) -> NewMessage` (`window.py:147`) | главный метод: собирает данные, текст, клавиатуру, медиа, link preview в `NewMessage` |
| `load_data` | `async load_data(dialog, manager) -> dict` (`window.py:113`) | `dialog.load_data(manager)` затем `.update(self.getter(**middleware_data))` |
| `render_text` | `async render_text(data, manager) -> str` (`window.py:86`) | делегирует `self.text.render_text` |
| `render_kbd` | `async render_kbd(data, manager) -> MarkupVariant` (`window.py:98`) | `keyboard.render_keyboard` → `markup_factory.render_markup` |
| `render_media` | `async render_media(data, manager) -> MediaAttachment \| None` (`window.py:91`) | `None`, если медиа нет |
| `render_link_preview` | `async render_link_preview(data, manager) -> LinkPreviewOptions \| None` (`window.py:106`) | `None`, если link preview нет |
| `process_message` | `async process_message(message, dialog, manager) -> bool` (`window.py:121`) | делегирует `self.on_message.process_message`; `False` если input нет |
| `process_callback` | `async process_callback(callback, dialog, manager) -> bool` (`window.py:131`) | делегирует `self.keyboard.process_callback`; `False` если кнопок нет |
| `process_result` | `async process_result(start_data, result, manager) -> None` (`window.py:141`) | вызывает `self.on_process_result`, если задан |
| `get_state` | `get_state() -> State` (`window.py:179`) | возвращает `self.state` |
| `find` | `find(widget_id) -> Widget \| None` (`window.py:182`) | ищет по `text/keyboard/on_message/media` (link_preview не сканируется!) |

#### `render()` детально (`window.py:147-177`)
1. `chat = manager.middleware_data["event_chat"]`.
2. `current_data = await self.load_data(dialog, manager)` (обёрнут try/except
   с логом `"Cannot get window data for state %s"`).
3. Берёт `EventContext` из `middleware_data[EVENT_CONTEXT_KEY]` (для `thread_id`,
   `business_connection_id`).
4. Конструирует `NewMessage(chat, thread_id, business_connection_id, text,
   reply_markup, parse_mode, protect_content, media, link_preview_options)`.
   `show_mode` **не** заполняется окном (остаётся `ShowMode.AUTO` по умолчанию;
   его проставляет `DialogManager.show()`, см. `manager.py:390-392`).

> `find()` НЕ ищет внутри `link_preview` (`window.py:183`) — поэтому id внутри
> `LinkPreview` через `manager.find()` недоступен.

### 1.5. `WindowProtocol` — `src/aiogram_dialog/api/internal/window.py:15`

`Protocol` с `@abstractmethod`: `process_message -> bool`,
`process_callback -> bool`, `process_result -> None`, `render -> NewMessage`,
`get_state -> State`, `find -> Any`. `Window` реализует всё это плюс
render_*-методы и `load_data` (которых нет в протоколе). Тип параметров окон в
`Dialog.__init__` — именно `WindowProtocol`, так что можно подменять окна
кастомной реализацией протокола.

---

## 2. Dialog — `src/aiogram_dialog/dialog.py:36`

`class Dialog(Router, DialogProtocol)` — **является aiogram `Router`**.

### 2.1. Полная сигнатура `__init__` (`dialog.py:37-77`)

```python
class Dialog(Router, DialogProtocol):
    def __init__(
        self,
        *windows: WindowProtocol,
        on_start: OnDialogEvent | None = None,
        on_close: OnDialogEvent | None = None,
        on_process_result: OnResultEvent | None = None,
        launch_mode: LaunchMode = LaunchMode.STANDARD,
        getter: GetterVariant = None,
        preview_data: GetterVariant = None,
        name: str | None = None,
    ): ...
```

> В задаче упомянут параметр `windows` — это `*windows` (позиционный варарг,
> минимум одно окно).

| Параметр | Тип | Дефолт | Назначение |
|---|---|---|---|
| `*windows` | `WindowProtocol` | — (≥1) | окна диалога; пустой список → `ValueError("Dialog must have at least one window")` |
| `on_start` | `OnDialogEvent \| None` | `None` | хук при старте диалога |
| `on_close` | `OnDialogEvent \| None` | `None` | хук при закрытии (`done()`) |
| `on_process_result` | `OnResultEvent \| None` | `None` | хук диалога при возврате результата дочернего диалога |
| `launch_mode` | `LaunchMode` | `STANDARD` | политика стека при запуске (см. §3) |
| `getter` | `GetterVariant` | `None` | getter уровня **диалога** (общие данные для всех окон) |
| `preview_data` | `GetterVariant` | `None` | данные диалога для preview-режима |
| `name` | `str \| None` | `None` | имя Router; по умолчанию `windows[0].get_state().group.__name__` |

### 2.2. Связь со `StatesGroup` (`dialog.py:48-67`)

В конструкторе:
1. Пустой список окон → `ValueError`.
2. `super().__init__(name=name or windows[0].get_state().group.__name__)`.
3. `self._states_group = windows[0].get_state().group` — группа берётся из
   **первого** окна.
4. Проход по окнам:
   - окно из другой группы → `ValueError("All windows must be attached to same StatesGroup")`;
   - дубликат состояния → `ValueError(f"Multiple windows with state {state}")`.
5. `self.windows: dict[State, WindowProtocol]` (порядок = порядок аргументов).
   Порядок важен для `Next`/`Back`/`next()` (индекс в `self._states`).

Методы группы: `states() -> list[State]` (`dialog.py:83`),
`states_group() -> type[StatesGroup]` (`dialog.py:192`),
`states_group_name() -> str` через `__full_group_name__` (`dialog.py:195`).

> ВАЖНО: один `Dialog` ⇄ ровно один `StatesGroup`. Несколько групп — несколько
> Dialog. `dialog.name` = имя группы (если не задан `name`); см.
> `tests/test_create.py:25-43`.

### 2.3. `Dialog` как Router и регистрация хендлеров

- `_setup_filter()` (`dialog.py:180`): на **все** observers Router вешается
  `IntentFilter(aiogd_intent_state_group=self.states_group())` — он пропускает
  событие, только если `context.state.group` совпадает с группой диалога
  (`context/intent_filter.py:13-21`). Так события маршрутизируются нужному
  диалогу по активному состоянию.
- `_register_handlers()` (`dialog.py:187`): регистрирует
  `_callback_handler` на `callback_query`, `_message_handler` на `message` и
  на `business_message`.
- `include_router()` переопределён и **запрещён**:
  `raise TypeError("Dialog cannot include routers")` (`dialog.py:213`).
  Сам диалог включают в Dispatcher/Router: `dp.include_router(dialog)`.

### 2.4. Обработка событий и `_need_refresh`

`_callback_handler` (`dialog.py:141`):
1. сохраняет `old_context`;
2. через `remove_intent_id(callback.data)` срезает intent-id, делает
   `callback.model_copy(update={"data": ...})` (виджеты видят «чистый»
   callback_data без служебного префикса);
3. `processed = window.process_callback(...)` (ловит `CancelEventProcessing` →
   `processed=False`);
4. если `_need_refresh(...)` → `dialog_manager.show()`;
5. всегда `dialog_manager.answer_callback()`.

`_message_handler` (`dialog.py:127`) — аналогично, без answer_callback;
используется для `message` и `business_message`.

`_need_refresh(processed, old_context, manager)` (`dialog.py:160-178`):
- нет контекста → `False`;
- контекст сменился (диалог переключился/закрылся) → `False` (уже перерисован);
- `processed == True` → `True`;
- иначе, если `event_chat.type == PRIVATE` → `True` (в личке гарантируем
  видимость диалога), для групп → `False`.

### 2.5. Методы Dialog (рендер/данные)

| Метод | Сигнатура | Эффект |
|---|---|---|
| `render` | `async render(manager) -> NewMessage` (`dialog.py:122`) | находит текущее окно и `window.render(self, manager)` |
| `load_data` | `async load_data(manager) -> dict` (`dialog.py:115`) | `manager.load_data()` + `.update(self.getter(**middleware_data))` |
| `_current_window` | `async _current_window(manager) -> WindowProtocol` (`dialog.py:104`) | по `current_context().state`; иначе `UnregisteredWindowError` |
| `find` | `find(widget_id) -> Widget \| None` (`dialog.py:221`) | первый матч по всем окнам |
| `process_start` | `async process_start(manager, start_data, state=None) -> None` (`dialog.py:86`) | см. §4 |
| `process_result` | `async process_result(start_data, result, manager) -> None` (`dialog.py:198`) | см. §4 |
| `process_close` | `async process_close(result, manager) -> None` (`dialog.py:216`) | см. §4 |

### 2.6. `DialogProtocol` — `src/aiogram_dialog/api/protocols/dialog.py:18`

`@runtime_checkable Protocol`. Контракт: `launch_mode` (property),
`states_group_name() -> str`, `states() -> list[State]`,
`states_group() -> type[StatesGroup]`, `process_close`, `process_start`,
`process_result`, `find`, `load_data`, `render`. В этом же модуле определён
`class CancelEventProcessing(Exception)` (`dialog.py:14`) — бросается внутри
обработчиков виджета, чтобы отменить дефолтный re-render.

---

## 3. `LaunchMode` — `src/aiogram_dialog/api/entities/launch_mode.py:4`

```python
class LaunchMode(Enum):
    STANDARD   = "standard"
    ROOT       = "root"
    EXCLUSIVE  = "exclusive"
    SINGLE_TOP = "single_top"
```

| Значение | Поведение | Пример |
|---|---|---|
| `STANDARD` | без ограничений, обычное стекирование | большинство диалогов |
| `ROOT` | всегда корень стека; старт сбрасывает стек (`reset_stack`) | главное меню |
| `EXCLUSIVE` | единственный в стеке; старт сбрасывает стек; поверх него стартовать запрещено | баннеры |
| `SINGLE_TOP` | не дублируется на вершине: повторный старт того же диалога заменяет его | страница товара |

Где применяется (`manager/manager.py`):
- `_process_launch_mode` (`manager.py:315-325`): `EXCLUSIVE`/`ROOT` → перед
  стартом `reset_stack(remove_keyboard=False)`; `SINGLE_TOP` + тот же диалог на
  вершине → pop текущего контекста (замена).
- `_start_normal` (`manager.py:284-313`): попытка старта поверх диалога с
  `launch_mode == EXCLUSIVE` → `ValueError("Cannot start dialog on top of one
  with launch_mode==SINGLE")` (текст сообщения исторический, относится к
  EXCLUSIVE).

> Пример всех 4 режимов: `example/launch_modes.py`.

---

## 4. Lifecycle-хуки

### 4.1. Типы (`dialog.py:31-32`)

```python
OnDialogEvent = Callable[[Any, DialogManager], Awaitable]
OnResultEvent = Callable[[Data, Any, DialogManager], Awaitable]
```
`Data = dict | list | int | str | float | None` (`api/entities/context.py:7`).

### 4.2. `on_start` — старт диалога

- Сигнатура: `async (start_data: Any, manager: DialogManager)`.
- Вызов: `Dialog.process_start` (`dialog.py:86-96`) → внутри
  `manager.switch_to(state)` затем `_process_callback(self.on_start, start_data, manager)`.
- `process_start` инициируется из `DialogManager._start_normal`
  (`manager.py:310`) **после** push нового контекста. То есть к моменту вызова
  `on_start` контекст уже активен (можно писать `manager.dialog_data`,
  `manager.start_data`).
- `state=None` → берётся `self._states[0]` (первое окно). `start_data` — это
  `data`, переданная в `manager.start(state, data=...)`.
- Если хук не задан — ничего не происходит (`_process_callback` no-op при `None`).

### 4.3. `on_close` — закрытие диалога

- Сигнатура: `async (result: Any, manager: DialogManager)`.
- Вызов: `Dialog.process_close` (`dialog.py:216`) из
  `DialogManager.done()` (`manager.py:203`) — **до** `mark_closed()` (стек ещё
  содержит закрываемый контекст; диалог ещё «текущий»).
- `result` — аргумент `manager.done(result=...)`.

### 4.4. `on_process_result` — приём результата дочернего диалога

Два уровня, оба вызываются в `DialogManager.done()` после `mark_closed()`,
когда управление вернулось родительскому диалогу:

1. Хук **диалога** `Dialog.on_process_result`
   (`OnResultEvent`: `async (start_data, result, manager)`).
2. Хук **окна** `Window.on_process_result` — только если после хука диалога
   контекст не сменился (тот же `context.id`).

Поток (`dialog.py:198-211`):
```python
async def process_result(self, start_data, result, manager):
    context = manager.current_context()
    await self._process_callback(self.on_process_result, start_data, result, manager)
    if context.id == manager.current_context().id:
        await self.windows[context.state].process_result(start_data, result, manager)
```
- `start_data` — это `start_data` **закрытого** дочернего диалога
  (`old_context.start_data`, `manager.py:214`), `result` — то, что передали в
  `done(result)`.
- Окно-хук пропускается, если хук диалога сам переключил диалог/окно
  (изменился `context.id`).

### 4.5. Сводная таблица хуков

| Хук | Уровень | Тип | Сигнатура | Когда |
|---|---|---|---|---|
| `on_start` | Dialog | `OnDialogEvent` | `(start_data, manager)` | при старте, после switch_to первого/указанного state |
| `on_close` | Dialog | `OnDialogEvent` | `(result, manager)` | при `done()`, до удаления контекста из стека |
| `on_process_result` | Dialog | `OnResultEvent` | `(start_data, result, manager)` | когда дочерний диалог закрылся и вернул управление |
| `on_process_result` | Window | `OnResultEvent` | `(start_data, result, manager)` | то же, но только для активного окна и если диалог-хук не сменил контекст |

> `on_click`/`on_state_changed` и т.п. — это хуки **виджетов**, а не Dialog/Window
> (вне этой зоны).

---

## 5. Getter: Window vs Dialog и мердж данных

### 5.1. `GetterVariant` (`widgets/utils.py:27-33`)

```python
SingleGetterBase = DataGetter | dict          # DataGetter = Callable[..., Awaitable[dict]]
GetterVariant = SingleGetterBase | list[...] | tuple[...] | None
```

`ensure_data_getter` (`widgets/utils.py:138-151`) нормализует:
- `Callable` → как есть;
- `dict` → `StaticGetter(dict)` (всегда отдаёт этот словарь);
- `list`/`tuple` → `CompositeGetter(*map(ensure_data_getter, ...))`
  (последовательный `dict.update`, **последний getter перекрывает ключи**);
- `None` → `StaticGetter({})`;
- иначе → `InvalidWidgetType`.

`DataGetter` обычно пишут как `async def getter(dialog_manager, **kwargs) -> dict`.
В кваргах прилетает весь `middleware_data` + `dialog_manager`.

### 5.2. `PreviewAwareGetter` (`widgets/data/data_context.py:24-37`)

И Window, и Dialog оборачивают `(getter, preview_data)` в `PreviewAwareGetter`.
При вызове: если `dialog_manager.is_preview()` → вызывается `preview_getter`
(из `preview_data`), иначе — обычный `getter`. В боевом `DialogManager`
`is_preview()` всегда `False` (`manager.py:144`); в `FakeManager` (web-preview
tool) — всегда `True` (`tools/preview.py:157`).

### 5.3. Порядок мерджа (приоритет — снизу вверх)

`Window.load_data` (`window.py:113-119`):
```python
data = await dialog.load_data(manager)              # 1) базовый слой
data.update(await self.getter(**manager.middleware_data))   # 2) поверх — getter окна
```
`Dialog.load_data` (`dialog.py:115-120`):
```python
data = await manager.load_data()                    # 0) системный слой
data.update(await self.getter(**manager.middleware_data))   # 1) поверх — getter диалога
```
`DialogManager.load_data` (`manager.py:130-142`) даёт системные ключи:
```python
{ "dialog_data": context.dialog_data,
  "start_data":  context.start_data,
  "middleware_data": self._data,
  "event": self.event,
  **(custom_manager_getter or {}) }
```

**Итоговый приоритет при коллизии ключей (поздний перекрывает раннего):**

```
manager.load_data()  <  Dialog.getter  <  Window.getter
```

| Слой | Источник | Перекрывается кем |
|---|---|---|
| системный | `dialog_data`, `start_data`, `middleware_data`, `event` | Dialog.getter, Window.getter |
| диалог | `Dialog(getter=...)` — общие данные всех окон | Window.getter |
| окно | `Window(getter=...)` — данные конкретного окна | — (последний) |

> Подвох: ключ `event` (и др. системные) можно случайно перетереть своим
> getter'ом. Window.getter имеет высший приоритет — окно может переопределить
> данные диалога.

---

## 6. Preview-механизм Window

Назначение: статический рендер всех окон/переходов без реального Telegram —
для генерации графа (`tools/transitions.py`) и web-превью (`tools/web_preview.py`,
`tools/preview.py`).

- `preview_data` (Window и Dialog): данные, подставляемые вместо боевого getter
  через `PreviewAwareGetter`, когда `manager.is_preview()`. Так окно
  отрисовывается осмысленно без живых данных (пример:
  `preview_data={"name": "John Doe"}` в `example/subdialog.py:82,133`).
- `preview_add_transitions: list[Keyboard]`: «виртуальные» кнопки-переходы,
  которых в боевой клавиатуре нет, но которые нужны для графа. Используется в
  `tools/transitions.py:81-91` (`render_window` → `walk_keyboard`) — берётся
  через `getattr(window, "preview_add_transitions", None)`, разбираются
  `Start/SwitchTo/Next/Back/Cancel` для построения рёбер. Типичный кейс: окно с
  `MessageInput` без видимой кнопки `Next` — добавляют
  `preview_add_transitions=[Next()]`, чтобы граф показал переход
  (`example/subdialog.py:71,81`).
- В web-preview `FakeManager.is_preview() → True`, что также активирует
  ветки `is_preview` в виджетах (`Format`, `Multi`, `Select`, `Progress`):
  они отдают плейсхолдеры/«отмеченное» состояние вместо реальных значений.
- `preview_add_transitions` НЕ влияет на боевой рендер — это чисто
  инструментальная подсказка.

---

## 7. Связи с остальной библиотекой

- **Виджеты**: текст (`Const/Format/Multi/Case/...`), клавиатура
  (`Button/Group/Row/Start/Back/Next/SwitchTo/Cancel/Select/...`), ввод
  (`MessageInput/TextInput/...`), медиа (`Media/DynamicMedia`),
  `LinkPreview` — собираются в Window. (Зоны виджетов — отдельно.)
- **DialogManager** (`manager/manager.py`): драйвер lifecycle. Вызывает
  `process_start`/`process_close`/`process_result`, `render`, `show`.
  `show()` (`manager.py:380`) дергает `dialog.render(self)`, проставляет
  `show_mode`, отправляет/редактирует сообщение через `message_manager`.
- **NewMessage** (`api/entities/new_message.py:41`): датакласс — результат
  рендера; поля `chat, thread_id, business_connection_id, text, reply_markup,
  parse_mode, protect_content, show_mode (=AUTO), media, link_preview_options`.
- **MarkupFactory** (`api/internal/widgets.py:135`): дефолт
  `InlineKeyboardFactory` (`widgets/markup/inline_keyboard.py:12`) — добавляет
  intent-id к callback_data (`add_intent_id`) и собирает `InlineKeyboardMarkup`.
  Альтернатива — `ReplyKeyboardFactory` (для reply-клавиатур).
- **IntentFilter** (`context/intent_filter.py`): маршрутизация апдейтов в
  нужный Dialog по группе текущего состояния.
- **setup_dialogs** (`setup.py`): регистрирует middleware/handlers; диалоги
  собираются `collect_dialogs(router)`.
- **ShowMode/StartMode** (`api/entities/modes.py`): режимы отображения/старта,
  используются `DialogManager.start/show/done` (вне Window/Dialog, но влияют на
  результат рендера).

---

## 8. Рабочие примеры

### 8.1. Минимальный (quickstart, `docs/quickstart/summary.py`)
```python
class MySG(StatesGroup):
    main = State()

main_window = Window(
    Const("Hello, unknown person"),
    Button(Const("Useless button"), id="nothing"),
    state=MySG.main,
)
dialog = Dialog(main_window)

dp.include_router(dialog)
setup_dialogs(dp)

@dp.message(Command("start"))
async def start(message: Message, dialog_manager: DialogManager):
    await dialog_manager.start(MySG.main, mode=StartMode.RESET_STACK)
```

### 8.2. Getter уровня окна + диалога (мердж)
```python
async def dialog_getter(dialog_manager, **kwargs):
    return {"user": dialog_manager.middleware_data["event_from_user"].full_name}

async def window_getter(dialog_manager, **kwargs):
    return {"count": dialog_manager.dialog_data.get("count", 0)}

dialog = Dialog(
    Window(
        Format("Hi {user}! count={count}"),
        state=SG.main,
        getter=window_getter,        # перекрывает dialog_getter при коллизии
    ),
    getter=dialog_getter,            # общие данные всех окон
)
```

### 8.3. Хуки lifecycle (по `example/subdialog.py`)
```python
async def on_finish(callback, button, manager: DialogManager):
    await manager.done({"name": manager.dialog_data["name"]})   # вернёт результат родителю

async def process_result(start_data, result, manager: DialogManager):
    if result:
        manager.dialog_data["name"] = result["name"]

name_dialog = Dialog(
    Window(Const("What is your name?"), Cancel(), MessageInput(name_handler),
           state=NameSG.input, preview_add_transitions=[Next()]),
    Window(Format("Your name is `{name}`, it is correct?"),
           Row(Back(Const("No")), Button(Const("Yes"), id="yes", on_click=on_finish)),
           state=NameSG.confirm, getter=get_name_data,
           preview_add_transitions=[Cancel()], preview_data={"name": "John Doe"}),
)
main_menu = Dialog(
    Window(..., state=MainSG.main, getter=get_main_data,
           preview_data={"name": "John Doe"}),
    on_process_result=process_result,    # принимает результат закрытого name_dialog
)
```

### 8.4. LaunchMode (по `example/launch_modes.py`)
```python
banner   = Dialog(Window(..., state=BannerSG.default),  launch_mode=LaunchMode.EXCLUSIVE)
main_menu= Dialog(Window(..., state=MainSG.default),    launch_mode=LaunchMode.ROOT)
product  = Dialog(Window(..., state=Product.show, getter=product_getter),
                  launch_mode=LaunchMode.SINGLE_TOP)
```

---

## 9. Подводные камни / краевые случаи

1. **Параметры после `*widgets` — keyword-only.** `Window(text, MySG.main)` не
   сработает: нужно `state=MySG.main`. То же для всех опций окна/диалога.
2. **Голый `Callable` в `*widgets` = input-хендлер**, не getter. Getter — только
   через `getter=`. Передадите функцию позиционно — она станет
   `MessageInput`-обработчиком.
3. **Только одно `Media` и один `LinkPreview` на окно** — иначе `ValueError`
   ещё на этапе конструирования.
4. **`disable_web_page_preview` deprecated**; даже `False` создаёт
   `LinkPreview(is_disabled=True)` и кидает `DeprecationWarning`. Конфликт с
   виджетом `LinkPreview` → `ValueError`. Используйте виджет `LinkPreview`.
5. **`parse_mode` по умолчанию `UNSET_PARSE_MODE`**, а не `None`: это значит
   «брать из `Bot(default=DefaultBotProperties(parse_mode=...))`». Явный `None`
   отключает форматирование для окна.
6. **Все окна — одна `StatesGroup`.** Чужая группа или дубликат состояния →
   `ValueError` в конструкторе. Группа берётся из ПЕРВОГО окна.
7. **Порядок окон важен** для `Next()`/`Back()`/`manager.next()` (индексация
   `states()`).
8. **`Dialog.include_router()` запрещён** (`TypeError`). Композиция диалогов —
   через внешний `Router` / `Dispatcher`.
9. **`Window.find()` не ищет внутри `link_preview`** — id внутри `LinkPreview`
   недоступен через `manager.find()`.
10. **Приоритет getter'ов:** `manager` < `Dialog.getter` < `Window.getter`.
    Легко затереть системные ключи (`event`, `dialog_data`, `start_data`).
11. **`on_close` вызывается ДО удаления контекста** (стек ещё содержит
    закрываемый диалог); **`on_process_result` — ПОСЛЕ** возврата к родителю.
    Window-хук `on_process_result` пропускается, если Dialog-хук сменил контекст.
12. **`_need_refresh`:** в группах при `processed == False` авто-перерисовки НЕ
    будет (только в личке). Если обработчик ничего не вернул `True`, в группе
    окно не обновится само.
13. **intent-id срезается из callback_data** до передачи в виджет
    (`remove_intent_id`); не рассчитывайте увидеть служебный префикс в
    `on_click`.
14. **`show_mode` окно не задаёт** — это делает `DialogManager.show()`
    (`ShowMode.AUTO` → вычисляется по типу события).
