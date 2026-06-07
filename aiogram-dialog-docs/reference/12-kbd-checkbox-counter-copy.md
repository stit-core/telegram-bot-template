---
zone: 12
title: "Checkbox, Counter, CopyText — виджеты клавиатуры с внутренним состоянием"
source_repo: aiogram_dialog
source_ref: "develop @ 08abdf0 (2026-05-02)"
aiogram_min: "3.14.0"
files:
  - src/aiogram_dialog/widgets/kbd/checkbox.py
  - src/aiogram_dialog/widgets/kbd/counter.py
  - src/aiogram_dialog/widgets/kbd/copy.py
  - src/aiogram_dialog/widgets/kbd/base.py
  - src/aiogram_dialog/widgets/common/action.py
  - src/aiogram_dialog/widgets/common/managed.py
  - src/aiogram_dialog/widgets/widget_event.py
docs:
  - docs/widgets/keyboard/checkbox/
  - docs/widgets/keyboard/counter/
  - docs/widgets/keyboard/copy_text/
tests:
  - tests/widgets/kbd/test_checkbox.py
  - tests/widgets/kbd/test_counter.py
examples:
  - example/mega/bot_dialogs/counter.py
tags: [keyboard, stateful, widget_data, checkbox, counter, copytext, managed]
---

# Зона 12 — Checkbox, Counter, CopyText

## 0. Обзор и общая модель

Это группа inline-кнопочных виджетов, два из которых (**Checkbox**, **Counter**)
**хранят собственное состояние**, а третий (**CopyText**) — stateless-обёртка над
нативной Telegram-кнопкой `copy_text` (Bot API 7.11+).

Все три наследуются от `Keyboard`
(`src/aiogram_dialog/widgets/kbd/base.py:15`), которая, в свою очередь, тянет:

| Базовый класс | Откуда | Что даёт |
|---|---|---|
| `Actionable` | `widgets/common/action.py:11` | `widget_id`, `find()`, `get_widget_data()`, `set_widget_data()` |
| `Whenable` | `widgets/common/when.py` | условие показа `when=` через `is_(data, manager)` |
| `KeyboardWidget` | `api/internal` | протокол клавиатурного виджета |

### Где живёт состояние

И Checkbox, и Counter хранят значение в **`widget_data` текущего контекста диалога**:

```python
# widgets/common/action.py:23
def get_widget_data(self, manager, default):
    return manager.current_context().widget_data.setdefault(self.widget_id, default)

def set_widget_data(self, manager, value):
    manager.current_context().widget_data[self.widget_id] = value
```

Ключ хранилища — это `widget_id` (то есть параметр `id=`). Важные следствия:

- **`id` обязателен** для Checkbox и Counter (без него `widget_data[None]`, состояние
  не привяжется и будет конфликтовать). `CopyText` `id` НЕ принимает вовсе.
- **`default` применяется лениво и «прилипает»**: `setdefault` записывает default в
  `widget_data` при **первом** чтении значения, дальше default уже не влияет — состояние
  живёт в контексте до закрытия диалога. См. подводные камни §5.
- Состояние раздельно для каждого **открытого** диалога (стек), но **все окна одного
  диалога делят одно хранилище** → два виджета с одинаковым `id` в разных окнах одного
  диалога делят состояние (docs/widgets/keyboard/checkbox/index.rst:23).

### Доступ к виджету из getter / хэндлера

`manager.find(id)` (`manager/manager.py:538`) возвращает не сам виджет, а его
**managed-обёртку** через `widget.managed(self)`:

```python
def find(self, widget_id) -> Any | None:
    widget = self.dialog().find(widget_id)
    if not widget:
        return None
    return widget.managed(self)   # ManagedCheckbox / ManagedCounter
```

Поэтому в getter вы получаете `ManagedCheckbox` / `ManagedCounter` с привязанным
`manager`, у которого методы уже без аргумента `manager`.

---

## 1. Checkbox

`src/aiogram_dialog/widgets/kbd/checkbox.py`

Иерархия: `BaseCheckbox(Keyboard, ABC)` → `Checkbox`. `ManagedCheckbox` — обёртка.

### 1.1. Сигнатура `Checkbox.__init__` (checkbox.py:107)

```python
Checkbox(
    checked_text: Text,                  # позиционный 1: текст в состоянии "отмечено"
    unchecked_text: Text,                # позиционный 2: текст в состоянии "не отмечено"
    id: str,                             # обязателен
    on_click: OnStateChanged | WidgetEventProcessor | None = None,
    on_state_changed: OnStateChanged | None = None,
    default: bool = False,
    when: WhenCondition = None,
    checked_style: StyleWidget = EMPTY_STYLE,    # стиль кнопки (aiogram 3.x ButtonStyle)
    unchecked_style: StyleWidget = EMPTY_STYLE,
)
```

> `checked_text` / `unchecked_text` — позиционные. В примерах библиотеки они передаются
> позиционно (`Checkbox(Const("✓ Checked"), Const("Unchecked"), id="check")`).

### 1.2. Параметры

| Параметр | Тип | Default | Назначение |
|---|---|---|---|
| `checked_text` | `Text` | — | текст кнопки, когда checked=True |
| `unchecked_text` | `Text` | — | текст кнопки, когда checked=False |
| `id` | `str` | — | ключ состояния в `widget_data`; обязателен |
| `on_click` | callback/processor | `None` | вызывается на любой клик ДО смены состояния |
| `on_state_changed` | callback | `None` | вызывается ПОСЛЕ изменения состояния (через `set_checked`) |
| `default` | `bool` | `False` | начальное состояние (лениво, см. §5) |
| `when` | условие | `None` | показывать/скрывать виджет |
| `checked_style` / `unchecked_style` | `StyleWidget` | `EMPTY_STYLE` | стиль кнопки aiogram (например цвет) на каждое состояние |

### 1.3. Тип `OnStateChanged` (checkbox.py:18)

```python
OnStateChanged = Callable[[ChatEvent, "ManagedCheckbox", DialogManager], Awaitable]
```

Сигнатура колбэка:

```python
async def on_changed(event: ChatEvent, checkbox: ManagedCheckbox, manager: DialogManager):
    ...
```

- `event` — на реальном клике это `CallbackQuery`; при программном `set_checked` — то,
  что передали (`manager.event`).
- `checkbox` — `ManagedCheckbox`, уже с актуальным состоянием (state записан ДО колбэка).

### 1.4. Механика переключения

`_process_item_callback` (checkbox.py:72):

1. Из callback_data берётся ТЕКУЩЕЕ (на момент отрисовки кнопки) значение:
   в `_render_keyboard` оно зашивается как `int(checked)` → `"0"`/`"1"`
   (checkbox.py:58,67).
2. `checked = data != "0"` — восстановление текущего состояния из callback_data.
3. Вызывается `on_click`.
4. `set_checked(callback, not checked, manager)` — инвертирование.

```python
async def _process_item_callback(self, callback, data, dialog, manager):
    checked = data != "0"
    await self.on_click.process_event(callback, self.managed(manager), manager)
    await self.set_checked(callback, not checked, manager)   # инверсия
    return True
```

> Важно: инвертируется значение **из callback_data отрисованной кнопки**, а не из
> текущего `widget_data`. На практике совпадает, но это защищает от двойного клика по
> устаревшей кнопке (toggle всегда относительно того, что видел пользователь).

`is_checked` / `set_checked` на самом классе (checkbox.py:128):

```python
def is_checked(self, manager) -> bool:
    return self.get_widget_data(manager, self.default)

async def set_checked(self, event, checked: bool, manager) -> None:
    self.set_widget_data(manager, checked)
    await self.on_state_changed.process_event(event, self.managed(manager), manager)
```

### 1.5. `ManagedCheckbox` (checkbox.py:144)

`ManagedWidget[Checkbox]` (`__getattr__` проксирует на сам виджет, `managed.py:14`).

| Метод | Возврат | Эффект |
|---|---|---|
| `is_checked()` | `bool` | текущее состояние (читает `widget_data`, может записать default) |
| `set_checked(checked: bool)` | `None` (awaitable) | пишет состояние, **триггерит `on_state_changed`**, НЕ триггерит `on_click` |

```python
class ManagedCheckbox(ManagedWidget[Checkbox]):
    def is_checked(self) -> bool:
        return self.widget.is_checked(self.manager)
    async def set_checked(self, checked: bool) -> None:
        return await self.widget.set_checked(self.manager.event, checked, self.manager)
```

> `set_checked` НЕ переключает (не toggle), а **устанавливает абсолютное** значение.
> Чтобы программно инвертировать: `await cb.set_checked(not cb.is_checked())`.

### 1.6. Пример (docs/widgets/keyboard/checkbox/example.py)

```python
from aiogram_dialog import DialogManager, ChatEvent
from aiogram_dialog.widgets.kbd import Checkbox, ManagedCheckbox
from aiogram_dialog.widgets.text import Const

async def check_changed(event: ChatEvent, checkbox: ManagedCheckbox, manager: DialogManager):
    print("Check status changed:", checkbox.is_checked())

check = Checkbox(
    Const("✓  Checked"),
    Const("Unchecked"),
    id="check",
    default=True,                 # отмечен по умолчанию
    on_state_changed=check_changed,
)
```

Чтение в getter:

```python
async def getter(dialog_manager: DialogManager, **kwargs):
    cb: ManagedCheckbox = dialog_manager.find("check")
    return {"is_on": cb.is_checked()}
```

---

## 2. Counter

`src/aiogram_dialog/widgets/kbd/counter.py`. Класс `Counter(Keyboard)`,
обёртка `ManagedCounter`.

Назначение: ввод числа кнопками `−` / `значение` / `+` (docstring counter.py:38).

### 2.1. Сигнатура `Counter.__init__` (counter.py:45)

```python
Counter(
    id: str,
    plus: Text | None = Const("+"),          # PLUS_TEXT
    minus: Text | None = Const("-"),         # MINUS_TEXT
    text: Text | None = Format("{value:g}"), # DEFAULT_COUNTER_TEXT
    min_value: float = 0,
    max_value: float = 999999,
    increment: float = 1,
    default: float = 0,
    cycle: bool = False,
    on_click: OnCounterEventVariant = None,
    on_text_click: OnCounterEventVariant = None,
    on_value_changed: OnCounterEventVariant = None,
    when: WhenCondition = None,
    plus_style: StyleWidget = EMPTY_STYLE,
    minus_style: StyleWidget = EMPTY_STYLE,
    value_style: StyleWidget = EMPTY_STYLE,
)
```

Константы по умолчанию (counter.py:32):
`PLUS_TEXT = Const("+")`, `MINUS_TEXT = Const("-")`, `DEFAULT_COUNTER_TEXT = Format("{value:g}")`.

### 2.2. Параметры

| Параметр | Тип | Default | Назначение |
|---|---|---|---|
| `id` | `str` | — | ключ состояния; обязателен |
| `plus` | `Text \| None` | `Const("+")` | текст кнопки «+». `None` → кнопки нет |
| `minus` | `Text \| None` | `Const("-")` | текст кнопки «−». `None` → кнопки нет |
| `text` | `Text \| None` | `Format("{value:g}")` | текст центральной кнопки значения. `None` → кнопки нет |
| `min_value` | `float` | `0` | нижняя граница (включительно) |
| `max_value` | `float` | `999999` | верхняя граница (включительно) |
| `increment` | `float` | `1` | шаг ±. Может быть дробным |
| `default` | `float` | `0` | стартовое значение (лениво) |
| `cycle` | `bool` | `False` | зацикливание при выходе за границу |
| `on_click` | callback | `None` | на ЛЮБОЙ клик (−, +, значение) ДО изменения |
| `on_text_click` | callback | `None` | клик по центральной кнопке значения |
| `on_value_changed` | callback | `None` | при изменении значения (любая причина) |
| `when` | условие | `None` | показ/скрытие |
| `plus_style` / `minus_style` / `value_style` | `StyleWidget` | `EMPTY_STYLE` | стили соответствующих кнопок |

### 2.3. Тип колбэков (counter.py:19)

```python
class OnCounterEvent(Protocol):
    async def __call__(self, event: ChatEvent, counter: "ManagedCounter",
                       dialog_manager: DialogManager): ...

OnCounterEventVariant = OnCounterEvent | WidgetEventProcessor | None
```

Все три колбэка (`on_click`, `on_text_click`, `on_value_changed`) одной сигнатуры.

### 2.4. Механика (counter.py:158 `_process_item_callback`)

callback_data кодирует, какая кнопка нажата: `"-"`, `""` (значение), `"+"`.

```python
await self.on_click.process_event(callback, self.managed(manager), manager)   # сначала on_click ВСЕГДА
value = self.get_value(manager)
if data == "+":
    value += self.increment
    if value > self.max and self.cycle:
        value = self.min
    await self.set_value(manager, value)
elif data == "-":
    value -= self.increment
    if value < self.min and self.cycle:
        value = self.max
    await self.set_value(manager, value)
elif data == "":
    await self.on_text_click.process_event(callback, self.managed(manager), manager)
```

`set_value` (counter.py:105) — **граничная проверка тут**:

```python
async def set_value(self, manager, value: float) -> None:
    if self.min <= value <= self.max:        # вне диапазона — НИЧЕГО не делает
        self.set_widget_data(manager, value)
        await self.on_value_changed.process_event(manager.event, self.managed(manager), manager)
```

`get_value` (counter.py:102):
```python
def get_value(self, manager) -> float:
    return self.get_widget_data(manager, self.default)
```

#### Порядок и краевые случаи логики ±

- **`on_click` вызывается всегда** и ПЕРВЫМ — даже при клике по центральной кнопке
  значения (после него ещё `on_text_click`).
- **Без `cycle`**: при `value + increment > max` итоговое значение НЕ проходит проверку
  `min <= value <= max` в `set_value` → значение **не меняется**, `on_value_changed`
  **не вызывается**. То есть «упирается» в границу, но не «прижимается» к ней
  (не клампится до max!). Пример: max=10, value=9, increment=2 → попытка 11 → остаётся 9.
- **С `cycle=True`**: при превышении max устанавливается `min` (и наоборот). Затем всё
  равно идёт через `set_value`, который снова проверяет границы; `min`/`max` валидны → ок.
- Если кнопки `minus`/`text`/`plus` = `None`, соответствующая кнопка не рендерится
  (`_render_keyboard` counter.py:120,131,145).

### 2.5. Рендер центральной кнопки и формат `{value:g}`

В `_render_keyboard` (counter.py:131) текст значения рендерится с данными
`{"value": <число>, "data": <исходный data>}`:

```python
value_data = {"value": self.get_value(manager), "data": data}
text=await self.text.render_text(value_data, manager)
```

- Дефолтный `Format("{value:g}")` форматирует через спецификатор `:g`: `5.0` → `"5"`,
  `5.5` → `"5.5"`. Удобно, чтобы целые не показывались с `.0`.
- Свой `text=` имеет доступ к `value` и вложенному `data` (то есть `Format("{value} из 10")`
  или `Format("{data[some_field]}")`).

### 2.6. `ManagedCounter` (counter.py:194)

| Метод | Возврат | Эффект |
|---|---|---|
| `get_value()` | `float` | текущее значение (может записать default при первом чтении) |
| `set_value(value: float)` | `None` (awaitable) | установка с проверкой границ; при успехе — `on_value_changed` |

```python
class ManagedCounter(ManagedWidget[Counter]):
    def get_value(self) -> float: ...
    async def set_value(self, value: float) -> None: ...
```

> `set_value` через managed так же **молча игнорирует** значения вне `[min, max]`
> (тест `test_min_value_counter` / `test_max_value_counter`).

### 2.7. Пример с Progress (example/mega/bot_dialogs/counter.py)

```python
ID_COUNTER = "counter"
MAX_VALUE = 10

async def getter(dialog_manager: DialogManager, **kwargs):
    counter: ManagedCounter = dialog_manager.find(ID_COUNTER)
    return {"progress": counter.get_value() / MAX_VALUE * 100}

async def on_text_click(event: CallbackQuery, widget: ManagedCounter, dialog_manager):
    await event.answer(f"Value: {widget.get_value()}")

Counter(
    id=ID_COUNTER,
    default=0,
    max_value=MAX_VALUE,
    on_text_click=on_text_click,
    plus_style=Style(ButtonStyle.SUCCESS),
    minus_style=Style(ButtonStyle.DANGER),
)
```

---

## 3. CopyText

`src/aiogram_dialog/widgets/kbd/copy.py`. Класс `CopyText(Keyboard)`. **Stateless**,
managed-обёртки НЕТ, `id` НЕТ.

### 3.1. Сигнатура (copy.py:13)

```python
CopyText(
    text: Text,                       # надпись на кнопке
    copy_text: Text,                  # что копируется в буфер обмена
    when: WhenCondition = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

| Параметр | Тип | Default | Назначение |
|---|---|---|---|
| `text` | `Text` | — | подпись кнопки |
| `copy_text` | `Text` | — | текст, копируемый в буфер по нажатию |
| `when` | условие | `None` | показ/скрытие |
| `style` | `StyleWidget` | `EMPTY_STYLE` | стиль кнопки |

### 3.2. Механика

Использует нативную `aiogram.types.CopyTextButton` (Bot API). Никакого callback —
копирование делает сам Telegram-клиент; колбэков `on_click` нет.

```python
InlineKeyboardButton(
    text=await self._text.render_text(data, manager),
    copy_text=CopyTextButton(text=await self._copy_text.render_text(data, manager)),
    style=style,
    icon_custom_emoji_id=icon_custom_emoji_id,
)
```

### 3.3. Пример (docs/widgets/keyboard/copy_text/example.py)

```python
from aiogram_dialog.widgets.kbd import CopyText
from aiogram_dialog.widgets.text import Const

copy_btn = CopyText(
    text=Const("Copy name"),
    copy_text=Const("Tishka17"),
)
```

`copy_text` может быть `Format(...)` — то есть копируемый текст формируется из getter-данных.

---

## 4. Сводная таблица состояния и колбэков

| Виджет | Хранит state | Ключ | Managed | Чтение | Запись | Колбэки |
|---|---|---|---|---|---|---|
| `Checkbox` | да (`bool`) | `id` | `ManagedCheckbox` | `is_checked()` | `set_checked(bool)` | `on_click`, `on_state_changed` |
| `Counter` | да (`float`) | `id` | `ManagedCounter` | `get_value()` | `set_value(float)` | `on_click`, `on_text_click`, `on_value_changed` |
| `CopyText` | нет | — | нет | — | — | нет (нативная кнопка) |

Порядок вызова колбэков на реальном клике:

- Checkbox: `on_click` → (запись) → `on_state_changed`.
- Counter «+»/«−»: `on_click` → (запись, если в границах) → `on_value_changed`.
- Counter по значению: `on_click` → `on_text_click` (значение не меняется).

---

## 5. Подводные камни и краевые случаи

1. **`default` «прилипает» после первого чтения.** `get_widget_data` использует
   `dict.setdefault`: при первом обращении (рендер или `find().is_checked()/get_value()`)
   default записывается в `widget_data`. Дальше менять `default=` в коде бесполезно для
   уже открытого диалога — состояние уже зафиксировано в контексте. Сбрасывается только
   пересозданием контекста (новый запуск диалога / `start` с `MODE.RESET_STACK` и т.п.).

2. **Counter молча игнорирует выход за границы.** `set_value` НЕ клампит и НЕ бросает
   исключение — просто ничего не делает, если `value` вне `[min, max]`. Значит:
   - программный `set_value(manager, 9999999)` при max=10 — no-op (тихо);
   - клик «+» у границы без `cycle` оставляет старое значение и НЕ зовёт `on_value_changed`.
   Если нужен кламп — реализуйте сами перед вызовом.

3. **`increment`, не делящий диапазон, может «застрять» у границы.** Пример: min=0,
   max=10, increment=3, value=9 → «+» даёт 12 > 10 → отклонено → остаётся 9; до 10 не
   дойти. Подбирайте `increment` под `(max-min)` или используйте `cycle`.

4. **`cycle` перескакивает на противоположную границу, не на ближайшую.** «+» за max →
   value=min; «−» за min → value=max. Это циклический счётчик, не «отскок».

5. **Тип значения Counter — `float`.** Арифметика `value += increment` идёт в float.
   Даже при целых `default`/`increment` после операций можно получить `5.0`. Для целого
   ввода форматируйте `:g` (дефолт) и приводите в getter: `int(counter.get_value())`.
   Не сравнивайте через `==` с дробными increment (накопление погрешности float).

6. **`id` обязателен для Checkbox/Counter; для CopyText не существует.** Без `id`
   состояние не привяжется (ключ `None`). Дублирование `id` в окнах ОДНОГО диалога →
   общее состояние (docs note). Разные открытые экземпляры диалога состояние не делят.

7. **`set_checked` — абсолютная установка, не toggle.** На реальном клике инверсия
   делается внутри `_process_item_callback`. Программно для переключения:
   `await cb.set_checked(not cb.is_checked())`.

8. **`manager.find(id)` возвращает managed-обёртку или `None`.** `None`, если виджета с
   таким `id` нет в дереве текущего диалога. Виджет, скрытый через `when`, всё равно
   присутствует в дереве и находится `find` (скрытие влияет только на рендер/обработку
   клика, не на наличие в дереве) — но кликнуть по нему пользователь не сможет.

9. **Checkbox toggle относителен отрисованной кнопки.** Инверсия берёт состояние из
   callback_data конкретной нажатой кнопки (`"0"`/`"1"`), а не из текущего `widget_data`.
   Это устойчиво к кликам по устаревшим сообщениям.

10. **`on_click` у Counter срабатывает и на клике по значению.** Если в `on_click`
    что-то делаете «на изменение», помните: при клике по центральной кнопке значение НЕ
    меняется, но `on_click` всё равно вызовется (затем `on_text_click`). Для реакции
    именно на изменение используйте `on_value_changed`.

11. **CopyText требует свежий aiogram/Bot API.** `CopyTextButton` — Bot API 7.11+
    (aiogram>=3.14 — минимальная версия библиотеки). Кнопка копирует на стороне клиента;
    серверного события клика нет, метрики кликов снять нельзя.

12. **Стили (`*_style`) требуют поддержки `ButtonStyle` в aiogram.** Передаются как
    `StyleWidget` (например `Style(ButtonStyle.SUCCESS)`), рендерятся в `style=` и
    `icon_custom_emoji_id=` `InlineKeyboardButton`. На старых клиентах могут
    игнорироваться.

---

## 6. Связи с остальной библиотекой

- **`Text`-виджеты** (`Const`, `Format`, `Case`): тексты кнопок. Checkbox внутри строит
  `Case({True: checked_text, False: unchecked_text}, selector=self._is_text_checked)`
  (checkbox.py:40) — то есть текст выбирается по текущему состоянию автоматически.
- **`Style`/`StyleCase`** (`widgets/style/`): Checkbox использует `StyleCase` для
  переключения стиля по состоянию (checkbox.py:44). Counter/CopyText — обычный `StyleWidget`.
- **`WidgetEventProcessor` / `ensure_event_processor`** (`widgets/widget_event.py`):
  любой колбэк оборачивается в `SimpleEventProcessor`; можно передать готовый processor.
- **`ManagedWidget[W]`** (`widgets/common/managed.py`): база managed-обёрток; `__getattr__`
  проксирует доступ к атрибутам самого виджета.
- **`DialogManager.find`** (`manager/manager.py:538`) + **`Window.find`**
  (`window.py:182`): путь получения managed-обёртки в getter/хэндлерах.
- **`current_context().widget_data`**: общее хранилище состояния всех stateful-виджетов
  (Select, Radio, Multiselect, ScrollingGroup и др. — тот же механизм).
- **`Progress`** (text-виджет): типичная пара к Counter для визуализации (mega-пример).

---

## 7. Шпаргалка для продакшн-шаблона

```python
from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import (
    Checkbox, ManagedCheckbox, Counter, ManagedCounter, CopyText,
)
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Const, Format

# --- Checkbox ---
notify = Checkbox(
    Const("🔔 Notifications: ON"),
    Const("🔕 Notifications: OFF"),
    id="notify",
    default=False,
    on_state_changed=lambda e, w, m: w.manager.event.answer(  # пример
        f"now {w.is_checked()}"
    ),
)

# --- Counter ---
qty = Counter(
    id="qty",
    min_value=1, max_value=99, increment=1, default=1,
    text=Format("Qty: {value:g}"),
    plus_style=Style(ButtonStyle.SUCCESS),
    minus_style=Style(ButtonStyle.DANGER),
)

# --- CopyText ---
ref = CopyText(text=Const("Copy referral code"), copy_text=Format("{ref_code}"))

# --- getter: читаем состояние ---
async def getter(dialog_manager: DialogManager, **kwargs):
    cb: ManagedCheckbox = dialog_manager.find("notify")
    cnt: ManagedCounter = dialog_manager.find("qty")
    return {
        "notify_on": cb.is_checked(),
        "quantity": int(cnt.get_value()),   # приводим float→int
        "ref_code": "ABC123",               # для CopyText.copy_text=Format("{ref_code}")
    }
```
