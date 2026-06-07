# Зона №11 — Виджеты выбора: Select, Radio, Multiselect, Toggle и Managed-обёртки

> **Зона:** Виджеты выбора из списка (`Select`, `Radio`, `Multiselect`, `Toggle`), их базовый класс `StatefulSelect`, способ задания списка элементов (`ItemsGetter`) и `Managed*`-обёртки для работы из getter/handler.
>
> **Изученные файлы (прочитаны целиком, сверено с кодом, не по памяти):**
>
> | Файл | Назначение |
> |------|-----------|
> | `src/aiogram_dialog/widgets/kbd/select.py` | Все классы зоны: `Select`, `StatefulSelect`, `Radio`, `Multiselect`, `Toggle`, `ManagedRadio/Multiselect/Toggle`, протоколы `OnItemClick`/`OnItemStateChanged` |
> | `src/aiogram_dialog/widgets/common/items.py` | `get_items_getter` — 4 способа задать `items` |
> | `src/aiogram_dialog/widgets/kbd/base.py` | `Keyboard` — базовый класс, callback-роутинг, `_item_callback_data`, `Or` |
> | `src/aiogram_dialog/widgets/common/action.py` | `Actionable` — `widget_id`, `get_widget_data`/`set_widget_data`, валидация id |
> | `src/aiogram_dialog/widgets/common/base.py` | `BaseWidget` — `managed`, `find` |
> | `src/aiogram_dialog/widgets/common/managed.py` | `ManagedWidget` — обёртка с `__getattr__`-делегированием |
> | `src/aiogram_dialog/widgets/common/when.py` | `Whenable`, `WhenCondition` |
> | `src/aiogram_dialog/widgets/text/multi.py` | `Case` — переключение checked/unchecked текста |
> | `src/aiogram_dialog/widgets/style/base.py`, `style/multi.py` | `Style`, `EMPTY_STYLE`, `StyleCase` |
> | `src/aiogram_dialog/widgets/widget_event.py` | `WidgetEventProcessor`, `ensure_event_processor` |
> | `src/aiogram_dialog/api/internal/widgets.py` | протоколы `Widget`/`TextWidget`/`StyleWidget`/`KeyboardWidget`, `ButtonStyle`, `RawKeyboard` |
> | `src/aiogram_dialog/manager/manager.py:538` | `DialogManager.find` → `widget.managed(self)` |
> | docs: `select/`, `radio/`, `multiselect/`, `toggle/` (index.rst + example.py) | официальные примеры |
> | `example/mega/bot_dialogs/select.py` | mega-пример со всеми 4 виджетами |
> | tests: `test_select.py`, `test_radio.py`, `test_multiselect.py`, `test_toggle.py` | поведенческие тесты |

---

## 1. Иерархия классов

```
Keyboard (kbd/base.py:15)            ← Actionable + Whenable + KeyboardWidget
 └─ Select[T]                        (select.py:60)    одиночный клик, без состояния
     └─ StatefulSelect[T] (ABC)      (select.py:138)   checked/unchecked текст+стиль, состояние в widget_data
         ├─ Radio[T]                 (select.py:236)   одиночный выбор
         │   └─ Toggle[T]            (select.py:475)   как Radio, но 1 кнопка-переключатель
         └─ Multiselect[T]           (select.py:345)   множественный выбор + min/max

ManagedWidget[W] (common/managed.py:9)
 ├─ ManagedRadio[T]                  (select.py:327)
 │   └─ ManagedToggle[T]             (select.py:538)   pass — наследует методы ManagedRadio
 └─ ManagedMultiselect[T]            (select.py:453)
```

`Select` — это `Generic[T]`, где `T` — тип, в который `type_factory` приводит `item_id` (строку) обратно. По умолчанию `T = str`.

**Тип-алиасы (select.py:28-31):**
```python
T = TypeVar("T")
TypeFactory = Callable[[str], T]          # str -> T
ItemIdGetter = Callable[[Any], str | int] # item -> id
```

---

## 2. `Select[T]` — базовый виджет выбора

`src/aiogram_dialog/widgets/kbd/select.py:60`

### Сигнатура `__init__`

```python
Select(
    text: TextWidget,                        # обязательный, рендер каждой кнопки
    id: str,                                 # обязательный, widget_id (callback-префикс)
    item_id_getter: ItemIdGetter,            # обязательный: item -> str | int
    items: ItemsGetterVariant,               # обязательный: str | callable | MagicFilter | Sequence
    type_factory: TypeFactory[T] = str,      # str -> T, приведение id обратно
    on_click: OnItemClick["Select[T]", T] | WidgetEventProcessor | None = None,
    when: WhenCondition = None,              # str | MagicFilter | Predicate | None
    style: StyleWidget = EMPTY_STYLE,        # стиль кнопок (aiogram ButtonStyle + emoji)
)
```

### Что хранит (select.py:76-82)
- `self.text` — TextWidget каждой кнопки.
- `self.type_factory` — функция приведения.
- `self.on_click = ensure_event_processor(on_click)` — всегда `WidgetEventProcessor` (даже если передали `None` → `SimpleEventProcessor(None)`, который ничего не делает).
- `self.item_id_getter` — как взять id из элемента.
- `self.items_getter = get_items_getter(items)` — нормализованный `Callable[[dict], Sequence]`.
- `self.style`.

### `_render_keyboard` (select.py:84-94)
Возвращает **один ряд** со всеми кнопками: `[[btn, btn, ...]]`. Перебирает `self.items_getter(data)` с `enumerate`, для каждого вызывает `_render_button(pos, item, item, data, manager)` — для `Select` `item` и `target_item` совпадают.

> Все элементы в одном ряду. Чтобы разложить по строкам — оборачивай в `Column`/`Group`/`Row` (см. doc-note `select/index.rst`).

### `_render_button` (select.py:96-120) — данные для рендера текста/стиля
В `text`/`style` передаётся словарь:
```python
{
    "data": data,          # исходные данные окна (getter)
    "item": item,          # сам элемент (что показываем)
    "target_item": target_item,  # элемент для callback (для Toggle отличается!)
    "pos": pos + 1,        # позиция с 1
    "pos0": pos,           # позиция с 0
}
```
Кнопка:
```python
InlineKeyboardButton(
    text=await self.text.render_text(data, manager),
    callback_data=self._item_callback_data(item_id),   # f"{id}:{item_id}"
    style=...,                # ButtonStyle | None (aiogram>=3.x)
    icon_custom_emoji_id=..., # str | None
)
```
`item_id = self.item_id_getter(target_item)` — **id берётся из `target_item`, не из `item`** (важно для Toggle).

### Callback-data: как формируется (base.py:49-60)
```python
callback_prefix()      -> f"{widget_id}:"          # напр. "s_fruits:"
_item_callback_data(x) -> f"{widget_id}:{x}"       # напр. "s_fruits:apple_a"
```
- `item_id` от `item_id_getter` может быть `str` или `int` — в callback он подставляется через f-string, т.е. **всегда строкой**.
- При входящем callback (`base.py:62-82`): сравнивается `callback.data` с `widget_id`; если начинается с префикса `"{id}:"` → `_process_item_callback(callback, callback.data[len(prefix):], ...)` — хвост (id) идёт строкой.

### `_process_item_callback` (select.py:122-135)
```python
await self.on_click.process_event(
    callback,
    self.managed(manager),       # ManagedWidget-обёртка как `widget`
    manager,
    self.type_factory(data),     # data — строка-хвост callback, приводится к T
)
```
**Здесь `type_factory` приводит строку обратно в `T`.** В `on_click` приходит уже типизированный `item_id: T`.

### Сигнатура `on_click` (протокол `OnItemClick`, select.py:47-57)
```python
async def on_click(
    event: CallbackQuery,
    select: ManagedT,        # ManagedSelect/ManagedRadio/... (обёртка)
    dialog_manager: DialogManager,
    data: T,                 # item_id, приведённый type_factory
) -> ...
```
Все 4 параметра позиционные (`/` в протоколе). В примерах часто называют 4-й аргумент `item_id` или `selected_item`.

---

## 3. `ItemsGetter` — 4 способа задать `items`

`src/aiogram_dialog/widgets/common/items.py`

```python
ItemsGetter = Callable[[dict], Sequence]
ItemsGetterVariant = str | ItemsGetter | MagicFilter | Sequence
```

`get_items_getter(attr_val)` (items.py:28-36) нормализует к `Callable[[dict], Sequence]`:

| Что передали | Поведение | Пример |
|---|---|---|
| **`str`** | `operator.itemgetter(attr_val)` — ключ в данных окна | `items="fruits"` → `data["fruits"]` |
| **`MagicFilter`** | `f.resolve(data)`; **если результат не `Sequence` → `[]`** | `items=F["others"]["fruits"]` |
| **`Callable`** | вызывается как есть с `data` | `items=lambda d: d["fruits"]` |
| **`Sequence`** (иначе) | литеральный список, замороженный в `identity` | `items=[("1","Apple"), ...]` |

> **Edge case (str):** `itemgetter("fruits")` бросит `KeyError`, если ключа нет в данных окна — в отличие от `MagicFilter`, который при не-Sequence тихо вернёт `[]`. Ключ должен присутствовать в результате getter / preview_data.
>
> **Edge case (MagicFilter):** проверка `isinstance(items, Sequence)` — `str` тоже `Sequence`! Если магия вернёт строку, её посимвольно разложат в кнопки. Возвращай списки/кортежи.
>
> **Литеральный список** удобен для статики, но тогда `item_id_getter` должен уметь достать id из каждого элемента (обычно `operator.itemgetter(0)` для кортежей `(id, name)`).

---

## 4. `StatefulSelect[T]` (ABC) — общий предок Radio/Multiselect/Toggle

`src/aiogram_dialog/widgets/kbd/select.py:138`

Добавляет к `Select` **два текста и два стиля** (checked/unchecked) и состояние.

```python
StatefulSelect(
    checked_text: TextWidget,
    unchecked_text: TextWidget,
    id: str,
    item_id_getter: ItemIdGetter,
    items: ItemsGetterVariant,
    type_factory: TypeFactory[T] = str,
    on_click: OnItemClick | WidgetEventProcessor | None = None,
    on_state_changed: OnItemStateChanged | WidgetEventProcessor | None = None,
    when: str | Callable | None = None,
    checked_style: StyleWidget = EMPTY_STYLE,
    unchecked_style: StyleWidget = EMPTY_STYLE,
)
```

Внутри (select.py:161-177):
- `text = Case({True: checked_text, False: unchecked_text}, selector=self._is_text_checked)` — переключение текста по «отмечен ли элемент».
- `style = StyleCase({True: checked_style, False: unchecked_style}, selector=self._is_text_checked)`.
- В `Select.__init__` передаётся `on_click=self._process_click` — **перехватывает родительский `on_click`**.
- `self.on_item_click = ensure_event_processor(on_click)` — пользовательский `on_click`.
- `self.on_state_changed = ensure_event_processor(on_state_changed)`.

### Цепочка обработки клика (важно понимать порядок)
1. `_process_item_callback` (select.py:220-233) — **переопределён**: вызывает `self.on_click.process_event(...)` с `data` (строкой, **БЕЗ** `type_factory`!), `self.on_click` тут = `self._process_click`.
2. `_process_click` (select.py:197-208):
   - если задан `self.on_item_click` → `on_item_click.process_event(callback, select, manager, self.type_factory(item_id))` — **пользовательский on_click получает уже приведённый `T`**;
   - затем `await self._on_click(...)` — абстрактный метод, реализован в Radio/Multiselect (меняет состояние).
3. `_on_click` вызывает `set_checked`, тот при изменении дёргает `_process_on_state_changed`.

### `_process_on_state_changed` (select.py:179-186)
Вызывает `on_state_changed.process_event(event, managed, manager, self.type_factory(item_id))`. Протокол `OnItemStateChanged` (select.py:34-44):
```python
async def on_state_changed(
    event: ChatEvent,           # CallbackQuery при клике
    select: ManagedT,
    dialog_manager: DialogManager,
    data: T,                    # item_id, приведённый type_factory
)
```

### `_is_text_checked` — абстрактный (select.py:188-195)
Селектор для `Case`/`StyleCase`: получает `data` (словарь рендера, где есть `data["item"]`), возвращает `bool`. Реализуется в Radio/Multiselect/Toggle по-разному.

---

## 5. `Radio[T]` — одиночный выбор

`src/aiogram_dialog/widgets/kbd/select.py:236`

Сигнатура `__init__` совпадает со `StatefulSelect` (те же параметры, `on_click`/`on_state_changed` типизированы как `OnItemClick["ManagedRadio[T]", T]`). **Нет min/max.**

### Состояние
- Хранится в `widget_data` контекста как **строка** (один id) или `None`.
- `get_widget_data(manager, None)` / `set_widget_data(manager, item_id_str)` (action.py:23-40 → `manager.current_context().widget_data[widget_id]`).

### Методы (на самом виджете, не Managed)

| Метод | Строки | Возврат / эффект |
|---|---|---|
| `get_checked(manager) -> T \| None` | 274-278 | id выбранного, приведённый `type_factory`; `None` если ничего |
| `_get_checked(manager) -> str \| None` | 280-281 | сырое значение (строка/None) |
| `set_checked(event, item_id: T, manager)` (async) | 283-291 | `set_widget_data(str(item_id))`; если значение изменилось → `_process_on_state_changed` |
| `is_checked(item_id: T, manager) -> bool` | 293-296 | `str(item_id) == _get_checked(...)` |
| `_is_text_checked(...)` | 303-312 | для рендера; в preview сравнивает с `_preview_checked_id` |
| `_on_click(...)` (async) | 314-321 | `await set_checked(callback, item_id, manager)` |
| `managed(manager) -> ManagedRadio[T]` | 323-324 | обёртка |

> **Сравнение всегда по строке:** `is_checked`/`set_checked` приводят `item_id` через `str(...)`. Поэтому `item_id_getter` может вернуть `int`, но внутри хранится/сравнивается строка. `get_checked` возвращает обратно через `type_factory` (см. test_radio.py: `type_factory=validate_datetime` → `get_checked()` отдаёт `datetime`).

### `ManagedRadio[T]` (select.py:327-342)
Обёртка `ManagedWidget[Radio[T]]`. Методы без `manager` (берётся из `self.manager`):

| Метод | Возврат |
|---|---|
| `get_checked() -> T \| None` | id выбранного |
| `set_checked(item_id: T)` (async) | устанавливает выбор (`self.manager.event` как event) |
| `is_checked(item_id: T) -> bool` | проверка |

Прочие атрибуты делегируются на виджет через `ManagedWidget.__getattr__` (managed.py:14).

---

## 6. `Multiselect[T]` — множественный выбор

`src/aiogram_dialog/widgets/kbd/select.py:345`

### Сигнатура (доп. параметры min/max)
```python
Multiselect(
    checked_text, unchecked_text, id, item_id_getter, items,
    min_selected: int = 0,       # минимум; клик-снятие игнорируется, если len == min
    max_selected: int = 0,       # 0 = без лимита; клик-добавление игнорируется при достижении
    type_factory=str,
    on_click=None,               # OnItemClick["ManagedMultiselect[T]", T]
    on_state_changed=None,
    when=None,
    checked_style=EMPTY_STYLE, unchecked_style=EMPTY_STYLE,
)
```

### Состояние
- В `widget_data` хранится **`list[str]`** (по умолчанию `[]`).

### Методы

| Метод | Строки | Возврат / эффект |
|---|---|---|
| `get_checked(manager) -> list[T]` | 407-408 | список id, каждый через `type_factory` |
| `_get_checked(manager) -> list[str]` | 404-405 | сырой список строк (default `[]`) |
| `is_checked(item_id: T, manager) -> bool` | 398-402 | `str(item_id) in _get_checked(...)` |
| `set_checked(event, item_id: T, checked: bool, manager)` (async) | 415-436 | добавляет/убирает с учётом min/max |
| `reset_checked(event, manager)` (async) | 410-413 | `set_widget_data([])` — **БЕЗ** `on_state_changed`! |
| `_on_click(...)` (async) | 438-447 | переключает: `set_checked(..., not is_checked(...))` |
| `managed(manager) -> ManagedMultiselect[T]` | 449-450 | обёртка |

### Логика `set_checked` (select.py:415-436) — точная
```python
item_id_str = str(item_id)
data = self._get_checked(manager)   # текущий list[str]
changed = False
if item_id_str in data:
    if not checked and len(data) > self.min_selected:   # снимаем только если выше минимума
        data.remove(item_id_str); changed = True
else:
    if checked:
        if self.max_selected == 0 or self.max_selected > len(data):  # добавляем если есть место
            data.append(item_id_str); changed = True
if changed:
    self.set_widget_data(manager, data)
    await self._process_on_state_changed(event, item_id_str, manager)
```
- `min_selected`: **не влияет на начальное состояние** (можно стартовать с 0 выбранных). Запрещает снятие, если опустимся ниже минимума. Подтверждено `test_min_selected_multiselect`.
- `max_selected=0` означает «без лимита». Подтверждено `test_max_selected_multiselect` (с `max=2` третий клик игнорируется).
- `reset_checked` **сбрасывает в `[]` напрямую**, не уважая `min_selected` и не вызывая `on_state_changed`.

### `ManagedMultiselect[T]` (select.py:453-472)

| Метод | Возврат |
|---|---|
| `is_checked(item_id: T) -> bool` | проверка |
| `get_checked() -> list[T]` | список выбранных id |
| `reset_checked()` (async) | сброс всех |
| `set_checked(item_id: T, checked: bool)` (async) | установить состояние одного |

> **Warning из доки (multiselect/index.rst):** Multiselect хранит ВСЕ отмеченные id, даже если элемент исчез из данных окна (полезно при пагинации, но может удивить, если данные реально удалены). `get_checked()` вернёт «осиротевшие» id.

---

## 7. `Toggle[T]` — кнопка-переключатель (одна кнопка)

`src/aiogram_dialog/widgets/kbd/select.py:475` — наследник `Radio[T]`.

### Сигнатура
```python
Toggle(
    text: TextWidget,            # ОДИН текст (не checked/unchecked!)
    id, item_id_getter, items,
    type_factory=str,
    on_click=None,               # OnItemClick["ManagedToggle[T]", T]
    on_state_changed=None,
    when=None,
    style: StyleWidget = EMPTY_STYLE,
)
```
Внутри (select.py:496-502): передаёт `checked_text=text, unchecked_text=text` в `Radio` (текст один и тот же в обоих состояниях), отдельно ставит `self.style`. **`checked_style`/`unchecked_style` не выставляются** — `StyleCase` использует `EMPTY_STYLE` для обоих, а `self.style` назначается ПОСЛЕ super().__init__ и переопределяет поле `style` Select. То есть для Toggle стиль один (`style=`), а не два.

### `_render_keyboard` (select.py:504-535) — главное отличие
Рендерит **ровно одну кнопку**, текст которой = текущий выбранный элемент, а callback ведёт к **следующему** элементу (циклически):
- если ничего не выбрано (`selected is None`) → показывается первый элемент;
- если выбран первый → показывается первый;
- иначе ищется выбранный элемент по `item_id_getter(i) == selected`; если не найден → fallback на первый (`(0, first_item)`);
- `next_item = next(items_it, first_item)` — следующий по итератору, при достижении конца → снова первый;
- кнопка: `_render_button(pos, item, next_item, ...)` — **`item` (показываем выбранный) ≠ `target_item` (callback ведёт к next_item)**.

Поведение подтверждено `test_toggle.py`: старт → "Apple", `set_checked("2")` → следующий рендер показывает "Banana".

> **Edge case:** `_render_keyboard` использует один итератор `items_it` с многократными `next(...)`. Логика поиска `selected` опирается на порядок и единственность id. При пустом списке возвращает `[[]]` (пустой ряд).

### `ManagedToggle[T]` (select.py:538-539)
`class ManagedToggle(ManagedRadio[Radio[T]]): pass` — полностью наследует `get_checked()/set_checked()/is_checked()` от `ManagedRadio`. Отдельной логики нет.

> Toggle полностью совместим и взаимозаменяем с Radio (одно и то же состояние, тот же id). В mega-примере Toggle и Radio даже используют один `id="radio"` (в разных окнах).

---

## 8. Где и как хранится состояние

- Хранилище — `manager.current_context().widget_data[widget_id]` (action.py:29, 40).
- `Radio/Toggle`: строка-id или отсутствует (`None`).
- `Multiselect`: `list[str]`.
- `widget_id` обязателен для stateful-виджетов: без id `get_widget_data` будет писать под ключ `None`. Кроме того, для callback нужен префикс `"{id}:"` — без id `callback_prefix()` вернёт `None` и роутинг сломается.
- **Валидация id (action.py:8-21):** `ID_PATTERN = ^[a-zA-Z0-9_.]+$`. Недопустимый id (пробел, `:`, кириллица, дефис) → `InvalidWidgetIdError`. **Двоеточие в id запрещено** — иначе сломался бы парсинг callback по префиксу.

---

## 9. Чтение выбора в getter / обработчике

Через `manager.find(id)` (manager.py:538-542) → возвращает `widget.managed(self)`, т.е. `ManagedRadio`/`ManagedMultiselect`/`ManagedToggle`:

```python
async def getter(dialog_manager: DialogManager, **_):
    radio = dialog_manager.find("radio")          # ManagedRadio
    multi = dialog_manager.find("multi")          # ManagedMultiselect
    return {
        "current": radio.get_checked(),           # T | None
        "selected": multi.get_checked(),          # list[T]
    }

async def handler(callback, button, manager: DialogManager):
    await manager.find("multi").reset_checked()   # см. mega/select.py:70-75
```

В `on_click`/`on_state_changed` обёртка приходит вторым аргументом (`select`) — можно сразу `select.get_checked()`. Внутри самого виджета методы требуют явный `manager`.

---

## 10. Связи с остальной библиотекой

- **Layout-виджеты:** `Select` и наследники рендерят один ряд (Select) или одну кнопку (Toggle); раскладку дают `Column`/`Row`/`Group` (kbd/group.py). В mega-примере все обёрнуты в `Column`.
- **Text-виджеты:** `text`/`checked_text`/`unchecked_text` — любой `TextWidget` (`Const`, `Format`, `Multi`, `Case`, `Jinja`…). `Format` получает `item`, `data`, `pos`, `pos0` (см. §2). `StatefulSelect` строит `Case` поверх них.
- **Style-виджеты:** `style`/`checked_style`/`unchecked_style` — `Style(style=..., emoji_id=..., when=...)` (aiogram `ButtonStyle` enum, иначе `str`-алиас при старом aiogram) и `icon_custom_emoji_id`. `EMPTY_STYLE` по умолчанию.
- **`WidgetEventProcessor`** (widget_event.py): `on_click`/`on_state_changed` оборачиваются `ensure_event_processor`. Можно передать как обычную async-функцию, так и готовый процессор.
- **`when`** (when.py): `str` (ключ-флаг в данных), `MagicFilter`, `Predicate(data, widget, manager)->bool`, или `None`. Скрытый виджет (`is_` → False) рендерит `[]` (base.py:32-34), но callback всё равно обрабатывается, если придёт.
- **`List` text-виджет:** в mega-примере тот же `items=FRUITS_KEY` используется и в `List(...)` для текстового списка — items-механизм общий.
- **preview / `manager.is_preview()`:** в режиме превью `Radio._is_text_checked` сравнивает с `_preview_checked_id`, `Multiselect` — «через одного» по `ord(item_id[-1]) % 2` (select.py:391-395), просто чтобы кнопки визуально отличались. Для превью нужен `preview_data=` в окне.

---

## 11. Подводные камни и краевые случаи (для продакшн-шаблона)

1. **`item_id` — всегда строка в callback и в состоянии.** `item_id_getter` может вернуть `int`, но в callback_data и в `widget_data` он становится строкой (`str(...)`/f-string). Чтобы получить обратно нужный тип — задавай `type_factory` (напр. `int`, `int`+lookup, кастомный парсер; см. test_radio.py `validate_datetime`). Сравнения `is_checked`/`set_checked` идут по строке, так что `type_factory` влияет только на `get_checked` и на аргумент `item_id` в `on_click`/`on_state_changed`.

2. **Длина callback_data ≤ 64 байта (лимит Telegram).** `callback_data = f"{widget_id}:{item_id}"`. Длинный `widget_id` + длинный `item_id` (например, UUID или путь) могут превысить лимит → Telegram отклонит/обрежет кнопку. Делай короткие id; для длинных ключей храни маппинг и используй короткий суррогатный id в `item_id_getter`.

3. **`id` не может содержать `:`, пробелы, дефисы, не-ASCII.** `ID_PATTERN = ^[a-zA-Z0-9_.]+$`, иначе `InvalidWidgetIdError` при создании виджета. Двоеточие критично — это разделитель префикса callback.

4. **`min_selected` не задаёт начальный выбор.** Это лишь нижняя граница для снятия. Стартовое состояние — пусто (`[]`); если нужен предзаполненный выбор, вызови `set_checked(..., True, ...)` при старте диалога. `max_selected=0` = безлимит (а не «ноль элементов»).

5. **`reset_checked` игнорирует `min_selected` и не зовёт `on_state_changed`.** Сбрасывает в `[]` жёстко (select.py:410-413). Если логика завязана на `on_state_changed`, ресет её не триггерит.

6. **Multiselect помнит исчезнувшие элементы.** При пагинации/смене данных отмеченные id, которых больше нет в `items`, остаются в `get_checked()`. Полезно для пагинации, но фильтруй вручную, если данные действительно удалены.

7. **`items` через `MagicFilter`/строку:** строка (`str`) сама является `Sequence` — если магия вернёт строку, она разложится посимвольно в кнопки; если ключа нет — `itemgetter` бросит `KeyError`, а `MagicFilter` тихо вернёт `[]`. Возвращай списки/кортежи и гарантируй наличие ключа в данных окна и в `preview_data`.

8. **`Select` кладёт все кнопки в один ряд, `Toggle` — одна кнопка.** Без `Column`/`Group` длинный список вылезет в одну строку. Toggle меняет элемент по кругу — нет «снятия выбора» как такового.

9. **Один `id` ↔ одно состояние.** Radio и Toggle с одним id делят `widget_data` — это by design (взаимозаменяемы). Но два разных stateful-виджета с одинаковым id в одном окне будут затирать состояние друг друга.

10. **`on_click` у stateful-виджетов вызывается ДО смены состояния-эффекта, но получает уже типизированный `item_id` (`T`).** Внутри `_process_click` сначала `on_item_click`, потом `_on_click` (меняет состояние). В момент пользовательского `on_click` состояние ещё старое — если нужно «новое» состояние, читай его в `on_state_changed` или после.
