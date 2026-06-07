---
zone: "09"
title: "Базовые клавиатурные виджеты: Button, Url, WebApp, SwitchInlineQuery* + контейнеры Group/Row/Column"
source_repo: "aiogram_dialog (develop, 08abdf0, 2026-05-02)"
aiogram_min: ">=3.14.0"
files:
  - src/aiogram_dialog/widgets/kbd/base.py
  - src/aiogram_dialog/widgets/kbd/button.py
  - src/aiogram_dialog/widgets/kbd/group.py
  - src/aiogram_dialog/widgets/kbd/copy.py
  - src/aiogram_dialog/widgets/common/action.py
  - src/aiogram_dialog/widgets/common/base.py
  - src/aiogram_dialog/widgets/common/when.py
  - src/aiogram_dialog/widgets/widget_event.py
  - src/aiogram_dialog/api/internal/widgets.py
  - src/aiogram_dialog/widgets/style/base.py
  - src/aiogram_dialog/utils.py
  - src/aiogram_dialog/window.py
  - src/aiogram_dialog/dialog.py
status: reference
---

# Зона 09. Базовые клавиатурные виджеты и контейнеры

Заметка покрывает «фундамент» инлайн-клавиатур aiogram_dialog: базовый класс `Keyboard`,
листовые кнопки (`Button`, `Url`, `WebApp`, `LoginURLButton`, `CopyText`, семейство
`SwitchInlineQuery*`) и контейнеры раскладки (`Group`, `Row`, `Column`), плюс обвязку
`Actionable` / `Whenable` / `on_click`. Цель — продакшн-уровень понимания: сигнатуры,
эффекты, `callback_data`, краевые случаи.

---

## 1. Общая модель: как клавиатура попадает в Telegram

Каждый клавиатурный виджет реализует протокол `KeyboardWidget`
(`src/aiogram_dialog/api/internal/widgets.py:82`) с двумя ключевыми методами:

- `render_keyboard(data, manager) -> RawKeyboard` — строит контент;
- `process_callback(callback, dialog, manager) -> bool` — обрабатывает клик.

Тип результата:

```python
ButtonVariant = InlineKeyboardButton | KeyboardButton          # widgets.py:77
RawKeyboard   = list[list[ButtonVariant]]                       # widgets.py:78
```

То есть `RawKeyboard` — это «сырая» матрица строк/кнопок (список строк, каждая строка —
список кнопок). Это **не** `InlineKeyboardMarkup`. Финальную конвертацию делает
`MarkupFactory`.

### Конвейер рендера (Window → factory → Telegram)

`Window.render_kbd` (`src/aiogram_dialog/window.py:98`):

```python
keyboard = await self.keyboard.render_keyboard(data, manager)   # RawKeyboard
return await self.markup_factory.render_markup(data, manager, keyboard)
```

По умолчанию фабрика — `InlineKeyboardFactory`
(`src/aiogram_dialog/widgets/markup/inline_keyboard.py:12`):

```python
add_intent_id(keyboard, manager.current_context().id)           # ВАЖНО: мутирует callback_data
return InlineKeyboardMarkup(inline_keyboard=keyboard)
```

`self.keyboard` в `Window` — это единый корневой виджет (обычно `Group`/`Column`/`Row`,
в который завёрнуты все кнопки окна). У окна одна клавиатура; несколько виджетов
объединяются контейнером.

### Маршрутизация клика (intent_id срезается ДО виджетов)

`Dialog._callback_handler` (`src/aiogram_dialog/dialog.py:141`):

```python
_, callback_data = remove_intent_id(callback.data)              # снимаем intent_id
cleaned_callback = callback.model_copy(update={"data": callback_data})
processed = await window.process_callback(cleaned_callback, self, dialog_manager)
...
await dialog_manager.answer_callback()                          # авто-answer (см. §6)
```

Важное следствие: внутри виджетов (`process_callback`) `callback.data` **уже очищен** от
`intent_id`, то есть равен `widget_id` (для одиночной кнопки) или `widget_id:item`
(для составных). Виджетам про intent знать не нужно.

---

## 2. Базовый класс `Keyboard`

`src/aiogram_dialog/widgets/kbd/base.py:15`

```python
class Keyboard(Actionable, Whenable, KeyboardWidget):
    def __init__(self, id: str | None = None, when: WhenCondition = None): ...
```

Наследует:
- `Actionable` → `widget_id`, `find()`, `get_widget_data()/set_widget_data()`, валидация id;
- `Whenable` → условие видимости `when`;
- `KeyboardWidget` → контракт `render_keyboard` / `process_callback`.

### 2.1. Шаблонный метод рендера (`when`-обвязка)

| Метод | Строка | Назначение |
|---|---|---|
| `render_keyboard(data, manager)` | `base.py:20` | Публичный. Проверяет `when` → при скрытии возвращает `[]`, иначе делегирует `_render_keyboard`. Декорирован `@add_exception_note`. |
| `_render_keyboard(data, manager)` | `base.py:36` | `@abstractmethod`. Переопределяется в наследниках. Вызывается, **только если** виджет не скрыт. |

```python
@add_exception_note
async def render_keyboard(self, data, manager) -> RawKeyboard:
    if not self.is_(data, manager):     # проверка when (Whenable.is_)
        return []
    return await self._render_keyboard(data, manager)
```

**Паттерн для собственных виджетов:** наследуйтесь и переопределяйте `_render_keyboard`,
а не `render_keyboard` — тогда автоматически сохраняется обработка `when`. Это явно
указано в docstring (`base.py:29`).

`@add_exception_note` (`utils.py:230`): на Python ≥3.11 добавляет к любому исключению
note `at <repr(widget)>` (например `<Button id=go>`), что резко упрощает диагностику —
в трейсбеке видно, какой именно виджет упал.

### 2.2. Формирование callback_data

| Метод | Строка | Что возвращает |
|---|---|---|
| `callback_prefix()` | `base.py:49` | `f"{widget_id}:"` или `None` (если id нет) |
| `_own_callback_data()` | `base.py:54` | `widget_id` — для виджета с единственной кнопкой |
| `_item_callback_data(data)` | `base.py:58` | `f"{prefix}{data}"` = `"{widget_id}:{data}"` — для многокнопочных виджетов (Select/Radio/...) |

Таким образом:
- одиночная кнопка → `callback_data == widget_id` (например `"go"`);
- элемент составного виджета → `callback_data == "widget_id:item_id"` (например `"items:42"`).

К этому значению фабрика затем спереди добавит `intent_id + "\x1D"` (см. §7).

### 2.3. Диспетчеризация клика

`process_callback` (`base.py:62`) — единый разборщик. Получает уже очищенный от intent
`callback.data` и решает, чей это клик:

```python
if callback.data == self.widget_id:                  # точное совпадение
    return await self._process_own_callback(...)
prefix = self.callback_prefix()
if prefix and callback.data.startswith(prefix):      # "widget_id:..." 
    return await self._process_item_callback(
        callback, callback.data[len(prefix):], ...)  # item = хвост после "widget_id:"
return await self._process_other_callback(...)       # чужой клик → шанс контейнерам
```

Хуки-«заготовки» (по умолчанию возвращают `False`):

| Хук | Строка | Кто переопределяет |
|---|---|---|
| `_process_own_callback` | `base.py:84` | `Button` (вызывает `on_click`) |
| `_process_item_callback` | `base.py:93` | `Select`/`Radio`/`Multiselect`/пейджеры |
| `_process_other_callback` | `base.py:103` | контейнеры `Group`/`Or` (пробрасывают детям) |

Возврат `bool`: `True` означает «клик обработан, дальше не пробрасывать». Этот флаг
поднимается до `Dialog._need_refresh` и решает, нужно ли перерисовать окно
(`dialog.py:156`).

### 2.4. Класс `Or` и оператор `|`

`base.py:116`/`127`. `kb1 | kb2` создаёт `Or(kb1, kb2)`. `Or._render_keyboard`
возвращает клавиатуру **первого** виджета, давшего непустой результат
(`if res and any(res)`), — это «первый видимый из списка». См. `test_base.py:30`
(`A when F["a"] | B when F["b"] | C`). Перегрузки `__or__/__ror__/__ior__` схлопывают
вложенность, чтобы не плодить `Or(Or(...))`.

---

## 3. `Actionable` (id виджета) и `Whenable` (видимость)

### 3.1. `Actionable` — `src/aiogram_dialog/widgets/common/action.py:11`

```python
ID_PATTERN = re.compile("^[a-zA-Z0-9_.]+$")          # action.py:8

class Actionable(BaseWidget):
    def __init__(self, id: str | None = None):
        if id and not ID_PATTERN.match(id):
            raise InvalidWidgetIdError(f"Invalid widget id: {id}")
        self.widget_id = id
```

- **Допустимые символы id:** только латиница, цифры, `_` и `.`. Пробелы, дефисы,
  кириллица, `:` — запрещены и приводят к `InvalidWidgetIdError`
  (`api/exceptions.py:47`) ещё на этапе **конструирования** виджета (импорт модуля).
  Двоеточие исключено намеренно — оно служебный разделитель `_item_callback_data`.
- `find(widget_id)` (`action.py:17`) — возвращает `self`, если id совпал, иначе `None`.
  Контейнеры расширяют поиск на детей (см. `Group.find`).
- `get_widget_data(manager, default)` / `set_widget_data(manager, value)`
  (`action.py:23`/`34`) — чтение/запись состояния виджета в
  `current_context().widget_data[widget_id]`. Для `Button` не используется (кнопка
  без состояния), но это общий механизм для stateful-виджетов.
- `BaseWidget.managed(manager)` (`common/base.py:8`) по умолчанию возвращает `self`.
  У `Button`/`Url`/контейнеров своего managed-обёртчика нет, поэтому
  `manager.find("go")` вернёт сам объект `Button`.

### 3.2. `Whenable` — `src/aiogram_dialog/widgets/common/when.py:56`

`WhenCondition = str | MagicFilter | Predicate | None` (`when.py:31`).

| Тип `when` | Поведение | Источник |
|---|---|---|
| `None` | всегда показывать (`true_condition`) | `when.py:52` |
| `str` | показывать, если `bool(data.get(when))` (truthy-поле getter'а) | `when.py:34` |
| `MagicFilter` (`F[...]`) | `f.resolve(data)` | `when.py:43` |
| `Predicate` | произвольная функция `(data, widget, manager) -> bool` | `when.py:11` |

`is_(data, manager)` (`when.py:68`) вызывается из `render_keyboard`. Скрытый виджет
даёт `[]` и **не попадает в клавиатуру вообще** (а не «серой кнопкой»).

Сигнатура `Predicate.__call__` (`when.py:13`): `(data, widget, dialog_manager, /)` —
все три позиционные. `data` — словарь из getter'а окна; `widget` — сам виджет.

---

## 4. Листовые кнопки (`button.py`)

Все они наследуют `Keyboard`, рендерят ровно `[[InlineKeyboardButton(...)]]`
(одна строка, одна кнопка) и поддерживают `style: StyleWidget = EMPTY_STYLE`
(см. §8). `text`/`url`/`query` — это `Text`-виджеты (`Const`, `Format`, ...), а не
строки: текст рендерится из `data` окна (динамические подписи).

### 4.1. `Button` — `button.py:24`

```python
OnClick = Callable[[CallbackQuery, "Button", DialogManager], Awaitable]   # button.py:21

class Button(Keyboard):
    def __init__(
        self,
        text: TextWidget,
        id: str,                                       # ОБЯЗАТЕЛЕН (без default)
        on_click: OnClick | WidgetEventProcessor | None = None,
        when: WhenCondition = None,
        style: StyleWidget = EMPTY_STYLE,
    ): ...
```

- **`id` обязателен** — у `Button` нет дефолта (в отличие от `Url`/`SwitchInlineQuery*`,
  где `id` опционален). Без id кнопка не имела бы `callback_data` и клик нельзя было бы
  смаршрутизировать.
- `on_click` оборачивается в `ensure_event_processor` → `SimpleEventProcessor`
  (`widget_event.py:38`). Можно передать как обычную async-функцию, так и готовый
  `WidgetEventProcessor`.
- `_render_keyboard` (`button.py:47`): `callback_data = self._own_callback_data()`
  (= `widget_id`).
- `_process_own_callback` (`button.py:38`):
  ```python
  await self.on_click.process_event(callback, self, manager)
  return True                                  # клик всегда «потреблён»
  ```

**Сигнатура `on_click`:** `async def handler(callback: CallbackQuery, button: Button, manager: DialogManager)`.
Три позиционных аргумента, ровно в этом порядке. `button` — экземпляр, по которому
кликнули (полезно при общем хендлере на несколько кнопок: `button.widget_id`).

```python
async def go_clicked(callback: CallbackQuery, button: Button,
                     manager: DialogManager):
    await callback.message.answer("Going on!")

go_btn = Button(Const("Go"), id="go", on_click=go_clicked)
```

`callback.answer()` вызывать **не нужно** — диалог делает это сам (см. §6).

### 4.2. `Url` — `button.py:67`

```python
Url(text: TextWidget, url: TextWidget, id=None, when=None, style=EMPTY_STYLE)
```

Кнопка-ссылка. **Нет `on_click`** — Telegram не присылает callback при клике по URL.
`id` опционален (чаще не нужен). Оба аргумента — `Text`-виджеты:

```python
go_btn = Url(Const("Github"), Const("https://github.com/Tishka17/aiogram_dialog/"))
```

### 4.3. `WebApp` — `button.py:101`

```python
class WebApp(Url): ...   # тот же __init__, что у Url
```

Наследует конструктор `Url` (text, url, id, when, style), но в `_render_keyboard`
оборачивает url в `WebAppInfo(url=...)` и кладёт в `web_app=` вместо `url=`
(`button.py:110`). Открывает Telegram Web App. `url` должен быть **HTTPS**
(требование Telegram).

### 4.4. `LoginURLButton` — `button.py:163`

```python
LoginURLButton(
    text, url,
    forward_text: TextWidget | None = None,
    bot_username: TextWidget | None = None,
    request_write_access: bool | None = None,
    id=None, when=None, style=EMPTY_STYLE,
)
```

Кнопка авторизации через Telegram Login. Собирает `LoginUrl(url, forward_text,
bot_username, request_write_access)` (`button.py:201`). `forward_text`/`bot_username` —
`Text`-виджеты (рендерятся, если заданы), `request_write_access` — обычный `bool`.
URL должен быть HTTPS. Экспортируется как `LoginURLButton`.

```python
login_btn = LoginURLButton(
    text=Const("Login"),
    url=Const("https://example.com/login"),
    request_write_access=True,
)
```

### 4.5. `CopyText` — `copy.py:12` (родственный, тоже Keyboard)

```python
CopyText(text: TextWidget, copy_text: TextWidget, when=None, style=EMPTY_STYLE)
```

Кнопка «скопировать в буфер» (Telegram `CopyTextButton`). **`id` отсутствует** в
сигнатуре вовсе — копирование не порождает callback. Внутренние поля `_text`/`_copy_text`.

```python
copy_btn = CopyText(text=Const("Copy name"), copy_text=Const("Tishka17"))
```

### 4.6. Семейство `SwitchInlineQuery*`

Все три — кнопки переключения в inline-режим. `id`/`when`/`style` опциональны,
`on_click` отсутствует (нет callback).

| Класс | Строка | Аргумент запроса | Кладёт в `InlineKeyboardButton` |
|---|---|---|---|
| `SwitchInlineQuery` | `button.py:126` | `switch_inline_query: TextWidget` | `switch_inline_query=` |
| `SwitchInlineQueryCurrentChat` | `button.py:220` | `switch_inline_query_current_chat: TextWidget` | `switch_inline_query_current_chat=` |
| `SwitchInlineQueryChosenChatButton` | `button.py:261` | `query: TextWidget` + 4 флага | `switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(...)` |

**`SwitchInlineQuery`** — открывает выбор чата, вставляет `@bot query`:

```python
SwitchInlineQuery(Const("Some search"), Const("order"))   # text, query
```

**`SwitchInlineQueryCurrentChat`** — вставляет `@bot query` в текущий чат:

```python
SwitchInlineQueryCurrentChat(
    text=Const("Send inline query in the current chat"),
    switch_inline_query_current_chat=Const("inline query in the current chat"),
)
```

**`SwitchInlineQueryChosenChatButton`** — выбор чата с фильтрами по типу
(`button.py:261`). Доп. флаги `allow_user_chats`, `allow_bot_chats`,
`allow_group_chats`, `allow_channel_chats` (`bool | None`), собираются в
`SwitchInlineQueryChosenChat`:

```python
SwitchInlineQueryChosenChatButton(
    text=Const("Send inline query in the chosen chat"),
    query=Const("inline query in the chosen chat"),
    allow_user_chats=True,
    allow_group_chats=True,
    allow_channel_chats=False,
)
```

Имена классов в `__init__.py` экспортируются с суффиксом `Button` у двух из трёх:
`SwitchInlineQuery`, `SwitchInlineQueryCurrentChat`, **`SwitchInlineQueryChosenChatButton`**.

---

## 5. Контейнеры раскладки (`group.py`)

### 5.1. `Group` — `group.py:12`

```python
Group(*buttons: Keyboard, id=None, width: int | None = None, when=None)
```

Объединяет несколько клавиатурных виджетов. Логика `_render_keyboard`
(`group.py:34`):

```python
kbd = []
for b in self.buttons:
    b_kbd = await b.render_keyboard(data, manager)   # RawKeyboard каждого ребёнка
    if self.width is None:
        kbd += b_kbd                                 # стопка: строки добавляются как есть
    else:
        if not kbd:
            kbd.append([])
        kbd[0].extend(chain.from_iterable(b_kbd))    # все кнопки сплющиваются в одну ленту
if self.width and kbd:
    kbd = self._wrap_kbd(kbd[0])                     # лента → строки по width
return kbd
```

Два режима:

- **`width=None` (по умолчанию) — режим «стопки».** Каждый ребёнок отдаёт свою матрицу
  строк, они склеиваются вертикально, **иерархия сохраняется**. Если ребёнок —
  `Row` из 3 кнопок, эта строка из 3 кнопок ляжет целиком. См. `example.py`:
  `Group(Row(...), Button(...))` → строка из двух кнопок, ниже одиночная.
- **`width=N` — режим «перепаковки».** Все кнопки **всех** детей сплющиваются
  (`chain.from_iterable`) в один линейный поток и режутся по `N` штук в строку
  (`_wrap_kbd`, `group.py:52`). **Вложенная иерархия детей игнорируется** — это
  важный краевой случай: `Group(Row(a, b), c, width=2)` даст `[[a, b], [c]]` по чистому
  потоку `a, b, c`, а не по строкам Row.

`_wrap_kbd` (`group.py:52`): простое нарезание `row.append(b); if len(row) >= width: flush`.
Остаток (`if row`) выливается последней неполной строкой. См. `test_group.py:45`:
5 кнопок, `width=3` → `[[1,2,3],[4,5]]`.

`find` (`group.py:24`): сначала проверяет себя (по `id`), затем рекурсивно опрашивает
детей — так `dialog_manager.find("inner_id")` достаёт вложенную кнопку.

`_process_other_callback` (`group.py:67`): пробрасывает клик всем детям по очереди,
возвращает `True` на первом обработавшем. Сам `Group`/`Row`/`Column` собственного
`callback_data` не имеет (если без `id`) — это чистый layout.

### 5.2. `Row` — `group.py:79`

```python
class Row(Group):
    def __init__(self, *buttons, id=None, when=None):
        super().__init__(*buttons, id=id, width=9999, when=when)
        #                                  ^^^^ "telegram does not allow even 100 columns"
```

Сахар над `Group(width=9999)` — все кнопки в **одну строку**. `width=9999` —
сознательно «бесконечная» ширина (Telegram всё равно лимитирует число столбцов).
Игнорирует вложенную иерархию (как любой `Group` с `width`). См. `test_row.py`:
3 кнопки → одна строка из 3.

### 5.3. `Column` — `group.py:91`

```python
class Column(Group):
    def __init__(self, *buttons, id=None, when=None):
        super().__init__(*buttons, id=id, when=when, width=1)   # по одной в строке
```

Сахар над `Group(width=1)` — каждая кнопка в **отдельной строке**. См. `test_column.py`:
3 кнопки → 3 строки по 1. NB: `Column` ≡ `Group(width=1)`, но **не** ≡ `Group(width=None)`:
у дефолтного `Group` ребёнок-`Row` сохранил бы свою многокнопочную строку, а `Column`
её расплющит в столбец.

### 5.4. Сводка раскладки

| Виджет | `width` | Иерархия детей | Результат |
|---|---|---|---|
| `Group()` | `None` | сохраняется | вертикальная стопка матриц |
| `Group(width=N)` | `N` | **сплющивается** | поток кнопок по N в строке |
| `Row()` | `9999` | сплющивается | всё в одну строку |
| `Column()` | `1` | сплющивается | всё в столбец по одной |

---

## 6. Авто-answer callback (почему не нужен `callback.answer()`)

После `window.process_callback` диалог сам зовёт `dialog_manager.answer_callback()`
(`dialog.py:158` → `manager.py:219`). Поэтому в `on_click` вызывать
`callback.answer()` **не следует** (это явно сказано в `docs/.../button/index.rst:11`).
Если очень нужен `show_alert`/текст всплывашки — это отдельный механизм; обычный
«погасить часики» делается автоматически.

---

## 7. `callback_data`: формат, лимит 64 байта, коллизии

### 7.1. Что реально летит в Telegram

Финальный `callback_data` собирается в два слоя:

1. Виджет: `widget_id` (одиночная кнопка) или `widget_id:item` (составной виджет).
2. Фабрика `InlineKeyboardFactory` → `add_intent_id` (`utils.py:211`):
   ```python
   intent_callback_data(intent_id, callback_data) = f"{intent_id}\x1D{callback_data}"
   ```
   Разделитель `CB_SEP = "\x1D"` (`utils.py:28`). На входящем клике
   `remove_intent_id` (`utils.py:220`) делит по `\x1D` и срезает префикс.

Итог в проводе: `"<intent_id>\x1D<widget_id>[:<item>]"`.

### 7.2. Бюджет 64 байта

Telegram ограничивает `callback_data` **64 байтами (UTF-8)**. Из них «съедают»:
- `intent_id` — генерируемый идентификатор стека/контекста (несколько символов);
- `\x1D` — 1 байт;
- `widget_id` (+ при составных виджетах `:` и `item`).

То есть на ваш `widget_id` и `item` приходится **меньше 64 байт**. **В библиотеке нет
явной валидации длины** (в `InlineKeyboardFactory` стоит `# TODO validate buttons`,
`inline_keyboard.py:16`) — превышение всплывёт как ошибка Telegram API при отправке
сообщения, а не на этапе сборки. Держите `id` короткими, особенно для `Select`/`Radio`,
где к `widget_id` добавляется `:item`.

### 7.3. Уникальность id и коллизии

- `process_callback` матчит по **точному** `widget_id` или по префиксу `widget_id:`.
  Два `Button` с одинаковым `id` в одном окне дадут одинаковый `callback_data` →
  клик уйдёт первому совпавшему по обходу, второй недостижим. **id обязан быть
  уникален в пределах окна.**
- Опасная коллизия префиксов: если есть `Button(id="item")` и рядом составной виджет
  с `id="item"` (даёт `item:42`) — `callback_data="item"` уйдёт в own-ветку, а
  `item:42` в item-ветку; но если завести `Button(id="item")` и `Button(id="item")` в
  разных подгруппах — конфликт. Также избегайте id, являющихся префиксом другого id с
  двоеточием семантикой (на практике двоеточие в id запрещено `ID_PATTERN`, что снижает
  риск, но логических коллизий это не отменяет).

---

## 8. Стилизация (`style`) — общая для всех листовых кнопок

Все листовые кнопки принимают `style: StyleWidget = EMPTY_STYLE`. `StyleWidget`
(`api/internal/widgets.py:51`) рендерит:
- `render_style(data, manager) -> ButtonStyle | None` — стиль кнопки (aiogram `ButtonStyle`);
- `render_emoji(data, manager) -> str | None` → `icon_custom_emoji_id`.

`EMPTY_STYLE = Style(style=None, emoji_id=None, when=None)`
(`widgets/style/base.py:149`) — оба `None`, кнопка без стилей. Поля `style=` и
`icon_custom_emoji_id=` передаются в `InlineKeyboardButton` напрямую. Это
относительно новая возможность (зависит от поддержки `ButtonStyle` в aiogram;
при отсутствии импорта `ButtonStyle` алиасится в `str`, `widgets.py:19`).

---

## 9. Связи с остальной библиотекой

- **Window** (`window.py`): держит единственный корневой `keyboard`, зовёт
  `render_keyboard`/`process_callback`. Несколько виджетов окна оборачиваются в
  `Group`/`Column`/`Row`.
- **MarkupFactory**: `InlineKeyboardFactory` (default) → `InlineKeyboardMarkup`;
  существуют `ReplyKeyboardFactory`/`ForceReplyFactory` (для reply-кнопок
  `RawKeyboard` конвертируется `transform_to_reply_keyboard`, `utils.py:127` — кодирует
  `callback_data` в невидимые юникод-символы внутри текста).
- **Text-виджеты** (зона текста): `text`/`url`/`query` — это `TextWidget`
  (`Const`, `Format`, `Multi`, ...). Их `render_text(data, manager)` получает `data`
  окна, поэтому подписи и URL динамические.
- **on_click / WidgetEventProcessor** (`widget_event.py`): общий механизм событий;
  `Button.on_click` — частный случай. `ensure_event_processor` приводит callable к
  `SimpleEventProcessor`.
- **Производные виджеты**: `Select`/`Radio`/`Multiselect`/`Toggle`, пейджеры
  (`NextPage`/`PrevPage`/...), `Checkbox`, `Counter`, навигация
  (`Start`/`SwitchTo`/`Back`/`Next`/`Cancel`), `Calendar`, `ScrollingGroup`,
  `ListGroup` — все построены на `Keyboard` и `_item_callback_data`/контейнерах из этой
  зоны.

---

## 10. Подводные камни и чек-лист для продакшн-шаблона

1. **Лимит callback_data 64 байта без явной проверки.** `intent_id + "\x1D" + id[:item]`
   должно укладываться в 64 байта UTF-8; иначе — ошибка Telegram API при показе окна
   (не при сборке). Короткие латинские `id`.
2. **`id` валидируется регуляркой `^[a-zA-Z0-9_.]+$` в конструкторе.** Дефис, пробел,
   двоеточие, кириллица → `InvalidWidgetIdError` уже при импорте модуля. У `Button`
   `id` обязателен; у `Url`/`SwitchInlineQuery*`/`CopyText` — опционален/отсутствует.
3. **`id` обязан быть уникален в окне.** Дубли дают одинаковый `callback_data` →
   часть кнопок «мёртвая». Особенно следите за коллизиями own-id и `item`-префиксов
   составных виджетов.
4. **Сигнатура `on_click` фиксирована и позиционна:**
   `async def f(callback, button, manager)`. Только async. Не вызывайте
   `callback.answer()` внутри — диалог делает это сам.
5. **`Group(width=N)`, `Row`, `Column` РАСПЛЮЩИВАЮТ вложенную иерархию.** Только
   `Group(width=None)` сохраняет строки детей. Если внутри `Row`/`Column`/`Group(width=N)`
   положить `Row`, его собственная строковая раскладка будет потеряна.
6. **Скрытие через `when` полностью убирает виджет** (`[]`), а не делает кнопку
   неактивной. Для условной видимости целых блоков заворачивайте их в `Group(when=...)`.
7. При собственных виджетах переопределяйте **`_render_keyboard`**, а не
   `render_keyboard` — иначе потеряете обработку `when` и note об ошибках.
8. `Url`/`WebApp`/`LoginURLButton` требуют **HTTPS** url (требование Telegram), callback
   не приходит — `on_click` для них не предусмотрен.
