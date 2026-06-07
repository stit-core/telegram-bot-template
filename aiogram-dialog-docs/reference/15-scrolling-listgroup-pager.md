---
title: "Скроллинг и пагинация: ScrollingGroup, Pager-виджеты, ListGroup, StubScroll, протокол Scroll"
zone: 15
source_repo: /tmp/aiogram_dialog
source_rev: "develop @ 08abdf0 (2026-05-02)"
aiogram: ">=3.14.0"
status: reference
tags: [scrolling, pagination, scroll-protocol, pager, list-group, stub-scroll, widget-data, sub-manager]
files:
  - src/aiogram_dialog/widgets/common/scroll.py
  - src/aiogram_dialog/widgets/kbd/scrolling_group.py
  - src/aiogram_dialog/widgets/kbd/pager.py
  - src/aiogram_dialog/widgets/kbd/list_group.py
  - src/aiogram_dialog/widgets/kbd/stub_scroll.py
  - src/aiogram_dialog/widgets/text/list.py
  - src/aiogram_dialog/widgets/text/scrolling_text.py
  - src/aiogram_dialog/widgets/media/scroll.py
---

# Зона 15. Скроллинг и пагинация

Эта зона описывает **единый механизм пагинации** aiogram_dialog. В его центре —
протокол `Scroll`, который реализуют все «скроллируемые» виджеты:
`ScrollingGroup` (клавиатура), `List` / `ScrollingText` (текст), `MediaScroll`
(медиа), `ListGroup` (повторяемые виджеты) и «бесклавиатурный» `StubScroll`.
Отдельный набор виджетов **Pager** (`FirstPage`, `PrevPage`, `CurrentPage`,
`NextPage`, `LastPage`, `NumberedPager`) — это **только кнопки управления**: они
не хранят страницу, а находят целевой `Scroll` по его `id` и дёргают
`set_page()`/`get_page()`/`get_page_count()`.

Ключевая идея: **состояние страницы хранится в `widget_data` под `id` самого
скролла**, а не пейджера. Любое число пейджеров может управлять одним скроллом, и
любой скролл можно нарисовать вообще без пейджера (или со встроенным).

---

## 1. Протокол `Scroll` и базовый класс `BaseScroll`

`src/aiogram_dialog/widgets/common/scroll.py`

### 1.1. Протокол `Scroll` (`scroll.py:17`)

```python
class Scroll(Widget, Protocol):
    async def get_page_count(self, data: dict, manager: DialogManager) -> int: ...
    async def get_page(self, manager: DialogManager) -> int: ...
    async def set_page(self, event: ChatEvent, page: int, manager: DialogManager) -> None: ...
    def managed(self, manager: DialogManager) -> "ManagedScroll": ...
```

Наследует `Widget` (т.е. `find()`, `render*` и пр.) и является `Protocol` с
`@abstractmethod`. Это **поведенческий контракт**, по которому пейджеры работают с
любым скроллом, не зная его конкретного типа.

| Метод | Назначение | Возврат |
|---|---|---|
| `get_page_count(data, manager)` | Сколько всего страниц при текущих данных. `data` — это словарь окна (getter+dialog_data). | `int` (0…N) |
| `get_page(manager)` | Номер текущей страницы (**0-based**). | `int` |
| `set_page(event, page, manager)` | Установить текущую страницу и вызвать `on_page_changed`. | `None` |
| `managed(manager)` | Обёртка `ManagedScroll` для вызова из колбэков/getter. | `ManagedScroll` |

### 1.2. `BaseScroll` (`scroll.py:58`)

```python
class BaseScroll(Actionable, Scroll, ABC):
    def __init__(self, id: str, on_page_changed: OnPageChangedVariants = None): ...
    async def get_page(self, manager) -> int:        # widget_data[id], default 0
    async def set_page(self, event, page, manager):  # пишет widget_data[id]=page + on_page_changed
    def managed(self, manager) -> ManagedScroll
```

- Наследует `Actionable` (`widgets/common/action.py:11`) — отсюда `widget_id`,
  `find()`, и главное `get_widget_data()` / `set_widget_data()`.
- **Хранилище страницы:** `get_page` = `self.get_widget_data(manager, 0)`,
  `set_page` = `self.set_widget_data(manager, page)`. То есть текущая страница
  лежит в `manager.current_context().widget_data[id]` как обычное целое
  (`action.py:23-40`). Между показами окна страница персистентна (живёт в FSM
  storage вместе со всем контекстом).
- `set_page` всегда вызывает `self.on_page_changed.process_event(...)` —
  даже если страница не изменилась. `event` тут — это `ChatEvent` (Message или
  CallbackQuery).
- `get_page_count` НЕ реализован в `BaseScroll` — это `@abstractmethod` из
  `Scroll`, каждый конкретный виджет считает страницы по-своему.

**Важно:** `BaseScroll` не реализует `_render_keyboard`/`_render_text` — это
делают конкретные классы. `BaseScroll` — лишь «миксин состояния страницы».

### 1.3. `ManagedScroll` (`scroll.py:37`)

```python
class ManagedScroll(ManagedWidget[Scroll]):
    async def get_page_count(self, data: dict) -> int
    async def get_page(self) -> int
    async def set_page(self, page: int) -> None
```

Обёртка для удобного вызова из getter/колбэков (manager уже «зашит» внутрь).
`ManagedWidget` (`widgets/common/managed.py`) проксирует прочие атрибуты на
`self.widget` через `__getattr__`. Получают её через
`dialog_manager.find(scroll_id)` (manager делает `widget.managed(self)` —
`manager/manager.py:538`) или `scroll.managed(manager)`.

Типичный вызов из getter (см. `example/scrolls.py:85`):

```python
async def paging_getter(dialog_manager: DialogManager, **_):
    current_page = await dialog_manager.find("stub_scroll").get_page()
    return {"current_page": current_page + 1, ...}
```

`get_page_count(data)` требует `data` — словарь окна; в getter его обычно нет под
рукой, поэтому чаще зовут `get_page()`.

### 1.4. `OnPageChanged` и `sync_scroll` (`scroll.py:51`, `:84`)

```python
OnPageChanged = Callable[[ChatEvent, ManagedScroll, DialogManager], Awaitable]
OnPageChangedVariants = OnPageChanged | WidgetEventProcessor | None
```

`on_page_changed` принимается всеми скроллами (через `BaseScroll.__init__`) и
оборачивается `ensure_event_processor(...)`. Сигнатура коллбэка:
`(event, managed_scroll, manager)`.

**`sync_scroll(scroll_id, on_page_chaged=None)`** (`scroll.py:84`) — фабрика
готового `on_page_changed`, которая **синхронизирует несколько скроллов**: после
смены страницы у текущего скролла она читает его `get_page()` и вызывает
`set_page(page)` у каждого из `scroll_id` (можно строку или `Sequence[str]`).
Опционально сначала вызывается пользовательский `on_page_chaged`.

```python
ScrollingGroup(
    Multiselect(...), id="sync_scroll", width=1, height=10,
    on_page_changed=sync_scroll("list_scroll"),  # один пейджер на 2 объекта
)
```

Экспорт: `from aiogram_dialog.widgets.common import sync_scroll`
(`widgets/common/__init__.py:15`). Пример: `example/mega/bot_dialogs/scrolls.py:259`.

> Опечатка в имени параметра: `on_page_chaged` (без `n`). При передаче по имени
> используйте именно это написание.

---

## 2. `ScrollingGroup` — клавиатура, режущаяся на страницы

`src/aiogram_dialog/widgets/kbd/scrolling_group.py`

### 2.1. Сигнатура (`scrolling_group.py:15`)

```python
class ScrollingGroup(Group, BaseScroll):
    def __init__(
        self,
        *buttons: Keyboard,
        id: str,
        width: int | None = None,
        height: int = 0,
        when: WhenCondition = None,
        on_page_changed: OnPageChangedVariants = None,
        hide_on_single_page: bool = False,
        hide_pager: bool = False,
    ):
```

Множественное наследование: `Group` (`kbd/group.py:12`, layout по `width`) +
`BaseScroll` (состояние страницы). `id` **обязателен** (в отличие от `Group`, где
`id` опционален) — потому что он же используется как ключ хранилища страницы.

| Параметр | Тип | Назначение |
|---|---|---|
| `*buttons` | `Keyboard` | Вложенные виджеты (любые кнопки/группы/Select). |
| `id` | `str` | **Обязателен.** Ключ `widget_data` для страницы + префикс callback пейджера. |
| `width` | `int \| None` | Колонок в ряду (наследуется от `Group`). `None` — не перекомпоновывать. |
| `height` | `int` | **Кнопок-строк на странице.** Дефолт `0` — см. подводный камень. |
| `when` | `WhenCondition` | Скрыть весь виджет по условию. |
| `on_page_changed` | `OnPageChangedVariants` | Коллбэк смены страницы. |
| `hide_on_single_page` | `bool` | Прятать встроенный пейджер, если страница одна. |
| `hide_pager` | `bool` | Никогда не рисовать встроенный пейджер (управление снаружи). |

### 2.2. Как режутся кнопки

Конвейер в `_render_keyboard` (`scrolling_group.py:97`):

1. `_render_contents` → `Group._render_keyboard` — раскладывает вложенные кнопки
   в `RawKeyboard` (учитывая `width`).
2. `_get_page_count(keyboard)` = `len(keyboard)//height + bool(len(keyboard)%height)`
   (`:37`) — число страниц по **количеству строк** клавиатуры (не кнопок!).
3. `_render_page(page, keyboard)` (`:85`) — берёт срез
   `keyboard[page*height : page*height+height]`. `current_page` клампится к
   `last_page` (защита от вышедшей за диапазон страницы).
4. `_render_pager(pages, manager)` (`:46`) — встроенный пейджер (см. ниже).
5. Возврат: `page_keyboard + pager` (пейджер всегда снизу).

`get_page_count(data, manager)` (`:123`) считает страницы заново через
`_render_contents` → используется внешними пейджерами.

### 2.3. Встроенный пейджер ScrollingGroup (`_render_pager`, `:46`)

Это **фиксированный «legacy» пейджер из 5 кнопок** в один ряд:
`1` (на первую) · `<` (prev) · `N` (текущая, на себя) · `>` (next) · `last`
(на последнюю). Текст — номера 1-based, callback — `id:page` (0-based).

Логика скрытия:
- `hide_pager=True` → `[]` (пейджера нет вообще).
- `pages == 0` → `[]`.
- `pages == 1 and hide_on_single_page` → `[]`.

Этот встроенный пейджер **не настраивается** (тексты `1/</N/>/last` зашиты). Для
кастомных кнопок ставьте `hide_pager=True` и используйте Pager-виджеты.

### 2.4. Обработка клика по странице (`_process_item_callback`, `:113`)

`callback_data` встроенного пейджера = `id:<page>`. По клику:
`set_page(callback, int(data), manager)` → пишет страницу + `on_page_changed`.
Возвращает `True` (колбэк обработан). Кнопки контента (Select и т.п.)
обрабатываются вложенными виджетами через `Group._process_other_callback`.

---

## 3. Pager-виджеты

`src/aiogram_dialog/widgets/kbd/pager.py`

Все пейджеры — **только кнопки управления**, состояния не хранят. База —
`BasePager` (`pager.py:46`).

### 3.1. `BasePager` (`pager.py:46`)

```python
class BasePager(Keyboard, ABC):
    def __init__(self, scroll: str | Scroll | None, id: str, when=None): ...
```

- `scroll` может быть **строкой-id**, **самим объектом `Scroll`**, или `None`.
  При строке хранит `_scroll_id`, иначе `_scroll`.
- `_find_scroll(manager)` (`:61`): если был объект — `scroll.managed(manager)`;
  если id — `manager.find(scroll_id)` (вернёт `ManagedScroll`).
- `_process_item_callback` (`:67`): `scroll.set_page(int(data))` — клик по любой
  pager-кнопке устанавливает целевую страницу. `callback_data` = `id:<target_page>`.

> **`id` у пейджеров общий по умолчанию** = `DEFAULT_PAGER_ID = "__pager__"`
> (`pager.py:35`). Несколько пейджеров с дефолтным id в одном окне технически
> делят префикс callback — но т.к. callback_data содержит целевую страницу, а
> страница пишется в **скролл**, конфликт не критичен. Тем не менее это нарушает
> «уникальность id виджетов» — см. подводные камни.

### 3.2. `SwitchPage` и направления (`pager.py:79`)

```python
class SwitchPage(BasePager):
    def __init__(self, page: int | PageDirection, scroll, id, text: TextWidget,
                 when=None, style: StyleWidget = EMPTY_STYLE): ...
```

`PageDirection` (`pager.py:15`): `FIRST | PREV | NEXT | LAST | IGNORE`.
`_get_target_page(current, pages)` (`:94`):

| direction | target_page |
|---|---|
| `int` | сам `page` |
| `FIRST` | `0` |
| `PREV` | `max(0, current-1)` |
| `NEXT` | `min(last, current+1)` |
| `LAST` | `max(0, last)` |
| `IGNORE` | `min(last, current)` (т.е. текущая) |

Рендерит **одну кнопку** (`_render_keyboard`, `:147`) с текстом из `TextWidget`,
callback на `target_page`, плюс `style`/`icon_custom_emoji_id` из `StyleWidget`.
Перед рендером (`render_keyboard`, `:130`) собирает `PagerPageData`:
`{data, target_page, target_page1, current_page, current_page1, pages}` —
эти поля доступны в `Format(...)` текста кнопки.

### 3.3. Готовые пейджеры-кнопки

Все наследуют `SwitchPage`, отличаются `page` и текстом по умолчанию.
Сигнатура одинакова: `(scroll, id=DEFAULT_PAGER_ID, text=<default>, when=None, style=EMPTY_STYLE)`.

| Класс | `:LINE` | direction | Текст по умолчанию |
|---|---|---|---|
| `FirstPage` | `pager.py:225` | `FIRST` | `Const("<<")` |
| `PrevPage` | `pager.py:206` | `PREV` | `Const("<")` |
| `CurrentPage` | `pager.py:244` | `IGNORE` | `Format("{current_page1}")` |
| `NextPage` | `pager.py:187` | `NEXT` | `Const(">")` |
| `LastPage` | `pager.py:168` | `LAST` | `Const(">>")` |

`CurrentPage` ведёт на текущую страницу (клик ничего не меняет) — обычно как
индикатор номера. Доступные плейсхолдеры в `text`: `target_page`/`target_page1`,
`current_page`/`current_page1`, `pages`, плюс исходный `data` под ключом `data`.

> `when=F["data"]["..."]` у пейджера работает по `data["data"]` (исходный getter),
> а не по pager-полям — см. `example/scrolls.py:178` (`show_hidden_prev_page`).

### 3.4. `NumberedPager` (`pager.py:263`)

```python
class NumberedPager(BasePager):
    def __init__(self, scroll, id=DEFAULT_PAGER_ID,
                 page_text: TextWidget = Format("{target_page1}"),
                 current_page_text: TextWidget = Format("[ {current_page1} ]"),
                 when=None, length: int | None = None,
                 style: StyleWidget = EMPTY_STYLE,
                 current_page_style: StyleWidget = EMPTY_STYLE): ...
```

Рисует **по кнопке на каждую страницу** (`for target_page in range(pages)`,
`:330`). Текущая страница рисуется через `current_page_text`/`current_page_style`,
остальные — через `page_text`/`style`. callback каждой кнопки = `id:<target_page>`.

- `length` — кнопок в ряду (перенос на новый ряд при достижении). `None` — все в
  одну строку (Telegram режет до 8). Поля в тексте: `target_page1`, `current_page1`,
  `pages` и т.д.
- Стили: `current_page_style=Style(ButtonStyle.SUCCESS)` для подсветки текущей
  (см. `example/mega/.../scrolls.py:149`). Требует aiogram c поддержкой
  `ButtonStyle` (новые версии). `EMPTY_STYLE` (`widgets/style/base.py:149`) —
  нейтрально, ничего не добавляет.

> `NumberedPager` без `length` при большом числе страниц даст слишком длинный ряд.
> Для длинных списков задавайте `length` или используйте `Prev/Next`.

---

## 4. `StubScroll` — пагинация без собственной клавиатуры

`src/aiogram_dialog/widgets/kbd/stub_scroll.py`

```python
class StubScroll(Keyboard, BaseScroll):
    def __init__(self, id: str,
                 pages: str | int | PagesGetter | MagicFilter,
                 on_page_changed: OnPageChangedVariants = None): ...
```

Это **скролл-«пустышка»**: хранит текущую страницу и умеет считать страницы, но
рисует пустую клавиатуру `[[]]` (`_render_keyboard`, `:59`). Нужен, чтобы
**связать пейджер с тем, что само пагинацию не предоставляет** — например,
текст из getter, `StaticMedia` по номеру страницы, любой ручной рендеринг,
зависящий от номера страницы.

Число страниц задаётся `pages` (`:52`):

| Тип `pages` | Обработчик | Поведение |
|---|---|---|
| `str` | `new_pages_field(name)` | `data.get(name)` — берёт число страниц из ключа getter. |
| `MagicFilter` (`F[...]`) | `new_pages_magic(f)` | `f.resolve(data)`. |
| `int` или `PagesGetter` | `new_pages_fixed` / как есть | фиксированное число / своя функция `(data, widget, manager)->int`. |

`get_page_count` просто зовёт `self._pages(data, self, manager)` (`:66`).

Типовой паттерн (`example/scrolls.py:222`): getter отдаёт `pages` и контент по
номеру страницы, `StubScroll(id, pages="pages")` хранит страницу, `NumberedPager`
рисует кнопки. Текст/медиа окна читают `current_page` из `StubScroll.get_page()`:

```python
async def paging_getter(dialog_manager, **_):
    current_page = await dialog_manager.find("stub_scroll").get_page()
    return {"pages": 7, "current_page": current_page + 1, ...}
# ...
StubScroll(id="stub_scroll", pages="pages")
NumberedPager(scroll="stub_scroll")
StaticMedia(path=Format("media/{current_page}.png"))  # реагирует на страницу
```

> `StubScroll._render_keyboard` возвращает `[[]]` (ряд с нулём кнопок), не `[]`.
> На итоговую клавиатуру это не влияет (пустые ряды отфильтровываются при сборке),
> но это сознательный «непустой» результат.

---

## 5. `ListGroup` — повторяемый набор виджетов на список

`src/aiogram_dialog/widgets/kbd/list_group.py`

### 5.1. Сигнатура (`list_group.py:30`)

```python
class ListGroup(Keyboard, BaseScroll):
    def __init__(
        self,
        *buttons: Keyboard,
        id: str,
        item_id_getter: ItemIdGetter,   # Callable[[Any], str | int]
        items: ItemsGetterVariant,
        when: WhenCondition = None,
        page_size: int = 0,
        on_page_changed: OnPageChangedVariants = None,
    ):
```

В отличие от `Select` (генерит простые кнопки), `ListGroup` **повторяет
произвольный набор виджетов для каждого элемента** `items`. Наследует `BaseScroll`
→ умеет пагинироваться (`page_size`) и управляться пейджерами.

| Параметр | Тип | Назначение |
|---|---|---|
| `*buttons` | `Keyboard` | Шаблон виджетов, повторяемый на каждый item. |
| `id` | `str` | **Обязателен.** Ключ widget_data + префикс callback. |
| `item_id_getter` | `Callable[[item], str\|int]` | Уникальный id элемента (попадает в callback). |
| `items` | `str \| Callable \| MagicFilter \| Sequence` | Источник списка (через `get_items_getter`, см. `common/items.py`). |
| `when` | `WhenCondition` | Скрыть весь виджет. |
| `page_size` | `int` | `0` — без пагинации (всё на одной странице, `get_page_count→1`). |
| `on_page_changed` | вариант | Коллбэк смены страницы. |

`items` принимает: строку-ключ getter (`itemgetter`), `MagicFilter` (`F["..."]`),
произвольный `Callable[[data], Sequence]`, либо готовую `Sequence`
(`common/items.py:28`).

### 5.2. Рендеринг элементов (`_render_keyboard`, `:60` → `_render_item`, `:77`)

1. `items = items_getter(data)`. При `page_size>0` берётся срез текущей страницы:
   `offset = min(total_pages-1, page) * page_size`, `items[offset:offset+page_size]`.
2. Для каждого item (`enumerate(items, offset)`) вызывается `_render_item`:
   - формирует **данные строки** `{"data": data, "item": item, "pos": pos+1, "pos0": pos}`
     — внутри шаблонных виджетов `item` доступен как `{item}`, исходный getter —
     как `{data[...]}` (см. `example/list_group.py:64` `Format("🔘 {item} ({data[item]})")`);
   - создаёт `SubManager(widget=self, manager, widget_id=self.widget_id, item_id=item_id)`
     — **отдельный контекст хранилища на каждый item**;
   - рендерит каждый шаблонный виджет с `sub_manager`;
   - **переписывает callback_data** каждой кнопки в `id:<item_id>:<orig_callback>`
     (`:97`). Так item_id попадает в callback.

### 5.3. Маршрутизация колбэков (`_process_item_callback`, `:113`)

callback `id:<item_id>:<rest>` разбирается: `item_id, callback_data = data.split(":", 1)`.
Создаётся `callback.model_copy(update={"data": callback_data})` (восстанавливается
оригинальный callback вложенного виджета), и собирается `SubManager` для этого
`item_id`. Затем `b.process_callback(...)` для каждого шаблонного виджета.
**В обработчике клика** `dialog_manager.item_id` равен item_id строки.

### 5.4. `find` и `SubManager`

- `ListGroup.find(widget_id)` (`:104`): сам себя или вложенный виджет по id.
- **Внутри шаблона** менеджер — это `SubManager`, поэтому:
  - `manager.find("check")` (`SubManager.find`, `sub_manager.py:88`) вернёт
    `ManagedCheckbox`, адаптированный под **текущую строку** (его `is_checked()`
    относится к этому item). См. `example/list_group.py:36` `when_checked`.
  - `manager.find_in_parent(id)` (`sub_manager.py:94`) — искать виджеты **вне**
    строки (в родительском `DialogManager`).
- `SubManager.current_context()` (`sub_manager.py:58`) подменяет `widget_data` на
  **вложенный словарь** `widget_data[widget_id][item_id]` — отсюда раздельное
  состояние Checkbox/Radio по каждому элементу.

### 5.5. Состояние страницы у ListGroup (`get_page`/`set_page`, `:138`)

Хитрость: страница `ListGroup` хранится в **`SubManager` c `item_id=""`** (пустая
строка), т.е. в `widget_data[id][""]`. Это отделяет состояние пагинации от
состояния отдельных элементов (`widget_data[id][<item_id>]`).
`get_page_count` (`:54`): `1` при `page_size==0`, иначе по числу items.

### 5.6. `ManagedListGroup` (`list_group.py:164`)

```python
class ManagedListGroup(ManagedScroll, ManagedWidget[ListGroup]):
    def find_for_item(self, widget_id: str, item_id: str) -> Any | None
```

- Наследует `ManagedScroll` → есть `get_page()`/`set_page()`/`get_page_count()`.
- `find_for_item(widget_id, item_id)` (`:165`) — найти **managed-виджет шаблона
  для конкретного item_id** извне (из getter/другого хендлера). Возвращает
  виджет, обёрнутый `SubManager` с нужным `item_id`. Если такого виджета нет — `None`.

```python
lg: ManagedListGroup = dialog_manager.find("lg")
check = lg.find_for_item("check", item_id="apple")  # ManagedCheckbox для 'apple'
```

---

## 6. Текстовые и медиа-скроллы (для полноты протокола)

Эти виджеты не входят в `kbd`, но реализуют тот же `Scroll` и управляются теми же
пейджерами — критично для понимания «единого механизма».

| Виджет | Файл | `page_size` смысл | get_page_count |
|---|---|---|---|
| `List` | `widgets/text/list.py:18` | элементов на странице (по умолч. `None` = всё) | `len//size + остаток`; `0` если пусто |
| `ScrollingText` | `widgets/text/scrolling_text.py:11` | **символов** на странице | по длине текста |
| `MediaScroll` | `widgets/media/scroll.py:16` | нет page_size: 1 item = 1 страница | `len(items)` |

`List` отдаёт в шаблон поля `current_page/current_page1/pages/data/item/pos/pos0`
(`text/list.py:50`). `ScrollingText` режет **строку текста** на куски по
`page_size` символов. Один `NumberedPager(scroll="list_scroll")` управляет
текстовым `List` так же, как клавиатурным `ScrollingGroup`.

Тест `tests/widgets/media/test_scroll.py` подтверждает контракт скролла на примере
`MediaScroll`: `set_page(event, page, manager)` и `managed(manager).set_page(page)`
меняют рендеримый item.

---

## 7. Связи с остальной библиотекой

- **`widget_data` / FSM:** страница хранится в контексте окна
  (`Actionable.get/set_widget_data` → `manager.current_context().widget_data`),
  значит переживает перерисовки и хранится в storage aiogram. Сброс контекста
  (`RESET_STACK`, рестарт диалога) сбрасывает страницу на 0.
- **`DialogManager.find` / `ManagedScroll`:** `manager.find(id)` возвращает
  `widget.managed(self)` (`manager/manager.py:538`); для скролла это
  `ManagedScroll`/`ManagedListGroup`.
- **`Window.render`:** окно рендерит клавиатуру одним вызовом
  `keyboard.render_keyboard` (`window.py:101`). Поэтому пейджер и его скролл
  **обязаны быть в одном окне** — иначе `_find_scroll`→`manager.find` не найдёт
  скролл (вернёт `None`, упадёт на `.set_page`).
- **`Group`:** `ScrollingGroup` — это `Group` + скролл; раскладка по `width`
  идентична обычной `Group`.
- **Style:** пейджеры рендерят `style`/`icon_custom_emoji_id`
  (`widgets/style`, `EMPTY_STYLE`), что требует поддержки `ButtonStyle` в aiogram.

---

## 8. Подводные камни и краевые случаи

1. **`ScrollingGroup(height=0)` → `ZeroDivisionError`.** Дефолт `height=0`
   (`scrolling_group.py:21`), а `_get_page_count` делит на `self.height`
   (`:37`). **`height` нужно задавать всегда** (>0). Это легко пропустить, т.к.
   параметр имеет дефолт и не помечен обязательным.

2. **`id` скролла обязан быть уникальным в рамках контекста** и валидным по
   `ID_PATTERN = ^[a-zA-Z0-9_.]+$` (`action.py:8`); иначе `InvalidWidgetIdError`
   (`api/exceptions.py:47`). Два скролла с одним id будут делить хранилище страницы
   и ловиться `find` непредсказуемо.

3. **Пейджеры по умолчанию делят `id="__pager__"`** (`DEFAULT_PAGER_ID`). Несколько
   пейджеров на один скролл в одном окне формально нарушают уникальность id
   виджетов. Работает (страница пишется в скролл, а не в пейджер), но для чистоты
   и предсказуемого `find` задавайте пейджерам явные `id`, если их несколько.

4. **Пейджер и его скролл — в одном окне.** `_find_scroll` ищет через
   `manager.find(scroll_id)` по дереву **текущего окна**. Скролл из другого окна
   не найдётся.

5. **`hide_pager` + внешний пейджер.** Если у `ScrollingGroup` оставить встроенный
   пейджер и одновременно добавить внешние Pager-виджеты, на экране будет **два
   пейджера**. Для кастомной пагинации ставьте `hide_pager=True`
   (`example/scrolls.py:148`).

6. **Синхронизация `StubScroll`/`List` + общий пейджер не происходит сама.**
   Несколько скроллов имеют **независимые** счётчики страниц. Чтобы один пейджер
   двигал несколько объектов, используйте `on_page_changed=sync_scroll([...])` на
   «ведущем» скролле (а пейджер вешайте на него). Без `sync_scroll` второй объект
   останется на своей странице.

7. **`get_page` 0-based, отображение 1-based.** В UI используйте `*_page1`-поля
   (`current_page1`, `target_page1`). В getter не забудьте `+1` (как в примерах).

8. **Клампинг страницы при уменьшении данных.** Если число элементов уменьшилось,
   `current_page` клампится к `last_page` при рендере (`scrolling_group.py:57`,
   `text/list.py:46`), но **в widget_data остаётся старое большое значение** —
   при увеличении данных страница «прыгнет». При смене набора данных при
   необходимости явно вызывайте `set_page(0)`.

9. **Вложенные id в `ListGroup`.** Внутри `ListGroup` менеджер — `SubManager`;
   `manager.find("x")` ищет **в строке** (адаптировано под item_id), `find` вне
   строки — `find_in_parent`. При вложении `ListGroup` в `ListGroup` родительский
   менеджер тоже `SubManager` (см. note в `docs/.../list_group/index.rst:19`).
   `item_id_getter` обязан давать **стабильные уникальные** id: они идут в
   callback и в ключ `widget_data[id][item_id]` (состояние Checkbox/Radio).
   Двоеточие в самом callback вложенного виджета безопасно — `split(":", 1)`
   режет только по первому разделителю item_id.

10. **`page_size=0` у `ListGroup`** (дефолт) = одна страница, пагинация выключена,
    срез не берётся (`_render_keyboard`, `:65` — ветка `else: offset=0`).
    У `List` (текст) дефолт `page_size=None` с тем же смыслом «всё на одной».

11. **`on_page_changed` вызывается даже без реальной смены страницы**
    (`scroll.py:73-78`). Не закладывайтесь на то, что коллбэк = «страница точно
    изменилась».

12. **`get_page_count(data)` у `ManagedScroll` требует `data`** (словарь окна),
    которого в getter обычно нет. Если нужно знать число страниц извне — считайте
    его самостоятельно или передавайте сформированный `data`.

---

## 9. Шпаргалка по выбору

| Задача | Решение |
|---|---|
| Много кнопок → постранично | `ScrollingGroup(*btns, id=, height=N)` (встроенный пейджер) |
| Кастомные кнопки навигации | `ScrollingGroup(..., hide_pager=True)` + `Prev/Next/...` или `NumberedPager` |
| Пагинация длинного текста-списка | `List(..., id=, page_size=N)` + `NumberedPager(scroll=id)` |
| Пагинация сплошного текста | `ScrollingText(..., id=, page_size=символов)` + пейджер |
| Листание медиа | `MediaScroll(items=, media=, id=)` + пейджер |
| Пагинация «снаружи» (текст/медиа из getter) | `StubScroll(id=, pages=...)` + пейджер, getter читает `get_page()` |
| Повтор набора виджетов на список | `ListGroup(*tpl, id=, item_id_getter=, items=, page_size=)` |
| Один пейджер на 2 скролла | `on_page_changed=sync_scroll("other_id")` на ведущем скролле |
