---
zone: 16
title: "Ввод от пользователя: MessageInput, TextInput, комбинированный ввод, фильтры и валидация"
source_repo: /tmp/aiogram_dialog
source_rev: "develop 08abdf0 (2026-05-02)"
aiogram: ">=3.14.0"
status: reference
files:
  - src/aiogram_dialog/widgets/input/base.py
  - src/aiogram_dialog/widgets/input/text.py
  - src/aiogram_dialog/widgets/input/combined.py
  - src/aiogram_dialog/widgets/input/__init__.py
  - docs/widgets/input/index.rst
  - docs/widgets/input/message_input/{index.rst,example.py}
  - docs/widgets/input/text_input/{index.rst,example.py}
related_src:
  - src/aiogram_dialog/widgets/utils.py
  - src/aiogram_dialog/window.py
  - src/aiogram_dialog/dialog.py
  - src/aiogram_dialog/context/intent_middleware.py
  - src/aiogram_dialog/widgets/widget_event.py
  - src/aiogram_dialog/widgets/common/action.py
  - src/aiogram_dialog/widgets/common/managed.py
  - src/aiogram_dialog/api/internal/widgets.py
  - src/aiogram_dialog/api/entities/context.py
---

# Зона 16 — Ввод от пользователя (Input widgets)

Группа виджетов, которые перехватывают **входящее сообщение** (`Message`), а не нажатие
inline-кнопки. Сюда входят `MessageInput`, `TextInput`, `CombinedInput` и базовый `BaseInput`.
Все они живут в `src/aiogram_dialog/widgets/input/` и экспортируются из
`aiogram_dialog.widgets.input` (`__init__.py:1-12`).

```python
from aiogram_dialog.widgets.input import (
    BaseInput, MessageInput, TextInput, ManagedTextInput,
    CombinedInput, MessageHandlerFunc,
)
```

> ВАЖНО: в этой ревизии (develop 08abdf0) **нет** `TextUnchangedFilter` и type-factory вроде
> `int_factory`/`float_factory`. `grep -rin "unchanged"` по всему репозиторию ничего не находит.
> Type-factory — это обычный `Callable[[str], T]`; по умолчанию `str`. Подробнее — секция
> «type_factory» и «Подводные камни».

---

## 1. Общая картина: как input встроен в окно

Виджеты-ввода НЕ рисуются на экране (нет inline-разметки). Они срабатывают, когда пользователь
шлёт **обычное сообщение в чат** (или reply — см. подводные камни про стек). Поток обработки:

1. Апдейт `message` проходит через `IntentMiddlewareFactory.process_message`
   (`context/intent_middleware.py:298`): подгружается контекст (стек/intent), кладётся в
   `middleware_data`.
2. Хэндлер диалога `Dialog._message_handler` (`dialog.py:127`) берёт текущее окно и вызывает
   `window.process_message(...)`.
3. `Window.process_message` (`window.py:121`) делегирует **единственному** input-слоту окна
   `self.on_message` (если он есть).
4. `on_message.process_message(...)` возвращает `bool`: «обработал/не обработал».
5. По итогам `Dialog._need_refresh` (`dialog.py:160`) решает, перерисовать ли окно
   (`manager.show()`).

Ключевой нюанс: **в окне ровно один input-слот** (`self.on_message`), а не список. Если в
`Window(...)` передать несколько input-виджетов/коллбэков, они автоматически собираются в один
`CombinedInput` (см. §5 и `widgets/utils.py:97-135`).

### Иерархия классов

```
Actionable (widgets/common/action.py)      InputWidget (api/internal/widgets.py:116, Protocol)
        \                                  /
         BaseInput (input/base.py:26)  ── обязывает реализовать async process_message(...) -> bool
        /            |            \
MessageInput   CombinedInput    TextInput[T]
(base.py:35)   (combined.py:14) (text.py:53, Generic[T])
                                      |
                                ManagedTextInput[T] (text.py:107) — обёртка для manager.find()
```

`BaseInput` наследует:
- `Actionable` (`common/action.py:11`) → даёт `widget_id`, `find()`, `get_widget_data()`,
  `set_widget_data()`, валидацию id по `ID_PATTERN = ^[a-zA-Z0-9_.]+$`.
- `InputWidget` (Protocol, `api/internal/widgets.py:116`) → контракт `process_message`.

```python
# input/base.py:26-32
class BaseInput(Actionable, InputWidget):
    @abstractmethod
    async def process_message(
        self, message: Message, dialog: DialogProtocol, manager: DialogManager,
    ) -> bool:
        raise NotImplementedError
```

`process_message` возвращает `True`, если виджет «принял» сообщение (и его не нужно
пропускать дальше), `False` — если отказался (фильтр/тип не подошёл). Возврат влияет на
перерисовку окна.

---

## 2. MessageInput

`src/aiogram_dialog/widgets/input/base.py:35-68`

Перехватывает сообщение и зовёт пользовательскую функцию. Сам **ничего не сохраняет** в контекст
— вся логика в коллбэке.

### Сигнатура

```python
MessageInput(
    func: MessageHandlerFunc | WidgetEventProcessor | None,
    content_types: Sequence[str] | str = ContentType.ANY,
    filter: Callable[..., Any] | None = None,
    id: str | None = None,
)
```

Тип коллбэка (`base.py:20-23`):

```python
MessageHandlerFunc = Callable[[Message, "MessageInput", DialogManager], Awaitable]
```

То есть сигнатура `func`:

```python
async def handler(
    message: Message,            # входящее сообщение
    widget: MessageInput,        # сам виджет (в примерах часто message_input/widget)
    manager: DialogManager,
) -> Any: ...
```

| Параметр | Назначение | По умолчанию |
|---|---|---|
| `func` | коллбэк-обработчик; оборачивается `ensure_event_processor` (`base.py:44`). Может быть `None` (виджет просто «съедает» сообщение нужного типа). | — |
| `content_types` | какие типы сообщений ловить. Строка или последовательность строк/`ContentType`. | `ContentType.ANY` (всё) |
| `filter` | дополнительный aiogram-фильтр (`F[...]`, magic-filter, callable). | `None` |
| `id` | id виджета (не обязателен для MessageInput). | `None` |

### Как строятся фильтры (`base.py:46-54`)

```python
filters = []
if isinstance(content_types, str):
    if content_types != ContentType.ANY:
        filters.append(FilterObject(F.content_type == content_types))
elif ContentType.ANY not in content_types:
    filters.append(FilterObject(F.content_type.in_(content_types)))
if filter is not None:
    filters.append(FilterObject(filter))
self.filters = filters
```

- `ContentType.ANY` (значение по умолчанию) **отключает** фильтр по типу — список `filters`
  пустой, ловит ВСЁ.
- Если передан один тип строкой → `F.content_type == content_types`.
- Если передан список и в нём нет `ANY` → `F.content_type.in_(content_types)`.
- Если в списке есть `ContentType.ANY` → фильтр по типу не добавляется (ловит всё).
- `filter` добавляется отдельным `FilterObject` поверх типа.

### Обработка (`base.py:56-68`)

```python
async def process_message(self, message, dialog, manager) -> bool:
    for handler_filter in self.filters:
        if not await handler_filter.call(manager.event, **manager.middleware_data):
            return False                       # фильтр не прошёл → отказ
    await self.func.process_event(message, self, manager)
    return True                                # приняли
```

- Фильтры вызываются на `manager.event` (текущее событие) + `middleware_data` — поэтому в
  кастомном `filter` можно завязываться на DI-зависимости aiogram.
- Если хотя бы один фильтр вернул falsy → `return False` (сообщение не принято).
- Иначе зовётся `func` и возвращается `True` — даже если `func is None`
  (`SimpleEventProcessor` с `callback=None` просто ничего не делает, `widget_event.py:34`).

### Возврат и эффекты
- Возвращает `True`/`False` (принял/нет).
- Эффекты — целиком внутри `func`: запись в `manager.dialog_data`, `manager.next()/done()`,
  ответ пользователю и т.п. Виджет сам не пишет в `widget_data`.

### Пример (документация, `docs/.../message_input/example.py`)

```python
async def document_handler(message: Message, message_input: MessageInput, manager: DialogManager):
    manager.dialog_data["document"] = message.document
    await message.answer("Your document has been verified!")
    await manager.done()

Window(
    Const("Submit your document for verification:"),
    MessageInput(document_handler, content_types=[ContentType.DOCUMENT]),
    state=Main.document,
)
```

### Пример с медиа-группой (`example/input_media_group.py:31-39, 89`)

```python
async def on_input_photo(message, widget, dialog_manager):
    dialog_manager.dialog_data.setdefault("photos", []).append(
        (message.photo[-1].file_id, message.photo[-1].file_unique_id),
    )

MessageInput(content_types=[ContentType.PHOTO], func=on_input_photo)
```

Для фото берут `message.photo[-1]` (наибольшее разрешение). Для документа — `message.document`.
Для медиа-групп (альбомов) каждое фото приходит **отдельным апдейтом**: aiogram-dialog НЕ
агрегирует альбом сам — `on_input_photo` вызовется по разу на каждое фото (если стоит aiogram
album-middleware, поведение меняется).

---

## 3. TextInput[T]

`src/aiogram_dialog/widgets/input/text.py:53-104`

В отличие от `MessageInput`, **сам валидирует и сохраняет** текст в контекст. Дженерик по типу
результата `T`.

### Сигнатура

```python
TextInput(
    id: str,                                              # ОБЯЗАТЕЛЕН
    type_factory: TypeFactory[T] = str,                  # Callable[[str], T]
    on_success: OnSuccess[T] | WidgetEventProcessor | None = None,
    on_error: OnError | WidgetEventProcessor | None = None,
    filter: Callable[..., Any] | None = None,
)
```

| Параметр | Назначение | По умолчанию |
|---|---|---|
| `id` | id виджета — под ним хранится текст в `widget_data`; нужен для `manager.find(id)`. | **обязателен** |
| `type_factory` | парсер/валидатор `str -> T`. Бросок `ValueError` → `on_error`. | `str` |
| `on_success` | коллбэк успеха, получает `value: T`. | `None` |
| `on_error` | коллбэк ошибки, получает `error: ValueError`. | `None` |
| `filter` | aiogram-фильтр поверх (после проверки `content_type == TEXT`). | `None` |

`type_factory` (`text.py:24`): `TypeFactory = Callable[[str], T]`.

### Протоколы коллбэков (`text.py:27-50`)

```python
class OnSuccess(Protocol[T]):
    async def __call__(self, message, widget, dialog_manager, data: T, /) -> Any: ...

class OnError(Protocol[T]):
    async def __call__(self, message, widget, dialog_manager, error: ValueError, /) -> Any: ...
```

Конкретные сигнатуры (позиционные, `/`):

```python
async def on_success(message: Message, widget: ManagedTextInput[T], manager: DialogManager, value: T): ...
async def on_error(message: Message, widget: ManagedTextInput[T], manager: DialogManager, error: ValueError): ...
```

`widget` здесь — `ManagedTextInput` (обёртка), а не сам `TextInput` (`text.py:87, 92`).

### Обработка (`text.py:71-95`)

```python
async def process_message(self, message, dialog, manager) -> bool:
    if message.content_type != ContentType.TEXT:
        return False                                  # 1. только текст
    if self.filter and not await self.filter.call(
            manager.event, **manager.middleware_data):
        return False                                  # 2. кастомный фильтр
    try:
        value = self.type_factory(message.text)       # 3. парсинг
    except ValueError as err:
        await self.on_error.process_event(message, self.managed(manager), manager, err)
    else:
        self.set_widget_data(manager, message.text)   # 4. сохраняем ОРИГИНАЛЬНЫЙ текст
        await self.on_success.process_event(message, self.managed(manager), manager, value)
    return True                                       # принято в любом случае (TEXT прошёл)
```

Ключевые детали:
1. **Не текст → `False`** сразу (фото/документ TextInput не примет, см. §5 про CombinedInput).
2. Только `ValueError` ловится в `on_error`. Любое другое исключение (`TypeError`,
   `KeyError`, `ArithmeticError`, `Decimal` `InvalidOperation` и т.п.) **пробрасывается** и
   улетит в `errors`-роутер aiogram. Делайте `raise ValueError(...)` в кастомных парсерах.
3. В `widget_data` сохраняется **исходная строка** `message.text`, а НЕ результат `value`.
   `get_value()` парсит её заново через `type_factory` при каждом вызове.
4. Метод возвращает `True`, как только сообщение текстовое — даже при ошибке валидации. Это
   значит, что окно после ошибки перерисуется (`processed=True` → `_need_refresh`).

### get_value / хранение

```python
# text.py:97-101
def get_value(self, manager) -> T | None:
    data = self.get_widget_data(manager, None)   # читает widget_data[widget_id]
    if data is None:
        return None
    return self.type_factory(data)               # ПЕРЕ-парсит исходную строку
```

- Данные лежат в `manager.current_context().widget_data[widget_id]`
  (`common/action.py:23-40`). Это **per-context** (per стек+intent) и **сериализуется в
  storage** вместе с `Context` (`api/entities/context.py:18`), поэтому переживают рестарт бота.
- `get_value()` возвращает `None`, пока пользователь ничего не ввёл.
- Каждый `get_value()` заново зовёт `type_factory(stored_text)` — для `int`/`float` это норм, но
  для дорогих парсеров стоит закешировать результат самому.

`ManagedTextInput` (`text.py:107-110`) — то, что возвращает `manager.find(id)`:

```python
class ManagedTextInput(ManagedWidget[TextInput[T]], Generic[T]):
    def get_value(self) -> T | None:
        """Get last input data stored by widget."""
        return self.widget.get_value(self.manager)
```

`ManagedWidget` (`common/managed.py`) хранит `(widget, manager)` и проксирует атрибуты через
`__getattr__`. Поэтому через `manager.find("age").get_value()` (без аргументов) вы получаете
типизированное значение. `manager.find()` (`manager/manager.py:538-542`) ищет виджет в дереве
окна (`window.find` → `Window.find`, `window.py:182`) и зовёт `.managed(self)`.

> Нет публичного `set_value()`/`clear()` у `ManagedTextInput`. Чтобы очистить или подставить
> значение вручную — пишите напрямую: `manager.current_context().widget_data.pop("id", None)`
> или `manager.find("id").set_widget_data(manager, text)` (метод унаследован от `Actionable`,
> но принимает **исходную строку**, а не `T`).

### Type-factory: рецепты

```python
TextInput(id="age", type_factory=int, on_error=age_error, on_success=Next())      # int
TextInput(id="price", type_factory=float, on_success=Next())                       # float
TextInput(id="name")                                                               # str (default)

# Кастомный парсер с валидацией диапазона — БРОСАЙ ValueError:
def positive_int(text: str) -> int:
    v = int(text)            # int() уже кидает ValueError на мусоре
    if v <= 0:
        raise ValueError("must be positive")
    return v

TextInput(id="qty", type_factory=positive_int, on_error=err, on_success=ok)
```

`int("12.5")` → `ValueError` → попадёт в `on_error`. `float("1,5")` (запятая) → `ValueError`.
`Decimal("x")` бросает `decimal.InvalidOperation` (подкласс `ArithmeticError`, **НЕ** `ValueError`)
— оберните в свой парсер с `raise ValueError`.

### Пример (документация, `docs/.../text_input/example.py`)

```python
async def error(message, dialog_, manager, error_: ValueError):
    await message.answer("Age must be a number!")

async def getter(dialog_manager, **kwargs):
    return {
        "age": dialog_manager.find("age").get_value(),
        "country": dialog_manager.find("country").get_value(),
    }

Window(
    Const("Enter your age:"),
    TextInput(id="age", on_error=error, on_success=Next(), type_factory=int),
    state=SG.age,
),
```

### Пример wizard (`example/wizard.py:57-72`)

```python
TextInput(id="title", on_success=next_or_end)        # str, on_success — кастомный переход
...
"title": dialog_manager.find("title").get_value(),   # чтение в getter финального окна
```

---

## 4. Коллбэки: ensure_event_processor / WidgetEventProcessor

`src/aiogram_dialog/widgets/widget_event.py`

И `MessageInput.func`, и `TextInput.on_success/on_error` пропускаются через
`ensure_event_processor` (`widget_event.py:38-44`):

- Если уже `WidgetEventProcessor` (например `Next()`, `SwitchTo()`, `Start()` из `kbd`) — берётся
  как есть.
- Иначе оборачивается в `SimpleEventProcessor(callback)` (`widget_event.py:22-35`), который при
  `process_event` зовёт `callback(event, source, manager, *args, **kwargs)`.

Поэтому `on_success=Next()` работает: `Next` — это `WidgetEventProcessor`, и его `process_event`
выполняет переход на следующее окно. Дополнительные позиционные аргументы (`value`/`error`)
передаются в `*args` — kbd-обработчики их игнорируют, а ваши функции принимают.

`None`-коллбэк безопасен: `SimpleEventProcessor.process_event` проверяет `if self.callback`
(`widget_event.py:34`) и ничего не делает.

---

## 5. CombinedInput и сосуществование нескольких input в окне

`src/aiogram_dialog/widgets/input/combined.py`

### Как несколько input попадают в одно окно

В окне физически **один** input-слот. Сборка происходит в `ensure_widgets`
(`widgets/utils.py:97-135`): все виджеты-кандидаты (что есть `BaseInput` ИЛИ `Callable`)
складываются в список `inputs`, затем `ensure_input(inputs)` (`utils.py:54-72`):

```python
def ensure_input(widget) -> BaseInput | None:
    if isinstance(widget, BaseInput):
        return widget
    elif isinstance(widget, Sequence):
        if len(widget) == 0:   return None
        elif len(widget) == 1: return widget[0]
        else:                  return CombinedInput(*widget)   # >1 input → объединяем
    else:
        return MessageInput(widget)                            # «голый» callable → MessageInput
```

- 0 input → `None` (окно не обрабатывает сообщения).
- 1 input → он сам.
- ≥2 input → оборачиваются в `CombinedInput`.
- Голый `Callable` в `Window(...)` тоже допустим — превращается в `MessageInput(callback)`
  с `content_types=ANY` (см. `WidgetSrc`, `utils.py:17-25` и условие `isinstance(w, Callable)`
  в `utils.py:117`).

### CombinedInput

```python
CombinedInput(*inputs: BaseInput, filter: Callable[..., Any] | None = None)
```

Обработка (`combined.py:26-40`):

```python
async def process_message(self, message, dialog, manager) -> bool:
    for handler_filter in self.filters:                       # общий filter сначала
        if not await handler_filter.call(manager.event, **manager.middleware_data):
            return False
    for input_widget in self.inputs:                          # затем по порядку
        if await input_widget.process_message(message, dialog, manager):
            return True                                       # ПЕРВЫЙ принявший выигрывает
    return False
```

Правила:
- **Порядок = порядок объявления** виджетов в `Window(...)`.
- Срабатывает **первый**, чей `process_message` вернул `True`; остальные не вызываются.
- Общий `filter` у `CombinedInput` — это «гейт»: если он не прошёл, не вызовется ни один
  вложенный input.
- `CombinedInput` создаётся **без id** (`super().__init__()` без аргументов, `combined.py:21`),
  поэтому через `manager.find()` ищите вложенные `TextInput` по их собственным id, а не сам
  combined.

### Паттерн «typed-input + fallback» (`example/simple.py:100-102`)

```python
MessageInput(name_handler, content_types=[ContentType.TEXT]),  # 1) ловит только текст
MessageInput(other_type_handler),                              # 2) ловит ВСЁ остальное (ANY)
```

Первый принимает только текст. Если пришло не текст — он вернёт `False`, и сработает второй
(`content_types=ANY`), который отвечает «Text is expected». Это идиоматичный способ давать
обратную связь на неправильный тип. Тот же приём работает с `TextInput` первым (он отказывается
от не-текста, `text.py:77-78`) и `MessageInput`-fallback вторым.

> Если поставить catch-all `MessageInput(...)` (ANY) **первым**, он съест всё, и последующие
> input-виджеты (включая `TextInput`) никогда не получат сообщение. Catch-all всегда последним.

---

## 6. Фильтры и валидация — сводка

| Механизм | Где | Что фильтрует |
|---|---|---|
| `content_types` (MessageInput) | `base.py:46-51` | тип сообщения через `F.content_type` |
| `content_type == TEXT` (TextInput) | `text.py:77-78` | жёстко: только текст |
| `filter=` (любой input) | `base.py:52-53`, `text.py:63-66`, `combined.py:22-24` | произвольный aiogram-фильтр |
| `type_factory` ValueError (TextInput) | `text.py:83-88` | валидация значения → `on_error` |

Фильтры вызываются как `FilterObject(...).call(manager.event, **manager.middleware_data)` —
доступны те же DI-данные, что и обычным aiogram-хэндлерам (бот, fsm-данные, кастомные
middleware-инъекции).

---

## 7. Подводные камни и краевые случаи

| # | Проблема | Детали / решение |
|---|---|---|
| 1 | **Ввод «не работает» в неосновном стеке без reply** | Обычное сообщение грузит контекст ТОЛЬКО из `DEFAULT_STACK_ID` (`intent_middleware.py:339-340`, `_load_default_context`). Диалог в дочернем/именованном стеке получит ввод, лишь если юзер **ответит (reply)** на сообщение бота с inline-кнопками — тогда intent берётся из reply (`_intent_id_from_reply`, `intent_middleware.py:281-296, 332-338`). Без inline-кнопок в окне reply-механизм не сработает (нет `callback_data`). |
| 2 | **Не-`ValueError` пробрасывается** | `TextInput` ловит ТОЛЬКО `ValueError` (`text.py:85`). `Decimal`/`datetime.strptime`/кастом, бросающие `InvalidOperation`/`TypeError` и пр., улетят в errors-роутер. Оборачивайте: `raise ValueError(...)`. |
| 3 | **В `widget_data` лежит строка, не `T`** | Хранится `message.text` (`text.py:91`). `get_value()` каждый раз парсит заново (`text.py:101`). Если `type_factory` недетерминирован/дорог — закешируйте сами. После смены `type_factory` старое сохранённое значение распарсится новым парсером. |
| 4 | **Повторный ввод перезаписывает** | Новый текст в то же окно/виджет затирает `widget_data[id]` (`set_widget_data`, `action.py:40`). Истории нет. `on_success` зовётся каждый раз. |
| 5 | **Нет `set_value()`/`clear()` у Managed** | `ManagedTextInput` даёт только `get_value()`. Очистка: `manager.current_context().widget_data.pop("id", None)`. Ручная установка: `find("id").set_widget_data(manager, "<строка>")` (строка, не `T`). |
| 6 | **Catch-all порядок** | В `CombinedInput`/окне первый принявший (`True`) выигрывает (`combined.py:37-39`). `MessageInput(content_types=ANY)` ставьте последним, иначе он перехватит всё. |
| 7 | **TextInput без id падает** | `id` обязателен (нет дефолта, `text.py:55`). MessageInput — id опционален. id валидируется `^[a-zA-Z0-9_.]+$` (`action.py:8, 13-14`), иначе `InvalidWidgetIdError`. |
| 8 | **Медиа/документы/альбомы** | Для фото — `message.photo[-1]` (макс. размер). Документ — `message.document`. Альбом приходит несколькими апдейтами → коллбэк сработает по разу на каждое медиа (если нет album-middleware). `content_types=[ContentType.PHOTO]` и т.п. для конкретных типов. |
| 9 | **`ContentType.ANY` в списке** | Если в `content_types`-списке есть `ANY`, фильтр по типу не ставится вообще (`base.py:50`) — ловит всё, прочие элементы списка игнорируются. |
| 10 | **`func=None` у MessageInput** | Допустимо: виджет «проглотит» сообщение нужного типа и вернёт `True`, ничего не сделав (`SimpleEventProcessor` с `None`, `widget_event.py:34`). Полезно как «заглушка-поглотитель». |
| 11 | **Окно перерисуется после ввода** | `process_message` обоих принявших виджетов возвращает `True` → `_need_refresh` → `manager.show()` (`dialog.py:138`, `_need_refresh:171-173`). В приватных чатах окно показывается даже при `False` (`dialog.py:174-177`). Если переход уже сделан в коллбэке (контекст сменился) — повторного show не будет (`dialog.py:168-170`). |
| 12 | **`is_preview()` / превью** | В режиме превью (`tools/preview.py`) реальных сообщений нет; коллбэки должны учитывать `manager.is_preview()` и делать переход самостоятельно (см. `simple.py:55-58`). |
| 13 | **`CancelEventProcessing`** | Если коллбэк бросает `CancelEventProcessing` (`api/protocols/dialog.py:14`), `Dialog._message_handler` ставит `processed=False` (`dialog.py:136-137`) — окно не перерисуется по этой причине. Способ «тихо» отменить обработку. |
| 14 | **TextInput не реагирует на не-текст** | Картинка/документ → `TextInput.process_message` вернёт `False` (`text.py:77-78`). Чтобы дать фидбек «нужен текст», добавьте вторым `MessageInput(fallback)` (ANY). |

---

## 8. Связи с остальной библиотекой

- **Window / ensure_widgets** (`window.py:55-61`, `utils.py:97-135`): окно держит один
  `on_message`-слот; множественные input → `CombinedInput`; голый callable → `MessageInput`.
- **Dialog** (`dialog.py:127-178`): маршрутизирует `message` в окно, решает перерисовку.
- **IntentMiddleware** (`intent_middleware.py:298-341`): подгрузка контекста для сообщений;
  reply-механизм для неосновных стеков.
- **kbd-переходы как коллбэки**: `Next()`, `SwitchTo()`, `Start()`, `End()` — это
  `WidgetEventProcessor`, их можно передавать в `on_success`/`func` напрямую.
- **DialogManager.find** (`manager/manager.py:538-542`) + **ManagedWidget**
  (`common/managed.py`): доступ к `ManagedTextInput.get_value()`.
- **Context.widget_data** (`api/entities/context.py:18`): per-context хранилище, сериализуется
  в storage — данные TextInput переживают рестарт и привязаны к конкретному стеку/intent.

---

## 9. Шпаргалка по сигнатурам

```python
# --- MessageInput (base.py:35) ---
MessageInput(func, content_types=ContentType.ANY, filter=None, id=None)
async def func(message: Message, widget: MessageInput, manager: DialogManager): ...

# --- TextInput (text.py:53) ---
TextInput(id, type_factory=str, on_success=None, on_error=None, filter=None)  # Generic[T]
async def on_success(message: Message, widget: ManagedTextInput[T], manager, value: T): ...
async def on_error(message: Message, widget: ManagedTextInput[T], manager, error: ValueError): ...
value: T | None = manager.find(id).get_value()                # ManagedTextInput.get_value()

# --- CombinedInput (combined.py:14) ---
CombinedInput(*inputs: BaseInput, filter=None)                # первый принявший выигрывает

# --- BaseInput / контракт (base.py:26) ---
async def process_message(message, dialog, manager) -> bool   # True = принял, не пропускать дальше
```
