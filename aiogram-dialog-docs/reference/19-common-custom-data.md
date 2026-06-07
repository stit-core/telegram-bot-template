---
title: "Зона 19 — Общая машинерия виджетов: Whenable/when, Managed, find, передача данных, скрытие, кастомные виджеты"
zone: 19
source_repo: /tmp/aiogram_dialog
source_rev: "develop, 08abdf0, 2026-05-02"
aiogram_min: ">=3.14.0"
status: reference
updated: 2026-06-07
tags: [common, whenable, when, managed, find, getter, data, custom-widget, business, groups]
---

# Зона 19. Общая машинерия виджетов

Эта заметка покрывает «фундамент» библиотеки: базовые классы и протоколы, на которых строятся
все виджеты (`Text`, `Keyboard`, `Input`, `Media`, `LinkPreview`), механику скрытия (`when`),
обёртки `Managed*`, поиск виджетов `find`, нормализацию обработчиков событий и полный поток данных
от getter-ов к рендеру. В конце — раздел про бизнес-чаты и группы (`group_business`).

> **Важно про версию.** В задании упомянуты `GeneratorType` и `register_callback` в
> `widget_event.py` — в этой ревизии их **нет**. Поток обработчиков нормализуется только через
> `SimpleEventProcessor` (см. раздел «WidgetEventProcessor»). Поддержки генераторов / списка
> обработчиков в `ensure_event_processor` тоже нет — это либо более старое, либо более позднее
> API. Не закладывайтесь на него в шаблоне.

---

## 1. Карта файлов зоны

| Файл | Что определяет |
|---|---|
| `widgets/common/base.py` | `BaseWidget(Widget)` — дефолтные `managed`/`find` |
| `widgets/common/when.py` | `Whenable`, `Predicate`, `WhenCondition`, фабрики предикатов |
| `widgets/common/managed.py` | `ManagedWidget[W]` — обёртка для `manager.find(id)` |
| `widgets/common/action.py` | `Actionable` — `id`, `find`, `get/set_widget_data` |
| `widgets/common/case.py` | `Selector`, фабрики селекторов для `Case`/`StyleCase` |
| `widgets/common/__init__.py` | публичный реэкспорт common-слоя |
| `widgets/widget_event.py` | `WidgetEventProcessor`, `SimpleEventProcessor`, `ensure_event_processor` |
| `widgets/utils.py` | `ensure_widgets`, `ensure_*`, `ensure_data_getter`, `GetterVariant`, `WidgetSrc` |
| `widgets/data/data_context.py` | `CompositeGetter`, `StaticGetter`, `PreviewAwareGetter` |
| `api/internal/widgets.py` | протоколы `Widget`/`TextWidget`/`KeyboardWidget`/`InputWidget`/`MediaWidget`/`StyleWidget`/`LinkPreviewWidget`/`MarkupFactory`, `DataGetter`, `RawKeyboard` |

Иерархия наследования (упрощённо):

```
Widget (Protocol, runtime_checkable)        api/internal/widgets.py:30
└── BaseWidget                              common/base.py:7
    └── Actionable                          common/action.py:11   (+ id)
        ├── Keyboard(Actionable, Whenable, KeyboardWidget)   kbd/base.py:15
        ├── BaseInput(Actionable, InputWidget)               input/base.py:26
        └── ...
Text(Whenable, BaseWidget, TextWidget)      text/base.py:14       (Text НЕ Actionable → нет id)
Whenable                                    common/when.py:56     (mixin, не Widget)
```

---

## 2. Протоколы виджетов (`api/internal/widgets.py`)

Базовый протокол — `Widget` (`api/internal/widgets.py:30`, `@runtime_checkable`):

```python
class Widget(Protocol):
    def managed(self, manager: DialogManager) -> Any: ...
    def find(self, widget_id: str) -> Optional["Widget"]: ...
```

Специализации (все `@runtime_checkable`, наследуют `Widget`):

| Протокол | Ключевой async-метод | Возврат | Файл:строка |
|---|---|---|---|
| `TextWidget` | `render_text(data, manager)` | `str` | `widgets.py:41` |
| `StyleWidget` | `render_style(...)` / `render_emoji(...)` | `ButtonStyle\|None` / `str\|None` | `widgets.py:51` |
| `LinkPreviewWidget` | `render_link_preview(...)` | `LinkPreviewOptions\|None` | `widgets.py:68` |
| `KeyboardWidget` | `render_keyboard(...)` → `RawKeyboard`; `process_callback(...)` → `bool` | см. ниже | `widgets.py:82` |
| `MediaWidget` | `render_media(...)` | `MediaAttachment\|None` | `widgets.py:106` |
| `InputWidget` | `process_message(...)` | `bool` | `widgets.py:116` |
| `MarkupFactory` | `render_markup(data, manager, keyboard)` | `MarkupVariant` | `widgets.py:136` |

Типы-алиасы (`widgets.py:77`, `:132`):

```python
ButtonVariant = InlineKeyboardButton | KeyboardButton
RawKeyboard   = list[list[ButtonVariant]]
DataGetter    = Callable[..., Awaitable[dict]]
```

Семантика `process_callback`/`process_message` (важно!): вызывается **на каждом виджете дерева,
независимо** от того, кому принадлежит callback. Виджет сам решает «моё / не моё» и возвращает
`True`, если событие обработано и **дальше распространять не нужно** (см. `kbd/base.py:62`).

---

## 3. `BaseWidget` и `Actionable`

`BaseWidget` (`common/base.py:7`) даёт дефолтные реализации протокола `Widget`:

```python
class BaseWidget(Widget):
    def managed(self, manager): return self          # по умолчанию — сам виджет
    def find(self, widget_id): return None           # листовой виджет ничего не находит
```

`Actionable` (`common/action.py:11`) добавляет идентификатор и доступ к persistent-данным виджета:

```python
ID_PATTERN = re.compile("^[a-zA-Z0-9_.]+$")

class Actionable(BaseWidget):
    def __init__(self, id: str | None = None):
        if id and not ID_PATTERN.match(id):
            raise InvalidWidgetIdError(...)          # пробел/двоеточие/кириллица → исключение
        self.widget_id = id

    def find(self, widget_id):                       # action.py:17
        return self if (self.widget_id and self.widget_id == widget_id) else None

    def get_widget_data(self, manager, default):     # action.py:23
        return manager.current_context().widget_data.setdefault(self.widget_id, default)

    def set_widget_data(self, manager, value):       # action.py:34
        manager.current_context().widget_data[self.widget_id] = value
```

- `widget_id` хранится как `self.widget_id` (атрибут называется иначе, чем параметр `id`).
- `id` валидируется паттерном — **разрешены только `[a-zA-Z0-9_.]`**. Двоеточие `:`
  зарезервировано как разделитель в `callback_data` (`kbd/base.py:60`), потому его нет в паттерне.
- `get/set_widget_data` пишут в `context.widget_data` (отдельно от `dialog_data`) —
  именно так `Checkbox`/`Multiselect`/`Counter`/`Calendar` хранят своё состояние между рендерами.
- `Text` наследует `BaseWidget`, но **не** `Actionable` → у текстовых виджетов нет `id` и их нельзя
  найти через `find` (кроме контейнеров `Multi/Case/Or`, которые делегируют поиск детям по тексту).

---

## 4. Скрытие виджетов: `Whenable` и `when`

`Whenable` (`common/when.py:56`) — mixin (не наследует `Widget`), хранящий предикат `condition`:

```python
WhenCondition = str | MagicFilter | Predicate | None

class Whenable:
    def __init__(self, when: WhenCondition = None):
        if when is None:                self.condition = true_condition
        elif isinstance(when, str):     self.condition = new_when_field(when)
        elif isinstance(when, MagicFilter): self.condition = new_when_magic(when)
        else:                           self.condition = when      # callable Predicate

    def is_(self, data, manager) -> bool:                         # when.py:68
        return self.condition(data, self, manager)
```

### Четыре формы `when`

| Форма | Тип | Семантика | Фабрика |
|---|---|---|---|
| `when=None` | — | всегда показывать | `true_condition` (`when.py:52`) |
| `when="extended"` | `str` | показать, если `bool(data.get("extended"))` | `new_when_field` (`when.py:34`) |
| `when=F["extended"]` | `MagicFilter` | показать, если `f.resolve(data)` истинно | `new_when_magic` (`when.py:43`) |
| `when=my_predicate` | `Predicate` | показать, если `predicate(...) -> True` | как есть |

Протокол `Predicate` (`common/when.py:11`, позиционные аргументы — `/`):

```python
class Predicate(Protocol):
    def __call__(self, data: dict, widget: Whenable, dialog_manager: DialogManager, /) -> bool: ...
```

> Сигнатура предиката — **`(data, widget, manager)`**. В примерах документации третий параметр
> называют `manager`, в протоколе — `dialog_manager`; имена не важны (аргументы позиционные).

### Как `when` влияет на рендер

Скрытие реализовано в обёртках `render_*`, а не в `_render_*`:

- `Text.render_text` (`text/base.py:18`): `if not self.is_(data, manager): return ""`
- `Keyboard.render_keyboard` (`kbd/base.py:20`): `if not self.is_(data, manager): return []`

Поэтому скрытый текст даёт пустую строку (а `Multi` через `filter(None, ...)` её выбрасывает,
`text/multi.py:96`), а скрытая клавиатура — пустой ряд кнопок. **Правило кастомного виджета:**
переопределяй `_render_text` / `_render_keyboard`, чтобы `when` продолжал работать автоматически
(см. раздел про кастомные виджеты).

### `F`-фильтр работает по всему словарю данных

`MagicFilter.resolve(data)` получает **итоговый словарь** из getter-цепочки (см. поток данных),
включая зарезервированные ключи. Поэтому валидно:

```python
F["extended"]                      # ключ из getter
F["dialog_data"]["user"]["name"]   # вложенный доступ к dialog_data
F["start_data"]                    # проверка наличия start_data
```

`F` импортируется и из `magic_filter`, и из `aiogram` (aiogram реэкспортирует тот же объект —
в тестах библиотеки используется `from aiogram import F`, `tests/widgets/kbd/test_base.py:2`).

### Пример скрытия (из `docs/widgets/hiding/example.py`)

```python
def is_tishka17(data, widget: Whenable, manager: DialogManager):
    return data.get("name") == "Tishka17"

window = Window(
    Multi(
        Const("Hello"),
        Format("{name}", when="extended"),   # str-ключ
        sep=" ",
    ),
    Group(
        Row(
            Button(Const("Wait"), id="wait"),
            Button(Const("Ignore"), id="ignore"),
            when=F["extended"],              # F-фильтр, скрывает ВЕСЬ Row
        ),
        Button(Const("Admin mode"), id="nothing", when=is_tishka17),  # callable
    ),
    state=MySG.main,
    getter=get_data,
)
```

---

## 5. `Case` / `Selector` (`common/case.py`)

Параллель к `Whenable`, но возвращает **ключ выбора** (`Hashable`), а не `bool`. Используется
в `Case`-тексте (`text/multi.py:16`) и `StyleCase`.

```python
Selector = Callable[[dict, T, DialogManager], Hashable]
new_case_field(fieldname)  → возвращает data.get(fieldname)          # case.py:12
new_magic_selector(f)      → возвращает f.resolve(data)              # case.py:21
```

`Case` (`text/multi.py:16`): `selector` принимает `str | Selector | MagicFilter`; ключ `...`
(Ellipsis) в словаре `texts` — это **default-ветка**. Если ключ не найден и default нет —
в обычном режиме `KeyError`, а в preview берётся первый элемент (`text/multi.py:40`).

---

## 6. `ManagedWidget` и `managed()` (`common/managed.py`)

```python
class ManagedWidget(Generic[W]):
    def __init__(self, widget: W, manager: DialogManager):
        self.widget = widget
        self.manager = manager
    def __getattr__(self, item):          # проксирует ВСЁ на self.widget
        return getattr(self.widget, item)
```

Смысл: `ManagedWidget` «привязывает» виджет к конкретному `manager`, чтобы методы можно было
вызывать **без передачи manager каждый раз**. Конкретные подклассы добавляют удобные методы:

```python
class ManagedCheckbox(ManagedWidget[Checkbox]):          # kbd/checkbox.py:144
    def is_checked(self) -> bool:
        return self.widget.is_checked(self.manager)
    async def set_checked(self, checked: bool) -> None:
        return await self.widget.set_checked(self.manager.event, checked, self.manager)
```

Какие виджеты имеют свой `Managed`-класс (переопределяют `managed()`):
`Checkbox`→`ManagedCheckbox`, `Radio`→`ManagedRadio[T]`, `Multiselect`→`ManagedMultiselect[T]`,
`Counter`→`ManagedCounter`, `Calendar`→`ManagedCalendar`, `*TimeSelect`→`ManagedTimeSelect`,
`ListGroup`→`ManagedListGroup`, `Scroll`→`ManagedScroll`, `TextInput`→`ManagedTextInput`.
Остальные виджеты возвращают `self` (дефолт `BaseWidget.managed`, `base.py:8`).

> Из-за `__getattr__` обёртка прозрачна: `managed.widget_id`, `managed.is_(...)` и т.п. работают.
> Но **аннотации типов** на проксируемые члены не распространяются — IDE «не видит» их через
> обёртку, видит только методы, явно объявленные в `Managed*`-подклассе.

---

## 7. Поиск виджетов: `find` и `manager.find`

### Дерево `find`

`find(widget_id)` идёт сверху вниз и возвращает «сырой» виджет (не обёрнутый):

| Уровень | Логика | Файл:строка |
|---|---|---|
| `DialogManager.find` | `widget = self.dialog().find(id); return widget.managed(self) if widget else None` | `manager/manager.py:538` |
| `Dialog.find` | перебор `self.windows.values()`, первый непустой | `dialog.py:221` |
| `Window.find` | перебор `(text, keyboard, on_message, media)` | `window.py:182` |
| `Group.find` | `super().find()` (свой id), затем рекурсия по `self.buttons` | `kbd/group.py:24` |
| `ListGroup.find` | свой id, затем рекурсия по детям | `kbd/list_group.py:104` |
| `Multi/Case/Or` (текст) | рекурсия по детям | `text/multi.py:44`, `text/base.py:122/161` |
| `Actionable.find` | `self`, если совпал `widget_id`, иначе `None` | `action.py:17` |
| `BaseWidget.find` (лист) | всегда `None` | `base.py:11` |

Ключевое: **`manager.find` оборачивает результат в `Managed`** (`widget.managed(self)`), а
голый `widget.find()` — нет. Поэтому в продакшн-коде всегда используйте `manager.find(id)`.

```python
checkbox: ManagedCheckbox = manager.find("opt_in")
if checkbox is None:                       # id не найден → None, без исключения
    return
await checkbox.set_checked(True)
```

### Подводные камни find

- **Возвращает `None`, если id нет** в текущем диалоге — обязательно проверяйте на `None`.
- Ищется по **всему диалогу** (всем окнам), а не только по текущему окну — id уникальны в пределах
  диалога.
- Текстовые виджеты без `Multi/Case/Or` (`Const`, `Format`) **нельзя найти** — у них нет id.
- В `ListGroup` для доступа к под-виджетам нужен `SubManager` (item-контекст). Снаружи
  `manager.find(list_id)` вернёт `ManagedListGroup`, а доступ к конкретному элементу идёт через
  под-менеджер (`sub_manager.py:88`, `find_in_parent` — `sub_manager.py:94`).

---

## 8. Обработчики событий: `WidgetEventProcessor`

`widgets/widget_event.py` — тонкий слой нормализации `on_click` / `on_state_changed` / `on_success`
/ `on_error` и т.п.

```python
class WidgetEventProcessor:                           # widget_event.py:9
    async def process_event(self, event, source, manager, *args, **kwargs): ...

class SimpleEventProcessor(WidgetEventProcessor):     # widget_event.py:22
    def __init__(self, callback): self.callback = callback
    async def process_event(self, event, source, manager, *args, **kwargs):
        if self.callback:
            await self.callback(event, source, manager, *args, **kwargs)

def ensure_event_processor(processor) -> WidgetEventProcessor:   # widget_event.py:38
    return processor if isinstance(processor, WidgetEventProcessor) \
                     else SimpleEventProcessor(processor)
```

- Любой виджет в `__init__` делает `self.on_click = ensure_event_processor(on_click)`
  (`kbd/button.py:35`, `kbd/checkbox.py:48`, `input/base.py:44`, `kbd/select.py:79` и т.д.).
- Затем в обработчике callback вызывает `await self.on_click.process_event(event, source, manager)`.
- `source` — это **то, что увидит ваш handler вторым аргументом**. Для `Button` это сам виджет
  (`kbd/button.py:44` передаёт `self`), для `Checkbox` — `self.managed(manager)` (т.е.
  `ManagedCheckbox`, `kbd/checkbox.py:82`). Поэтому в хендлере чекбокса второй аргумент — managed.
- `callback` может быть `None` — тогда `process_event` ничего не делает (`if self.callback`).
- Можно передать **готовый `WidgetEventProcessor`** вместо callable — тогда `ensure_*` вернёт его
  как есть. Это точка расширения для кастомной логики (несколько хендлеров, фильтры — реализуйте
  свой подкласс `WidgetEventProcessor`).

> **Сигнатура пользовательского `on_click`:** `async def handler(event, widget, manager, ...)`.
> Для `Button`: `(callback: CallbackQuery, button: Button, manager: DialogManager)`
> (`OnClick`, `kbd/button.py:21`). Лишние `*args/**kwargs` прокидываются через `process_event`.

---

## 9. Поток данных: getter → render

### Слои данных (объединяются снизу вверх)

```
manager.load_data()              manager/manager.py:130
  → { dialog_data, start_data, middleware_data, event,  **global_getter(...) }
dialog.load_data(manager)        dialog.py:115
  → manager.load_data() | dict(dialog.getter(**middleware_data))
window.load_data(dialog, manager)  window.py:113
  → dialog.load_data() | dict(window.getter(**middleware_data))
```

Точная реализация базового слоя (`manager/manager.py:130`):

```python
async def load_data(self) -> dict:
    context = self.current_context()
    data = await self._getter(**self.middleware_data) if self._getter else {}
    return {
        "dialog_data": context.dialog_data,
        "start_data": context.start_data,
        "middleware_data": self._data,
        "event": self.event,
        **data,                       # global getter из setup_dialogs(getter=...)
    }
```

- `self._getter` — **глобальный** getter, переданный в `setup_dialogs(getter=...)`
  (`setup.py:229` → `manager.py:91`).
- `Dialog.load_data` и `Window.load_data` поверх делают `data.update(await getter(...))`
  — поэтому **window-getter перекрывает dialog-getter, а тот — global-getter** при совпадении
  ключей (последний `update` побеждает).
- Все getter-ы вызываются с `**manager.middleware_data` (а не с собранным `data`!). Это значит,
  внутри getter доступны ключи middleware-данных aiogram: `dialog_manager`, `event_chat`,
  `event_from_user`, `bot`, ваши middleware-ключи и т.д.

### Объявление getter

```python
async def getter(**kwargs) -> dict:
    manager: DialogManager = kwargs["dialog_manager"]   # или объявить именованным параметром
    bot = kwargs["bot"]
    return {"name": "Tishka17", "items": [...]}
```

Канонический способ — `async def getter(dialog_manager, **kwargs) -> dict`. **Обязательно
оставляйте `**kwargs`** — иначе при добавлении новых ключей в middleware getter упадёт с
`TypeError`. Getter **обязан вернуть `dict`**.

### `GetterVariant` и нормализация (`widgets/utils.py`)

```python
SingleGetterBase = DataGetter | dict
GetterVariant = SingleGetterBase | list[SingleGetterBase] | tuple[...] | None   # utils.py:28

def ensure_data_getter(getter) -> DataGetter:           # utils.py:138
    if callable(getter):       return getter
    if isinstance(getter, dict): return StaticGetter(getter)
    if isinstance(getter, (list, tuple)): return CompositeGetter(*map(ensure_data_getter, getter))
    if getter is None:         return StaticGetter({})
    raise InvalidWidgetType(...)
```

То есть `getter=` у `Dialog`/`Window` принимает: **callable**, **готовый dict** (статика),
**список/кортеж** getter-ов (мердж по порядку), или `None`. Список особенно удобен, чтобы
переиспользовать несколько мелких getter-ов в одном окне:

```python
Window(..., getter=[get_user, get_settings, {"static": 1}])
```

### `data_context.py`

```python
class CompositeGetter:        # data_context.py:5  — последовательный update словарей
class StaticGetter:           # data_context.py:16 — всегда возвращает фиксированный dict
class PreviewAwareGetter:     # data_context.py:24 — выбирает normal/preview getter
```

`Dialog`/`Window` оборачивают `getter` и `preview_data` в `PreviewAwareGetter`
(`dialog.py:72`, `window.py:62`). В обычном режиме зовётся `normal_getter`, в режиме preview
(`manager.is_preview()`) — `preview_getter`. Преимущество композиции: `getter=[a, b]` →
`CompositeGetter(a, b)`, мердж в порядке списка (поздний ключ побеждает).

### Доступ к данным в обработчиках

В `on_click`/`on_message` собранного словаря **нет** — данные берутся из `manager`
(`docs/widgets/passing_data/data_in_handlers.py`):

```python
async def button1_clicked(callback, button, manager: DialogManager):
    manager.dialog_data["user_input"] = "..."   # пишем (persist в FSM)
    event = manager.event                        # текущий ChatEvent
    middleware_data = manager.middleware_data    # = manager._data
    start_data = manager.start_data
    await manager.next()
```

Свойства менеджера (`manager/manager.py`): `event` (`:104`), `middleware_data` (`:108`),
`dialog_data` (`:113` → `current_context().dialog_data`), `start_data` (`:118`).

### Зарезервированные ключи (конфликт имён!)

Базовый слой кладёт в данные ключи `dialog_data`, `start_data`, `middleware_data`, `event`.
**Если ваш getter вернёт ключ с тем же именем — он перетрёт системный** (т.к. `**data` идёт
последним в `manager.load_data`, `manager.py:141`). Не называйте поля getter-а
`event`/`dialog_data`/`start_data`/`middleware_data`.

---

## 10. Сборка виджетов окна: `ensure_widgets` (`widgets/utils.py:97`)

`Window(*widgets)` раскладывает разнородный список по «слотам» по типам:

```python
WidgetSrc = str | TextWidget | Keyboard | MessageHandlerFunc | Media | BaseInput | LinkPreviewBase
```

| Тип входа | Слот | Преобразование |
|---|---|---|
| `str` | text | `Format(str)` (`ensure_text`, utils.py:36) |
| `Text` / `Sequence[Text]` | text | один — как есть, несколько — `Multi(*)` |
| `Keyboard` / список | keyboard | один — как есть, несколько — `Group(*)` |
| `BaseInput` / `Callable` | input | один — как есть; callable → `MessageInput`; несколько → `CombinedInput` |
| `Media` / список | media | только один; >1 → `ValueError` (utils.py:79) |
| `LinkPreviewBase` / список | link_preview | только один; >1 → `ValueError` |
| прочее | — | `InvalidWidgetType` (utils.py:124) |

Итог — кортеж `(text, keyboard, input|None, media, link_preview|None)` (`Window.__init__`,
`window.py:55`). Голая функция-обработчик в списке виджетов становится `MessageInput` —
поэтому `Window(..., my_handler)` валиден.

---

## 11. Как написать свой виджет

### Кастомный `Text`

Наследуй `Text`, переопредели **`_render_text`** (не `render_text`!) — тогда `when` работает сам:

```python
from aiogram_dialog.widgets.text import Text

class Shout(Text):
    def __init__(self, base: Text, when=None):
        super().__init__(when=when)
        self.base = base
    async def _render_text(self, data, manager) -> str:
        return (await self.base.render_text(data, manager)).upper()
    def find(self, widget_id):                  # если есть вложенные тексты — делегируй
        return self.base.find(widget_id)
```

### Кастомный `Keyboard`

Наследуй `Keyboard`, переопредели **`_render_keyboard`** (и при необходимости callback-методы):

```python
class SwitchInlineQueryCurrentChat(SwitchInlineQuery):   # docs custom_widgets example
    async def _render_keyboard(self, data, manager) -> list[list[InlineKeyboardButton]]:
        return [[InlineKeyboardButton(
            text=await self.text.render_text(data, manager),
            switch_inline_query_current_chat=await self.switch_inline.render_text(data, manager),
        )]]
```

Обработка кликов — переопредели один из:
`_process_own_callback` (callback_data == widget_id), `_process_item_callback`
(префикс `widget_id:`), `_process_other_callback` (всё остальное / layout-контейнеры)
(`kbd/base.py:84/93/103`). Регистрация обработчика — через `ensure_event_processor` в `__init__`
+ `await self.on_click.process_event(...)` в нужном месте.

> **Критично (docs/widgets/custom_widgets/index.rst:9):** создавайте `InlineKeyboardButton`
> **заново на каждом рендере**, не переиспользуйте экземпляр между рендерами — библиотека
> мутирует `callback_data` (вставляет intent id). Кэшированная кнопка приведёт к битым callback'ам.

Если у виджета есть состояние — добавь свой `Managed*`-класс и переопредели `managed()`:

```python
class MyWidget(Keyboard):
    def managed(self, manager): return ManagedMyWidget(self, manager)

class ManagedMyWidget(ManagedWidget[MyWidget]):
    def get_value(self): return self.widget.get_widget_data(self.manager, default=None)
```

### `add_exception_note`

`render_text`/`render_keyboard` декорированы `@add_exception_note` (`utils.py:230`): при
исключении на Python ≥ 3.11 в трейс добавляется `at <repr(widget)>` — поэтому
осмысленный `__repr__` у кастомного виджета сильно помогает в отладке. `Actionable.__repr__`
выводит `<ClassName id=...>` (`action.py:42`).

---

## 12. Бизнес-чаты и группы (`docs/group_business.rst`)

Поддержка групп/супергрупп/бизнес-чатов построена на **дополнительных стеках диалогов**:

- Дефолтный стек — **персональный**: диалоги в нём доступны только запустившему пользователю.
- Чтобы показать **общий** диалог, нужен другой стек: `aiogram_dialog.GROUP_STACK_ID`,
  своя строка-id, или запуск с `StartMode.NEW_STACK`.

```python
bg = dialog_manager.bg(stack_id=GROUP_STACK_ID)
await bg.start(MyStateGroup.MY_STATE, mode=StartMode.RESET_STACK)
```

- **Топики (threads):** стеки между топиками изолированы; для запуска в другом топике передайте
  `thread_id` в `.bg()`. В рендере `thread_id` и `business_connection_id` берутся из
  `EventContext` (`window.py:159-165`) — окно само адресует сообщение в нужный чат/тред/бизнес-
  подключение.
- **Ограничение доступа:** `AccessSettings(user_ids=[...])` при `start(...)`. Если не задано —
  копируется из последнего диалога в стеке. Сейчас поддерживается только проверка по `user.id`;
  своя логика — через протокол `StackAccessValidator` в `setup_dialogs`.
- **Запрещённое взаимодействие:** если пользователю нельзя — событие не маршрутизируется в диалоги,
  и его можно ловить в обычном aiogram по ключу `aiogd_stack_forbidden` в middleware-данных.

> Telegram жёстко лимитирует число операций в группах — интерактивные меню там не рекомендованы
> (предупреждение в начале `group_business.rst`).

---

## 13. Связи с остальной библиотекой

- `Text`/`Keyboard`/`Input`/`Media`/`LinkPreview` базы (`widgets/*/base.py`) наследуют
  `Whenable` + `Actionable`/`BaseWidget` из этой зоны.
- `Window`/`Dialog` (зона окна/диалога) дергают `render_*`/`process_*`/`find`/`load_data` —
  точки сшивки именно здесь.
- `DialogManager.find` (зона менеджера) — единственный «правильный» вход в `find` + `managed`.
- `setup_dialogs(getter=...)` (зона setup) кладёт глобальный getter в `manager._getter`.
- `SubManager` (`manager/sub_manager.py`) — контекст элемента `ListGroup`; повторяет `find`,
  добавляет `find_in_parent`.
- `PreviewAwareGetter` связывает зону данных с `tools/preview` (генерация превью диалогов).

---

## 14. Чек-лист подводных камней

1. `manager.find(id)` возвращает **`None`**, если id нет — всегда проверяй.
2. `id` валидируется паттерном `[a-zA-Z0-9_.]` — **никаких `:`, пробелов, кириллицы**.
3. Используй `manager.find`, а не `widget.find` — только первый оборачивает в `Managed`.
4. В кастомных виджетах переопределяй `_render_*`, не `render_*` — иначе сломаешь `when`.
5. Не переиспользуй `InlineKeyboardButton` между рендерами — `callback_data` мутируется.
6. Getter обязан иметь `**kwargs` и возвращать `dict`; зовётся с `**middleware_data`.
7. Не называй поля getter-а `event`/`dialog_data`/`start_data`/`middleware_data` — затрут системные.
8. Приоритет данных при конфликте ключей: window-getter > dialog-getter > global-getter > системные.
9. `F`-фильтр и str-ключ читают **итоговый** словарь данных (включая `dialog_data` и пр.).
10. В этой ревизии `GeneratorType`/`register_callback` отсутствуют — несколько обработчиков делай
    своим подклассом `WidgetEventProcessor`.
