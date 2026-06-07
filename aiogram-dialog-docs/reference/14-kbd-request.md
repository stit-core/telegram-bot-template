---
zone: 14
title: "Request-кнопки reply-клавиатуры: RequestContact, RequestLocation, RequestPoll"
slug: kbd-request
source_repo: aiogram_dialog
source_ref: "develop @ 08abdf0 (2026-05-02)"
aiogram_min: ">=3.14.0"
primary_files:
  - src/aiogram_dialog/widgets/kbd/request.py
  - src/aiogram_dialog/widgets/markup/reply_keyboard.py
  - example/mega/bot_dialogs/reply_buttons.py
  - docs/widgets/keyboard/request_poll/index.rst
widgets:
  - RequestContact
  - RequestLocation
  - RequestPoll
absent_widgets:
  - RequestUser
  - RequestUsers
  - RequestChat
tags: [kbd, reply-keyboard, KeyboardButton, request, markup-factory]
related_zones: [18 (markup-фабрики), 17 (MessageInput), стиль кнопок Style]
---

# Зона 14 — Request-кнопки reply-клавиатуры

## TL;DR (самое главное за 30 секунд)

В библиотеке РЕАЛЬНО есть только **три** Request-виджета — все в одном файле
`src/aiogram_dialog/widgets/kbd/request.py` (106 строк):

| Класс | Строка | Эффект кнопки | Что присылает Telegram в ответ |
|---|---|---|---|
| `RequestContact` | `request.py:11` | `KeyboardButton(request_contact=True)` | обычное `Message` с `message.contact` |
| `RequestLocation` | `request.py:42` | `KeyboardButton(request_location=True)` | обычное `Message` с `message.location` |
| `RequestPoll` | `request.py:73` | `KeyboardButton(request_poll=KeyboardButtonPollType(type=...))` | обычное `Message` с `message.poll` |

> **КРИТИЧНО:** Виджетов **`RequestUser` / `RequestUsers` / `RequestChat`
> (request_user / request_users / request_chat / `user_shared` / `chat_shared`)
> в aiogram_dialog НЕТ.** Я перепроверил поиском по всему `src/`, `example/`,
> `docs/` — единственное совпадение `request_chat` — это несвязанный метод
> `request_chat_join()` в `test_tools/bot_client.py:135`. Если в продакшн-шаблоне
> нужен «выбор пользователя/чата» через нативную кнопку Telegram — это надо
> делать своим виджетом-подклассом `Keyboard` (см. раздел «Как добавить
> RequestUser/RequestChat самому»).

Все три — это `KeyboardButton` (**reply**-клавиатура), а НЕ inline.
Поэтому они работают только под `markup_factory=ReplyKeyboardFactory()`.
Результат приходит обычным сообщением и ловится **отдельно** (через
`MessageInput` / `on_message` окна), а **не** через `on_click` — callback'а у
этих кнопок нет в принципе.

---

## 1. Базовый контракт: что наследуют все три виджета

Все три класса наследуют `Keyboard`
(`src/aiogram_dialog/widgets/kbd/base.py:15`):

```python
class Keyboard(Actionable, Whenable, KeyboardWidget):
```

Цепочка протоколов/миксинов:
- **`Actionable`** — даёт `widget_id` / `find()` / `managed()`. Здесь `id` НЕ
  передаётся (см. ниже), поэтому `widget_id is None`.
- **`Whenable`** — обработка `when` (скрытие виджета по условию/данным).
- **`KeyboardWidget`** (Protocol, `api/internal/widgets.py:81`) — требует
  `render_keyboard()` и `process_callback()`.

Ключевой метод базового класса (`base.py:21-34`):

```python
async def render_keyboard(self, data, manager) -> RawKeyboard:
    if not self.is_(data, manager):   # обработка when
        return []
    return await self._render_keyboard(data, manager)
```

То есть подклассы переопределяют именно `_render_keyboard()` (а не
`render_keyboard()`), чтобы `when` продолжал работать. Все три Request-виджета
так и делают.

`RawKeyboard` (`api/internal/widgets.py:77-78`):
```python
ButtonVariant = InlineKeyboardButton | KeyboardButton
RawKeyboard = list[list[ButtonVariant]]
```
Каждый Request-виджет возвращает «матрицу» `[[KeyboardButton(...)]]` —
ровно одну кнопку, занимающую отдельную строку (вложенность сохраняется до
момента, пока внешний layout-виджет — `Row`/`Column`/`Group` — её не
перекомпонует).

`process_callback()` базового `Keyboard` (`base.py:62-82`) для Request-кнопок
фактически всегда вернёт `False`: у них нет `widget_id` и нет callback_data,
поэтому ни одна ветка не срабатывает. Это и есть причина «нет on_click».

---

## 2. RequestContact

`src/aiogram_dialog/widgets/kbd/request.py:11-39`

### Сигнатура `__init__`
```python
RequestContact(
    text: TextWidget,
    when: str | Callable | None = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

| Параметр | Тип | Назначение |
|---|---|---|
| `text` | `TextWidget` | **позиционный, обязательный.** Текст-виджет надписи кнопки (`Const`, `Format`, `Multi`…). Рендерится `await self.text.render_text(data, manager)`. |
| `when` | `str \| Callable \| None` | условие показа (как у любого виджета). |
| `style` | `StyleWidget` | стиль кнопки (цвет/иконка), по умолчанию `EMPTY_STYLE`. См. §6. |

> Заметь: `id` тут **не принимается вообще** — конструктор зовёт
> `super().__init__(when=when)`, без `id`. Значит `widget_id is None`, и
> `manager.find("...")` такой виджет не найдёт. Это сознательно: управлять
> нечем, состояния у кнопки нет.

### `_render_keyboard` (`request.py:22-39`)
Возвращает:
```python
[[ KeyboardButton(
       text=<rendered>,
       request_contact=True,
       style=<rendered style>,
       icon_custom_emoji_id=<rendered emoji_id>,
   ) ]]
```
Эффект в Telegram: при нажатии клиент предлагает пользователю поделиться
**своим** номером телефона. Ответ приходит как `Message` с заполненным
`message.contact` (`Contact`: `phone_number`, `first_name`, `user_id`, …).

---

## 3. RequestLocation

`src/aiogram_dialog/widgets/kbd/request.py:42-70`

### Сигнатура
```python
RequestLocation(
    text: TextWidget,
    when: str | Callable | None = None,
    style: StyleWidget = EMPTY_STYLE,
)
```
Параметры идентичны `RequestContact`. Единственное отличие в рендере —
`request_location=True` (`request.py:65`).

Эффект: клиент просит поделиться **текущей геопозицией**. Ответ — `Message` с
`message.location` (`Location`: `latitude`, `longitude`, опц. `horizontal_accuracy`).

---

## 4. RequestPoll

`src/aiogram_dialog/widgets/kbd/request.py:73-105`

### Сигнатура
```python
RequestPoll(
    text: TextWidget,
    poll_type: str | None = None,
    when: str | Callable | None = None,
    style: StyleWidget = EMPTY_STYLE,
)
```

| Параметр | Тип | Назначение |
|---|---|---|
| `text` | `TextWidget` | надпись кнопки (обязательный позиционный). |
| `poll_type` | `str \| None` | тип опроса. `None` — любой; `"quiz"` — только викторина; `"regular"` — обычный опрос. Прокидывается в `KeyboardButtonPollType(type=self.poll_type)`. |
| `when` | … | условие показа. |
| `style` | `StyleWidget` | стиль кнопки. |

### `_render_keyboard` (`request.py:86-105`)
```python
request_poll = KeyboardButtonPollType(type=self.poll_type)
... KeyboardButton(text=..., request_poll=request_poll, style=..., icon_custom_emoji_id=...)
```

Эффект: клиент открывает интерфейс **создания опроса** и присылает его боту.
Ответ — `Message` с `message.poll`.

> `poll_type` не валидируется библиотекой — корректность значения целиком на
> совести Telegram. Допустимые значения по Bot API: `"quiz"`, `"regular"`.

### Документация и пример
- `docs/widgets/keyboard/request_poll/index.rst` — единственная доковая
  страница среди трёх Request-виджетов (для `RequestContact`/`RequestLocation`
  отдельных доков НЕТ). Упоминается также в
  `docs/widgets/keyboard/index.rst:32`.
- `docs/widgets/keyboard/request_poll/example.py`:
```python
from aiogram_dialog.widgets.kbd import RequestPoll
from aiogram_dialog.widgets.text import Const

poll_btn = RequestPoll(text=Const("Create Poll"))                 # любой тип
quiz_btn = RequestPoll(text=Const("Create Quiz"), poll_type="quiz")  # викторина
```

---

## 5. Экспорт и импорт

`src/aiogram_dialog/widgets/kbd/__init__.py`:
```python
# строка 84:
from .request import RequestContact, RequestLocation, RequestPoll
# __all__ (строки 34-36): "RequestContact", "RequestLocation", "RequestPoll"
```
Правильный импорт в шаблоне:
```python
from aiogram_dialog.widgets.kbd import RequestContact, RequestLocation, RequestPoll
```

---

## 6. Параметр `style` и `icon_custom_emoji_id` (важно для совместимости aiogram)

Все три виджета прокидывают в `KeyboardButton` два «новых» поля:
- `style` — результат `await self.style.render_style(data, manager)`
  (тип `ButtonStyle | None`, в старых aiogram — просто `str | None`).
- `icon_custom_emoji_id` — результат `await self.style.render_emoji(...)`.

`StyleWidget` — протокол (`api/internal/widgets.py:51-64`); базовая реализация в
`src/aiogram_dialog/widgets/style/base.py`:
- `Style(style=..., emoji_id=..., when=...)` — конкретный стиль кнопки
  (`style/base.py:79`).
- `EMPTY_STYLE = Style(style=None, emoji_id=None, when=None)`
  (`style/base.py:149`) — дефолт; оба рендера вернут `None`.
- `ButtonStyle` импортируется так (`api/internal/widgets.py:19-22`):
  ```python
  try:
      from aiogram.enums import ButtonStyle
  except ImportError:
      ButtonStyle: TypeAlias = str
  ```
  То есть фича опциональна по версии aiogram.

> **Подводный камень совместимости:** `KeyboardButton(style=..., icon_custom_emoji_id=...)`
> — это поля из новых ревизий Telegram Bot API (стилизация кнопок). На старой
> сборке aiogram, где у `KeyboardButton` нет этих полей, pydantic-модель сложит
> их в `model_extra` (aiogram использует `extra="allow"`), и они уйдут в API как
> неизвестные параметры. При `EMPTY_STYLE` оба значения `None`, поэтому риск
> минимален, но если задавать реальный `Style(...)` — проверь, что ваша версия
> aiogram/Telegram это поддерживает.

---

## 7. Как Request-кнопки попадают в reply-клавиатуру (связь с зоной 18)

Цепочка рендера окна (`src/aiogram_dialog/window.py:98-104`):
```python
async def render_kbd(self, data, manager) -> MarkupVariant:
    keyboard = await self.keyboard.render_keyboard(data, manager)   # RawKeyboard
    return await self.markup_factory.render_markup(data, manager, keyboard)
```

**Дефолтная фабрика — inline**, а не reply
(`window.py:38`): `_DEFAULT_MARKUP_FACTORY = InlineKeyboardFactory()`. Поэтому
без явного `markup_factory=ReplyKeyboardFactory(...)` Request-кнопки попадут в
`InlineKeyboardFactory`, и `transform`/рендер пойдут не туда — кнопки не
сработают так, как задумано.

`ReplyKeyboardFactory` (`src/aiogram_dialog/widgets/markup/reply_keyboard.py:14`):
```python
class ReplyKeyboardFactory(MarkupFactory):
    def __init__(
        self,
        resize_keyboard: bool | None = None,
        one_time_keyboard: bool | None = None,
        input_field_placeholder: TextWidget | None = None,  # текст-виджет!
        selective: bool | None = None,
        is_persistent: bool | None = None,
    ): ...

    async def render_markup(self, data, manager, keyboard) -> MarkupVariant:
        ...
        add_intent_id(keyboard, manager.current_context().id)
        return ReplyKeyboardMarkup(
            keyboard=transform_to_reply_keyboard(keyboard),
            resize_keyboard=..., one_time_keyboard=...,
            input_field_placeholder=placeholder, selective=..., is_persistent=...,
        )
```

Что важно для Request-кнопок внутри `transform_to_reply_keyboard`
(`src/aiogram_dialog/utils.py:94-133`):
- `_transform_to_reply_button` (`utils.py:94`): если кнопка УЖЕ `KeyboardButton`
  (а Request-кнопки именно такие), она **возвращается как есть** —
  `request_contact/location/poll`, `style`, `icon_custom_emoji_id` сохраняются.
- Inline-кнопки в той же reply-клавиатуре, наоборот, превращаются в
  `KeyboardButton`, где callback_data зашивается в текст невидимыми
  юникод-символами (`join_reply_callback`, `utils.py:72`). К Request-кнопкам это
  НЕ применяется — у них нет callback_data.
- `add_intent_id` (`utils.py:211-218`) дописывает intent_id **только** к
  `InlineKeyboardButton`. Для `KeyboardButton` (то есть для Request-кнопок) он
  не делает ничего → **intent-id к Request-кнопке не привязывается.** Это прямая
  причина, почему результат Request-кнопки нельзя сматчить с конкретным
  контекстом по reply_markup.

---

## 8. Как ловить результат (главное отличие от inline-кнопок)

Request-кнопки **не дают callback_query**. Ответ Telegram — обычное входящее
сообщение:
- contact → `message.contact`
- location → `message.location`
- poll → `message.poll`

Поэтому в окне нужен **обработчик сообщений**, а не `on_click`:

```python
from aiogram.types import ContentType, Message
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import RequestContact, RequestLocation, Row
from aiogram_dialog.widgets.markup.reply_keyboard import ReplyKeyboardFactory
from aiogram_dialog.widgets.text import Const


async def on_contact(message: Message, widget: MessageInput, manager: DialogManager):
    contact = message.contact
    manager.dialog_data["phone"] = contact.phone_number
    # await manager.next() / switch_to(...) и т.п.


async def on_location(message: Message, widget: MessageInput, manager: DialogManager):
    loc = message.location
    manager.dialog_data["geo"] = (loc.latitude, loc.longitude)


window = Window(
    Const("Поделитесь контактом или геопозицией"),
    Row(
        RequestContact(Const("👤 Контакт")),
        RequestLocation(Const("📍 Локация")),
    ),
    MessageInput(on_contact, content_types=ContentType.CONTACT),
    MessageInput(on_location, content_types=ContentType.LOCATION),
    markup_factory=ReplyKeyboardFactory(resize_keyboard=True),
    state=MySG.main,
)
```

`MessageInput` (`src/aiogram_dialog/widgets/input/base.py:35-68`):
```python
MessageInput(
    func: MessageHandlerFunc | WidgetEventProcessor | None,
    content_types: Sequence[str] | str = ContentType.ANY,
    filter: Callable[..., Any] | None = None,
    id: str | None = None,
)
```
- `content_types` фильтрует по типу контента: `ContentType.CONTACT`,
  `ContentType.LOCATION`, `ContentType.POLL`. Можно передать список.
- Сигнатура handler'а: `(message: Message, widget: MessageInput, manager: DialogManager)`.
- `process_message` сначала прогоняет фильтры, потом зовёт `func`. Возврат
  `True` означает «событие обработано, не пробрасывать дальше».

> Альтернатива `MessageInput` — позиционный коллбэк окна `on_message` через
> `Window(..., on_message=...)` или внешний `@router.message(...)` хэндлер. Но
> при внешнем хэндлере ты теряешь связку с текущим контекстом диалога, если
> сообщение не было reply на сообщение бота с inline-кнопками (см. §9).

---

## 9. Какой контекст диалога загрузится при ответе (default stack!)

`intent_middleware.process_message` (`src/aiogram_dialog/context/intent_middleware.py:298-341`):

1. Сначала пытается вытащить callback из текста сообщения
   (`split_reply_callback(event.text)`, `utils.py:76`). Для contact/location/poll
   `event.text is None` → callback_data нет → ветка `ReplyCallbackQuery`
   пропускается.
2. Потом `_intent_id_from_reply` (`intent_middleware.py:281-296`) — пытается
   взять intent из `reply_to_message.reply_markup.inline_keyboard`. У ответа на
   Request-кнопку обычно **нет** `reply_to_message` с inline-клавиатурой →
   `None`.
3. Итог: вызывается `_load_default_context(...)` →
   контекст берётся из **`DEFAULT_STACK_ID`** (дефолтный стек чата).

**Следствие (важнейшее ограничение):** результат Request-кнопки корректно
доезжает до диалога только если активный диалог живёт в **дефолтном стеке**.
Если диалог запущен в отдельном стеке (`bg().start(..., mode=StackMode.NEW)` /
свой `stack_id`), `MessageInput` этого окна может не получить событие — middleware
загрузит дефолтный контекст, а не твой. То же касается reply-кнопок вообще
(зона 18), но для Request-кнопок это особенно болезненно, потому что нет ни
callback'а, ни закодированного intent'а в тексте, по которым можно было бы
восстановить нужный стек.

---

## 10. Полный рабочий пример из репозитория

`example/mega/bot_dialogs/reply_buttons.py` (целиком):
```python
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import (
    Checkbox, Radio, RequestContact, RequestLocation, Row,
)
from aiogram_dialog.widgets.markup.reply_keyboard import ReplyKeyboardFactory
from aiogram_dialog.widgets.text import Const, Format
from . import states
from .common import MAIN_MENU_BUTTON

reply_kbd_dialog = Dialog(
    Window(
        Const("Reply keyboard with multiple widgets.\n"),
        Row(
            RequestContact(Const("👤 Send contact")),
            RequestLocation(Const("📍 Send location")),
        ),
        Checkbox(checked_text=Const("✓ Checkbox"),
                 unchecked_text=Const(" Checkbox"), id="chk"),
        Radio(checked_text=Format("🔘 {item}"),
              unchecked_text=Format("⚪️ {item}"),
              items=["A", "B", "C"], item_id_getter=lambda x: x, id="radio1"),
        MAIN_MENU_BUTTON,
        markup_factory=ReplyKeyboardFactory(
            input_field_placeholder=Format("{event.from_user.username}"),
            resize_keyboard=True,
        ),
        state=states.ReplyKeyboard.MAIN,
    ),
)
```

Чему учит пример:
- Request-кнопки спокойно соседствуют в reply-клавиатуре с обычными
  виджетами (`Checkbox`, `Radio`, `MAIN_MENU_BUTTON`) — `transform_to_reply_keyboard`
  превратит inline-кнопки этих виджетов в reply-кнопки с зашитым callback'ом, а
  Request-кнопки оставит как есть.
- `input_field_placeholder` принимает **text-виджет** (`Format(...)`), а не строку.
- В самом примере `mega` **нет** `MessageInput` на contact/location — то есть он
  демонстрирует только рендер кнопок, но не обработку результата. В продакшне
  обработчик добавлять обязательно.

---

## 11. Как добавить RequestUser / RequestChat самому (которых нет в либе)

Поскольку штатных виджетов нет, в шаблоне их делают подклассом `Keyboard`,
возвращая `KeyboardButton` с нужным полем aiogram:

```python
from aiogram.types import KeyboardButton, KeyboardButtonRequestUsers
from aiogram_dialog.widgets.kbd.base import Keyboard

class RequestUsers(Keyboard):
    def __init__(self, text, request_id: int, *,
                 user_is_bot=None, user_is_premium=None, max_quantity=None,
                 request_name=None, request_username=None, request_photo=None,
                 when=None):
        super().__init__(when=when)
        self.text = text
        self.req = KeyboardButtonRequestUsers(
            request_id=request_id,
            user_is_bot=user_is_bot, user_is_premium=user_is_premium,
            max_quantity=max_quantity, request_name=request_name,
            request_username=request_username, request_photo=request_photo,
        )

    async def _render_keyboard(self, data, manager):
        return [[KeyboardButton(
            text=await self.text.render_text(data, manager),
            request_users=self.req,
        )]]
```
Ответ ловится `MessageInput(..., content_types=ContentType.USERS_SHARED)` →
`message.users_shared` (для чата — `KeyboardButtonRequestChat`,
`content_types=ContentType.CHAT_SHARED`, `message.chat_shared`).
Параметры (`request_id`, `user_is_bot`, `user_is_premium`, `max_quantity`,
`chat_is_channel`, …) — целиком из aiogram-типов, а не из aiogram_dialog.
`request_id` нужен, чтобы различать несколько таких кнопок в одном сообщении.

---

## 12. Подводные камни и краевые случаи (чек-лист для продакшна)

1. **Только reply-разметка.** Без `markup_factory=ReplyKeyboardFactory()` (или
   совместимой) Request-кнопки не работают: дефолт окна — `InlineKeyboardFactory`
   (`window.py:38`). Telegram запрещает поля `request_*` в inline-кнопках.
2. **Нет on_click / нет callback.** `process_callback` всегда `False`. Результат
   ловится ТОЛЬКО входящим сообщением (`MessageInput`/`on_message`/внешний
   хэндлер по нужному `content_type`).
3. **Нет `widget_id`.** Конструкторы не принимают `id` → `manager.find()` их не
   найдёт; управлять/читать состояние нельзя (его и нет).
4. **Default stack.** Результат корректно доезжает до диалога преимущественно в
   дефолтном стеке (см. §9). В кастомных стеках — поведение хрупкое.
5. **Reply-клавиатура персистентна.** В отличие от inline, reply-клавиатура не
   привязана к конкретному сообщению и остаётся видимой. Управляй
   `one_time_keyboard` / `is_persistent` через `ReplyKeyboardFactory`. При
   переходе к окну без reply-клавиатуры её нужно явно убирать (на стороне
   рендера/`ReplyKeyboardRemove`), иначе старые кнопки «залипнут».
6. **`style` / `icon_custom_emoji_id`** уходят в `KeyboardButton` всегда (при
   `EMPTY_STYLE` — как `None`). На старом aiogram попадут в `model_extra` →
   уйдут как extra-параметры (см. §6). Проверь версию перед использованием
   реального `Style(...)`.
7. **`poll_type` не валидируется** — ошибочное значение отловит только Telegram.
8. **Request-кнопка занимает всю строку** в своём `_render_keyboard`
   (`[[button]]`), реальную раскладку определяет внешний layout-виджет
   (`Row`/`Column`), как в примере `mega`.
9. **`RequestUser/RequestUsers/RequestChat` отсутствуют** — это самая частая
   ловушка ожиданий. Делать вручную (§11).

---

## 13. Связи с остальной библиотекой

- **Зона 18 (markup-фабрики):** `ReplyKeyboardFactory`,
  `transform_to_reply_keyboard`, `add_intent_id`, кодирование callback в тексте —
  именно туда попадают Request-кнопки. Дефолт `InlineKeyboardFactory`.
- **Зона 17 / input:** `MessageInput` (`widgets/input/base.py`) — основной
  способ поймать contact/location/poll.
- **Style:** `StyleWidget` / `Style` / `EMPTY_STYLE`
  (`widgets/style/base.py`) — общий механизм стилизации кнопок,
  переиспользуется и inline-кнопками.
- **Base `Keyboard`** (`widgets/kbd/base.py`) — общий предок; `Or` для
  альтернативных раскладок.
- **`intent_middleware`** (`context/intent_middleware.py`) — определяет, в какой
  контекст диалога уйдёт ответное сообщение (default stack).

---

## Приложение: точные ссылки на исходники

| Что | Ссылка |
|---|---|
| `RequestContact.__init__` / рендер | `src/aiogram_dialog/widgets/kbd/request.py:11-39` |
| `RequestLocation.__init__` / рендер | `src/aiogram_dialog/widgets/kbd/request.py:42-70` |
| `RequestPoll.__init__` / рендер | `src/aiogram_dialog/widgets/kbd/request.py:73-105` |
| Импорт `KeyboardButton, KeyboardButtonPollType` | `src/aiogram_dialog/widgets/kbd/request.py:3` |
| Экспорт в `__all__` / import | `src/aiogram_dialog/widgets/kbd/__init__.py:34-36, 84` |
| Базовый `Keyboard` | `src/aiogram_dialog/widgets/kbd/base.py:15-124` |
| `ReplyKeyboardFactory` | `src/aiogram_dialog/widgets/markup/reply_keyboard.py:14-46` |
| `InlineKeyboardFactory` (дефолт) | `src/aiogram_dialog/widgets/markup/inline_keyboard.py:12` |
| Дефолтная фабрика окна | `src/aiogram_dialog/window.py:38, 48, 98-104` |
| `transform_to_reply_keyboard` / `_transform_to_reply_button` | `src/aiogram_dialog/utils.py:94-133` |
| `add_intent_id` (только inline) | `src/aiogram_dialog/utils.py:211-218` |
| Обработка входящего сообщения / default stack | `src/aiogram_dialog/context/intent_middleware.py:281-341` |
| `MessageInput` | `src/aiogram_dialog/widgets/input/base.py:35-68` |
| `StyleWidget` protocol / `Style` / `EMPTY_STYLE` | `src/aiogram_dialog/api/internal/widgets.py:51-64`, `src/aiogram_dialog/widgets/style/base.py:79-149` |
| `ButtonStyle` (опц. enum) | `src/aiogram_dialog/api/internal/widgets.py:19-22` |
| Доки RequestPoll | `docs/widgets/keyboard/request_poll/index.rst`, `.../example.py` |
| Пример reply-кнопок | `example/mega/bot_dialogs/reply_buttons.py` |
