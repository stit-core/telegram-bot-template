---
zone: 10
title: "Кнопки навигации/состояния: Start, SwitchTo, Next, Back, Cancel"
source_repo: aiogram_dialog
source_ref: "develop @ 08abdf0 (2026-05-02)"
aiogram_min: ">=3.14.0"
primary_file: src/aiogram_dialog/widgets/kbd/state.py
related:
  - src/aiogram_dialog/widgets/kbd/button.py
  - src/aiogram_dialog/widgets/kbd/base.py
  - src/aiogram_dialog/widgets/widget_event.py
  - src/aiogram_dialog/manager/manager.py
  - src/aiogram_dialog/dialog.py
  - src/aiogram_dialog/api/entities/modes.py
  - src/aiogram_dialog/api/entities/launch_mode.py
  - src/aiogram_dialog/api/protocols/dialog.py (CancelEventProcessing)
  - tests/test_transitions.py
  - docs/transitions/index.rst
tags: [keyboard, transitions, navigation, start, switch_to, next, back, cancel, StartMode, ShowMode]
---

# Зона 10. Кнопки навигации/состояния: `Start`, `SwitchTo`, `Next`, `Back`, `Cancel`

Все пять виджетов живут в одном файле `src/aiogram_dialog/widgets/kbd/state.py` (189 строк).
Это «кнопки-переходы»: каждая при клике вызывает соответствующий метод `DialogManager`
(`start` / `switch_to` / `next` / `back` / `done`). Любую из них можно эквивалентно заменить
обычным `Button(..., on_click=...)`, вручную дёргающим тот же метод менеджера
(см. `equal_solution.py` в каждой папке доки и `docs/transitions/switch.py`).

---

## 1. Архитектура: как кнопка превращается в переход

### 1.1 Базовый класс `EventProcessorButton`

`state.py:20-35`

```python
class EventProcessorButton(Button, WidgetEventProcessor):
    async def process_event(self, event, source, manager, *args, **kwargs):
        await self._on_click(event, self, manager)

    async def _on_click(self, callback, button, manager):
        raise NotImplementedError
```

Все пять кнопок наследуют `EventProcessorButton`, который сам наследует
`Button` (`button.py:24`) и `WidgetEventProcessor` (`widget_event.py:9`).
Ключевой трюк: в `__init__` каждой кнопки в базовый `Button` передаётся
`on_click=self._on_click` — то есть встроенный переход регистрируется как
«официальный» `on_click` виджета. Пользовательский же колбэк сохраняется отдельно
в `self.user_on_click` и вызывается изнутри `_on_click` ПЕРЕД переходом.

### 1.2 Полный путь клика (callback)

1. aiogram-роутер `Dialog._callback_handler` (`dialog.py:141-158`) ловит `CallbackQuery`.
   Перед этим `remove_intent_id` (`utils.py:220`) отрезает `intent_id` (префикс до символа
   `\x1D` = `CB_SEP`) от `callback.data`, оставляя «чистую» `callback_data` = `widget_id`.
2. `window.process_callback` → проходит по дереву виджетов → `Keyboard.process_callback`
   (`base.py:62-82`): если `callback.data == self.widget_id`, дёргается `_process_own_callback`.
3. `Button._process_own_callback` (`button.py:38-45`):
   `await self.on_click.process_event(callback, self, manager)` → `return True`.
   Здесь `self.on_click` — это `SimpleEventProcessor`, обёрнутый из `self._on_click`
   (см. `ensure_event_processor`, `widget_event.py:38`).
4. Срабатывает `_on_click` конкретной кнопки → сначала `user_on_click` (если задан),
   затем метод менеджера (`manager.start/switch_to/next/back/done`).
5. После обработки `Dialog._callback_handler` решает, надо ли перерисовать окно
   (`_need_refresh`, `dialog.py:160-178`) и вызывает `dialog_manager.answer_callback()`
   (закрывает «часики» на кнопке).

> ВАЖНО: `_process_own_callback` всегда `return True`. Поэтому даже если переход НЕ сменил
> состояние/контекст, в приватном чате окно всё равно перерисуется (см. `_need_refresh`).

### 1.3 `WidgetEventProcessor` / `ensure_event_processor`

`widget_event.py`. `Button.on_click` всегда нормализуется через `ensure_event_processor`
(`button.py:35`): callable → `SimpleEventProcessor`, а уже готовый `WidgetEventProcessor`
остаётся как есть. У переходных кнопок `on_click` = `self._on_click` (bound-метод, callable),
значит обёрнут в `SimpleEventProcessor`. Сами кнопки тоже реализуют `WidgetEventProcessor`
(через `EventProcessorButton`) — это позволяет использовать их как обработчики событий
в составных виджетах.

---

## 2. Сигнатуры и поведение

Общие для всех аргументы (из `Button`/`Keyboard`/`Actionable`):

| Аргумент | Тип | Назначение |
|---|---|---|
| `text` | `TextWidget` (напр. `Const`, `Format`) | Текст кнопки. Рендерится через `text.render_text(data, manager)`. |
| `id` | `str` | `widget_id`; служит и `callback_data` (см. §4). Валидируется `^[a-zA-Z0-9_.]+$` (`action.py:8`). |
| `on_click` | `OnClick | None` | Пользовательский колбэк `(CallbackQuery, Button, DialogManager) -> Awaitable`. |
| `when` | `WhenCondition` | Условие показа кнопки (`bool`/ключ в data/предикат). |
| `show_mode` | `ShowMode | None` | Переопределяет режим показа для перерисовки после перехода. |
| `style` | `StyleWidget` | По умолчанию `EMPTY_STYLE`. |

> NB: у `OnClick` второй параметр аннотирован как `Button`, НО фактически в `_on_click`
> передаётся `self` — то есть сам объект `Start`/`Cancel`/…, а не базовый `Button`
> (`state.py:63,92,120,149,182`). Это удобно: внутри пользовательского колбэка доступны
> `button.state`, `button.result` и т.п.

### 2.1 `Start` — запуск другого диалога

`state.py:153-188`

```python
Start(
    text: TextWidget,
    id: str,                       # ОБЯЗАТЕЛЕН, без значения по умолчанию
    state: State,                  # стартовое состояние целевого диалога
    data: Data = None,             # start_data, доступна как manager.start_data
    on_click: OnClick | None = None,
    show_mode: ShowMode | None = None,
    mode: StartMode = StartMode.NORMAL,
    when: WhenCondition = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

`_on_click` (`state.py:177-188`):
```python
if self.user_on_click:
    await self.user_on_click(callback, self, manager)
await manager.start(
    state=self.state, data=self.start_data,
    mode=self.mode, show_mode=self.show_mode,
)
```

- Вызывает `manager.start(...)` (`manager.py:241-259`).
- `data` сохраняется в новый контекст и читается через `manager.start_data` / в геттере.
- Возврат: `None`. Эффект — на стек добавляется новый контекст (NORMAL/NEW_STACK) или
  стек сбрасывается и стартует новый диалог (RESET_STACK).
- `id` ОБЯЗАТЕЛЕН (нет дефолта) — потому что в одном окне обычно несколько разных `Start`.

### 2.2 `SwitchTo` — переход к окну ВНУТРИ текущего диалога

`state.py:38-64`

```python
SwitchTo(
    text: TextWidget,
    id: str,                       # ОБЯЗАТЕЛЕН
    state: State,                  # целевое окно (того же StatesGroup!)
    on_click: OnClick | None = None,
    when: WhenCondition = None,
    show_mode: ShowMode | None = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

`_on_click`: `user_on_click` → `await manager.switch_to(self.state, show_mode=self.show_mode)`.

- `manager.switch_to` (`manager.py:355-368`): меняет ТОЛЬКО `context.state`, контекст
  (`dialog_data`, `widget_data`, `start_data`) сохраняется.
- ЖЁСТКАЯ ПРОВЕРКА: `context.state.group != state.group` → `ValueError`
  «Cannot switch to another state group». Нельзя `SwitchTo` в чужой диалог — для этого `Start`.
- `id` ОБЯЗАТЕЛЕН.

### 2.3 `Next` / `Back` — навигация по списку окон диалога

`state.py:67-93` (`Next`), `state.py:96-121` (`Back`)

```python
Next(
    text: TextWidget = NEXT_TEXT,  # Const("Next")
    id: str = "__next__",          # дефолтный id!
    on_click: OnClick | None = None,
    show_mode: ShowMode | None = None,
    when: WhenCondition = None,
    style: StyleWidget = EMPTY_STYLE,
)
Back(
    text: TextWidget = BACK_TEXT,  # Const("Back")
    id: str = "__back__",          # дефолтный id!
    ...
)
```

`Next._on_click`: `user_on_click` → `await manager.next(self.show_mode)`.
`Back._on_click`: `user_on_click` → `await manager.back(self.show_mode)`.

Как определяется «соседнее» окно — `manager.py:327-353`:
```python
states = self.dialog().states()             # порядок = порядок Window в Dialog(...)
current_index = states.index(context.state)
# next: states[current_index + 1]; back: states[current_index - 1]
await self.switch_to(new_state, show_mode)  # т.е. это обёртка над switch_to
```

- Порядок окон = порядок аргументов `Window` в конструкторе `Dialog(...)`
  (`dialog.py:55-67`, `self._states`). Состояния в `StatesGroup` НЕ обязаны быть в том же
  порядке — важен порядок ИМЕННО в `Dialog`.
- Текст/иконка по умолчанию: `Next`→"Next", `Back`→"Back" (`state.py:15-16`).
- У `Back` есть лишняя строка `self.callback_data = id` (`state.py:111`) — это рудимент,
  на маршрутизацию не влияет (она идёт через `widget_id`/`_own_callback_data`).

### 2.4 `Cancel` — закрытие текущего диалога

`state.py:124-150`

```python
Cancel(
    text: TextWidget = CANCEL_TEXT,  # Const("Cancel")
    id: str = "__cancel__",          # дефолтный id!
    result: Any = None,              # результат, попадёт в on_process_result родителя
    on_click: OnClick | None = None,
    when: WhenCondition = None,
    show_mode: ShowMode | None = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

`_on_click`: `user_on_click` → `await manager.done(self.result, show_mode=self.show_mode)`.

`manager.done` (`manager.py:196-217`):
1. `dialog().process_close(result, self)` → колбэк `on_close` диалога.
2. `mark_closed()` — снимает текущий контекст со стека (`stack.pop()`), удаляет его из storage.
3. Если стек опустел → `_process_last_dialog_result` → `_remove_kbd()` (убирает клавиатуру).
4. Иначе — `dialog.process_result(old_start_data, result, self)` у РОДИТЕЛЬСКОГО диалога
   (вызывает его `on_process_result`), затем перерисовка родительского окна.

- `result` доступен родителю в `on_process_result(start_data, result, manager)`
  (см. `docs/transitions/done.py`).

---

## 3. `StartMode` и `ShowMode`

### 3.1 `StartMode` (`api/entities/modes.py:37-65`)

| Режим | Значение | Поведение `manager.start` (`manager.py:251-259`) |
|---|---|---|
| `NORMAL` | по умолчанию | `_start_normal`: новый контекст ПОВЕРХ текущего стека. |
| `RESET_STACK` | — | `reset_stack(remove_keyboard=False)` затем `_start_normal`: чистит весь стек, стартует заново. |
| `NEW_STACK` | — | `_start_new_stack`: новый отдельный стек (новое сообщение, независимое поведение). |

Подводные камни:
- В обычном `Start` без `RESET_STACK` повторные запуски КОПЯТ контексты в стеке.
  Стек ограничен ~100 диалогами; переполнение «съест память» (docs/transitions/index.rst).
  Поэтому корневой/`/start` хендлер обычно делает `start(..., mode=StartMode.RESET_STACK)`
  (см. `tests/test_transitions.py:30-31`, `test_reset_stack` гоняет 200 рестартов).
- `LaunchMode` диалога может неявно сбросить стек НЕЗАВИСИМО от `StartMode`:
  `ROOT`/`EXCLUSIVE` → `reset_stack` (`manager.py:315-325`), `SINGLE_TOP` → заменяет верхний.
  Старт поверх `EXCLUSIVE`-диалога запрещён (`ValueError`, `manager.py:292-296`).

### 3.2 `ShowMode` (`api/entities/modes.py:4-34`)

`AUTO` (дефолт), `EDIT`, `SEND`, `DELETE_AND_SEND`, `NO_UPDATE`.
Все переходные кнопки прокидывают `show_mode` дальше в метод менеджера. Если `None` —
используется текущий `manager.show_mode` (по умолчанию `AUTO` → `_calc_show_mode`,
`manager.py:510-527`).

- `DELETE_AND_SEND`: при возрасте сообщения > 48ч Telegram не даст удалить.
- `NO_UPDATE`: переход состояния произойдёт, но окно НЕ перерисуется
  (`show` сразу выходит, `manager.py:385-387`). Полезно, если рендерить будешь сам позже.

---

## 4. `callback_data`, `id` и маршрутизация

- `_own_callback_data()` = `widget_id` (`base.py:54`). Кнопка-одиночка узнаёт себя по
  точному совпадению `callback.data == self.widget_id` (`base.py:68`).
- При рендере к `callback_data` каждой кнопки добавляется `intent_id` текущего контекста
  через `add_intent_id` (`utils.py:211`): итоговая строка = `f"{intent_id}\x1D{widget_id}"`.
  Это значит, что один и тот же `widget_id` в разных контекстах/стеках корректно
  разделяется, а клик по «старой» кнопке от прошлого контекста не сработает в новом.
- Telegram ограничивает `callback_data` 64 БАЙТАМИ. Сюда входит и `intent_id`, и `widget_id`.
  Длинные осмысленные `id` у `Start`/`SwitchTo` могут переполнить лимит — держи их короткими.
- `id` валидируется регуляркой `^[a-zA-Z0-9_.]+$` (`action.py:8-15`); недопустимые символы
  (пробел, `:`, кириллица, `-`) → `InvalidWidgetIdError`. Помни: `_item_callback_data`
  использует `:` как разделитель, поэтому `:` в `id` запрещён по смыслу.

---

## 5. `EventProcessing` / `CancelEventProcessing`

В задании упомянут «EventProcessing» — в `state.py` отдельного такого класса НЕТ.
Релевантные сущности:

- `WidgetEventProcessor` (`widget_event.py:9`) — протокол обработчика событий; именно его
  реализует `EventProcessorButton` (отсюда «EventProcessor» в названии базового класса).
- `CancelEventProcessing` — исключение (`api/protocols/dialog.py:14`). Его может бросить
  ЛЮБОЙ обработчик внутри `process_callback`/`process_message`, чтобы сказать диалогу:
  «я обработал, но перерисовку/дальнейшую обработку не делай». Ловится в
  `Dialog._callback_handler` (`dialog.py:154`) и `_message_handler` (`dialog.py:136`):
  `processed = False`, поэтому `_need_refresh` вернёт `False` в группах
  (в приватном чате окно всё равно может перерисоваться — `dialog.py:174-177`).

> Практика для переходных кнопок: бросать `CancelEventProcessing` из `user_on_click`
> можно, чтобы прервать выполнение ДО встроенного перехода — исключение «пролетит» сквозь
> `_on_click` и `process_event`, и `manager.start/switch_to/...` НЕ вызовется. Это
> единственный штатный способ «отменить» встроенный переход (см. §6).

---

## 6. Взаимодействие `user_on_click` и встроенного перехода

Порядок строго фиксирован во всех пяти кнопках:

```python
if self.user_on_click:
    await self.user_on_click(callback, self, manager)   # 1. сначала ТВОЙ колбэк
await manager.<transition>(...)                          # 2. потом встроенный переход
```

Следствия и краевые случаи:
- Нельзя «вставить» логику ПОСЛЕ перехода через `on_click` этой же кнопки — переход всегда
  последний. Если нужна логика после, используй `on_process_result` (для `Start`/`Cancel`)
  или просто обычный `Button` с ручным вызовом метода в нужном порядке.
- ОТМЕНИТЬ встроенный переход из `user_on_click` можно только выбросив исключение
  (например `CancelEventProcessing`) — `return` ничего не отменяет, т.к. возвращаемое
  значение колбэка игнорируется.
- Если внутри `user_on_click` ты сам сделал `manager.start/done/switch_to`, то встроенный
  переход выполнится ВТОРЫМ поверх твоего — легко получить двойной переход/неожиданный стек.
  Не смешивай: либо переходная кнопка, либо ручной `Button`.
- `user_on_click` получает `self` (конкретную кнопку), а не «чистый» `Button` — можно читать
  её атрибуты (`button.state`, `button.result`, `button.start_data`).

---

## 7. Подводные камни и краевые случаи

| Ситуация | Что происходит | Ссылка |
|---|---|---|
| `Next` на ПОСЛЕДНЕМ окне | `ValueError` «Cannot go to a non-existent state» (`current_index+1 >= len(states)`) | `manager.py:331-337` |
| `Back` на ПЕРВОМ окне | `ValueError` (`current_index-1 < 0`) | `manager.py:345-351` |
| `SwitchTo`/`switch_to` в чужой `StatesGroup` | `ValueError` «Cannot switch to another state group» | `manager.py:362-366` |
| `Cancel`/`done` на КОРНЕВОМ (единственном) диалоге | Стек опустошается, клавиатура убирается (`_remove_kbd`), контекст = `None`. Окна больше нет. Тест `test_finish_last` проверяет: `not last_message.reply_markup` | `manager.py:206-211`, `tests/test_transitions.py:108-120` |
| Несколько `Next`/`Back`/`Cancel` с `on_click` в одном окне | Дефолтные `id` совпадут → конфликт `callback_data`. Доки прямо требуют задавать РАЗНЫЕ `id`, если есть `on_click` | `docs/transitions/index.rst` (note), `state.py:71/100/128` |
| `id` у `Start`/`SwitchTo` | ОБЯЗАТЕЛЕН (нет дефолта). Забыл — `TypeError` при создании | `state.py:42,157` |
| Старт того же диалога без `RESET_STACK` | Контексты копятся в стеке (лимит ~100), память течёт | `docs/transitions/index.rst`, `tests/test_transitions.py:123-137` |
| `Start` поверх `EXCLUSIVE`-диалога | `ValueError` «Cannot start dialog on top of one with launch_mode==SINGLE» | `manager.py:292-296` |
| Длинный `id` у `Start`/`SwitchTo` | Риск превысить лимит callback_data 64 байта (вместе с `intent_id`) | §4 |
| Невалидные символы в `id` (`:`, пробел, дефис, кириллица) | `InvalidWidgetIdError` | `action.py:8-15` |
| Клик по «старой» кнопке прошлого контекста | Не сработает: `intent_id` в callback_data не совпадёт с текущим | `utils.py:211,220` |
| `_process_own_callback` всегда `True` | В приватном чате окно перерисуется даже без смены состояния | `button.py:45`, `dialog.py:171-177` |

---

## 8. Связи с остальной библиотекой

- Базовый `Button` (`button.py:24`) — все пять наследуют его рендер/маршрутизацию.
- `Keyboard` (`base.py:15`) — `process_callback`, `_own_callback_data`, `find`, оператор `|`
  (`Or`-композиция). `find(id)` ищет виджет по `id` для `manager.find(...)`.
- `DialogManager` (`manager.py`) — реальные методы `start/switch_to/next/back/done` (см. §2).
- `Dialog` (`dialog.py`) — порядок `Window` задаёт последовательность для `Next`/`Back`
  (`states()`), ловит `CancelEventProcessing`, вызывает `on_close`/`on_process_result`.
- `LaunchMode` (`launch_mode.py`) — взаимодействует со `StartMode` при `Start`.
- Тексты — `Const`/`Format` из `widgets.text`. Раскладка — `Row`/`Column`/`Group`
  (`docs/transitions/buttons.py` оборачивает `Back`+`Next` в `Row`).
- Тест-инструменты — `BotClient`, `MockMessageManager`, `InlineButtonTextLocator`
  (`tests/test_transitions.py`) кликают по тексту кнопки; используй для unit-тестов переходов.

---

## 9. Готовые рабочие примеры

### 9.1 Навигация внутри диалога (`SwitchTo` + `Next`/`Back`)

```python
from aiogram.filters.state import State, StatesGroup
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import Back, Next, Row, SwitchTo
from aiogram_dialog.widgets.text import Const

class DialogSG(StatesGroup):
    first = State(); second = State(); third = State()

dialog = Dialog(
    Window(Const("First"),
           SwitchTo(Const("To second"), id="sec", state=DialogSG.second),
           state=DialogSG.first),
    Window(Const("Second"),
           Row(Back(), Next()),          # дефолтные id __back__/__next__ ок: без on_click
           state=DialogSG.second),
    Window(Const("Third"), Back(), state=DialogSG.third),
)
```

### 9.2 `Start` с данными + `Cancel` с результатом

```python
from typing import Any
from aiogram.filters.state import State, StatesGroup
from aiogram_dialog import Data, Dialog, DialogManager, StartMode, Window
from aiogram_dialog.widgets.kbd import Cancel, Start
from aiogram_dialog.widgets.text import Const, Format

class MainSG(StatesGroup):  first = State()
class SubSG(StatesGroup):   first = State()

async def on_result(start_data: Data, result: Any, manager: DialogManager):
    print("subdialog result:", result)          # сюда прилетит Cancel.result

main = Dialog(
    Window(Const("Main"),
           Start(Const("Open sub"), id="open", state=SubSG.first,
                 data={"user_id": 42}, mode=StartMode.NORMAL),
           state=MainSG.first),
    on_process_result=on_result,
)
sub = Dialog(
    Window(Format("Sub, got: {start_data[user_id]}"),
           Cancel(Const("Done"), result={"status": "ok"}),
           state=SubSG.first),
)
```

### 9.3 `user_on_click` ПЕРЕД переходом + отмена через исключение

```python
from aiogram_dialog import CancelEventProcessing
from aiogram_dialog.widgets.kbd import Next

async def guard(callback, button, manager):
    if not manager.dialog_data.get("agreed"):
        await callback.answer("Сначала подтвердите", show_alert=True)
        raise CancelEventProcessing      # переход manager.next() НЕ выполнится

# код после raise (manager.next) не вызовется
win_next = Next(on_click=guard)
```

---

## 10. Шпаргалка соответствий кнопка → метод менеджера

| Кнопка | Метод | Семантика | Дефолтный `id` | `id` обязателен |
|---|---|---|---|---|
| `Start` | `manager.start(state, data, mode, show_mode)` | запуск ДРУГОГО диалога | — | да |
| `SwitchTo` | `manager.switch_to(state, show_mode)` | окно ВНУТРИ диалога | — | да |
| `Next` | `manager.next(show_mode)` | следующее окно по порядку `Dialog` | `__next__` | нет |
| `Back` | `manager.back(show_mode)` | предыдущее окно по порядку `Dialog` | `__back__` | нет |
| `Cancel` | `manager.done(result, show_mode)` | закрыть текущий диалог | `__cancel__` | нет |
