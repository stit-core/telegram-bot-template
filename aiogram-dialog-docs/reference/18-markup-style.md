---
zone: 18
title: "Фабрики разметки (markup_factory) и стили: inline vs reply, ForceReply, ReplyKeyboard"
source_repo: aiogram_dialog
source_ref: develop @ 08abdf0 (2026-05-02)
aiogram_min: ">=3.14.0"
scope:
  - src/aiogram_dialog/widgets/markup/inline_keyboard.py
  - src/aiogram_dialog/widgets/markup/reply_keyboard.py
  - src/aiogram_dialog/widgets/markup/force_reply.py
  - src/aiogram_dialog/widgets/style/base.py
  - src/aiogram_dialog/widgets/style/multi.py
related:
  - src/aiogram_dialog/api/internal/widgets.py  # MarkupFactory, RawKeyboard, StyleWidget protocols
  - src/aiogram_dialog/api/entities/new_message.py  # MarkupVariant
  - src/aiogram_dialog/utils.py  # add_intent_id, transform_to_reply_keyboard, reply-callback codec
  - src/aiogram_dialog/window.py  # markup_factory интеграция
  - src/aiogram_dialog/manager/manager.py  # scope-проверка reply
  - src/aiogram_dialog/manager/message_manager.py  # send/edit/remove reply
  - src/aiogram_dialog/context/intent_middleware.py  # декод reply-callback
tags: [markup, factory, reply-keyboard, inline-keyboard, force-reply, style, button-style, emoji]
---

# Зона 18. Фабрики разметки (`markup_factory`) и стили

## 0. TL;DR

- `markup_factory` — параметр `Window`, который превращает «сырую» клавиатуру
  (`RawKeyboard = list[list[InlineKeyboardButton | KeyboardButton]]`), собранную
  виджетами, в финальный `reply_markup` для Telegram.
- По умолчанию — `InlineKeyboardFactory()` (inline-кнопки + дописывание `intent_id`
  в `callback_data`).
- Альтернативы из коробки: `ReplyKeyboardFactory(...)` (reply-клавиатура под полем
  ввода) и `ForceReplyFactory(...)` (принудительный reply без кнопок).
- Стили (`Style`, `StyleCase`, `Or`) задают **цвет кнопки** (`ButtonStyle`) и
  **custom emoji** (`emoji_id`) для inline-виджетов; передаются параметром `style=`.
- Reply и inline **несовместимы** в одном окне (одна фабрика на окно). От
  reply-кнопок не приходит настоящий `callback_query` — библиотека эмулирует его
  через кодирование `callback_data` в zero-width-символы текста кнопки.
- Reply-клавиатуру **нельзя** использовать в неосновном стеке (только
  `DEFAULT_STACK_ID`), иначе `InvalidKeyboardType`.

---

## 1. Протокол `MarkupFactory` и место в конвейере рендера

### 1.1. Протокол

`src/aiogram_dialog/api/internal/widgets.py:135-142`

```python
@runtime_checkable
class MarkupFactory(Protocol):
    @abstractmethod
    async def render_markup(
            self, data: dict, manager: DialogManager, keyboard: RawKeyboard,
    ) -> MarkupVariant:
        """Render reply_markup using prepared keyboard."""
        raise NotImplementedError
```

| Элемент | Значение |
|---|---|
| Тип | `runtime_checkable` `Protocol` (структурная типизация, наследование не обязательно) |
| Единственный метод | `async render_markup(data, manager, keyboard) -> MarkupVariant` |
| `data` | словарь окна (`getter` + `dialog.load_data`) |
| `manager` | `DialogManager` (нужен для `current_context().id`, `is_preview()`, рендера текста плейсхолдера) |
| `keyboard` | уже отрендеренная виджетами `RawKeyboard` |
| Возврат | один из вариантов `MarkupVariant` (см. ниже) |

### 1.2. Типы

`src/aiogram_dialog/api/internal/widgets.py:77-78`

```python
ButtonVariant = InlineKeyboardButton | KeyboardButton
RawKeyboard = list[list[ButtonVariant]]
```

`src/aiogram_dialog/api/entities/new_message.py:16-21`

```python
MarkupVariant = (
    ForceReply
    | InlineKeyboardMarkup
    | ReplyKeyboardMarkup
    | ReplyKeyboardRemove
)
```

`RawKeyboard` — список строк, каждая строка — список кнопок. Виджеты
(`Keyboard`-наследники) возвращают именно его из `render_keyboard()`; layout-виджеты
(`Row`, `Column`, `Group`, `ScrollingGroup`) перекомпонуют строки.

### 1.3. Интеграция в `Window`

`src/aiogram_dialog/window.py`

```python
_DEFAULT_MARKUP_FACTORY = InlineKeyboardFactory()          # :38

class Window(WindowProtocol):
    def __init__(
            self, *widgets, state,
            markup_factory: MarkupFactory = _DEFAULT_MARKUP_FACTORY,  # :48
            ...
    ):
        ...
        self.markup_factory = markup_factory               # :68

    async def render_kbd(self, data, manager) -> MarkupVariant:  # :98-104
        keyboard = await self.keyboard.render_keyboard(data, manager)
        return await self.markup_factory.render_markup(data, manager, keyboard)
```

Порядок в `Window.render` (`window.py:147-177`):

1. `load_data` → собирает `data`.
2. `self.keyboard.render_keyboard(data, manager)` → `RawKeyboard`
   (`self.keyboard` — корневой layout-контейнер всех клавиатурных виджетов).
3. `markup_factory.render_markup(data, manager, keyboard)` → `MarkupVariant`.
4. Результат кладётся в `NewMessage.reply_markup`.

> Дефолтный экземпляр `InlineKeyboardFactory` **разделяется** между всеми окнами
> без явного `markup_factory`. Фабрики из коробки stateless по запросу (никакого
> мутабельного состояния между вызовами), поэтому это безопасно.

---

## 2. `InlineKeyboardFactory` (дефолт)

`src/aiogram_dialog/widgets/markup/inline_keyboard.py:12-20`

```python
class InlineKeyboardFactory(MarkupFactory):
    async def render_markup(self, data, manager, keyboard) -> MarkupVariant:
        # TODO validate buttons
        add_intent_id(keyboard, manager.current_context().id)
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
```

| Аспект | Детали |
|---|---|
| Конструктор | без параметров |
| Что делает | дописывает `intent_id` в `callback_data` каждой inline-кнопки, оборачивает в `InlineKeyboardMarkup` |
| Возврат | `InlineKeyboardMarkup` |
| Совместимые кнопки | любые `InlineKeyboardButton` (Button, Url, Select, Checkbox, Radio, Calendar, Counter, SwitchInlineQuery, CopyText…) |

### 2.1. `add_intent_id` — как привязывается контекст диалога

`src/aiogram_dialog/utils.py:200-224`

```python
CB_SEP = "\x1D"  # ASCII Group Separator

def intent_callback_data(intent_id, callback_data) -> str | None:
    if callback_data is None:
        return None
    prefix = intent_id + CB_SEP
    if callback_data.startswith(prefix):
        return callback_data         # идемпотентно: повторно не префиксует
    return prefix + callback_data

def add_intent_id(keyboard: RawKeyboard, intent_id: str):
    for row in keyboard:
        for button in row:
            if isinstance(button, InlineKeyboardButton):
                button.callback_data = intent_callback_data(
                    intent_id, button.callback_data,
                )

def remove_intent_id(callback_data: str) -> tuple[str | None, str]:
    if CB_SEP in callback_data:
        intent_id, new_data = callback_data.split(CB_SEP, maxsplit=1)
        return intent_id, new_data
    return None, callback_data
```

- Финальная `callback_data = "<intent_id>\x1D<widget_callback>"`.
- На входящем апдейте middleware вызывает `remove_intent_id`, восстанавливает
  `intent_id` (а значит — нужный контекст диалога в стеке) и «чистую»
  `callback_data` виджета.
- `add_intent_id` мутирует кнопки **на месте** (изменяет `button.callback_data`).
  Кнопки без `callback_data` (url, web_app, switch_inline_query, copy_text) не
  трогаются — `intent_id` к ним не дописывается.

### 2.2. Подводный камень: лимит длины callback_data

Telegram ограничивает `callback_data` 64 байтами. `intent_id` (UUID-подобная
строка) занимает часть бюджета. Если своя `callback_data`/`id` виджета длинная,
итог может не влезть. Держите `id` виджетов короткими.

---

## 3. `ReplyKeyboardFactory`

`src/aiogram_dialog/widgets/markup/reply_keyboard.py:14-46`

```python
class ReplyKeyboardFactory(MarkupFactory):
    def __init__(
            self,
            resize_keyboard: bool | None = None,
            one_time_keyboard: bool | None = None,
            input_field_placeholder: TextWidget | None = None,
            selective: bool | None = None,
            is_persistent: bool | None = None,
    ): ...

    async def render_markup(self, data, manager, keyboard) -> MarkupVariant:
        if self.input_field_placeholder:
            placeholder = await self.input_field_placeholder.render_text(data, manager)
        else:
            placeholder = None
        add_intent_id(keyboard, manager.current_context().id)
        return ReplyKeyboardMarkup(
            keyboard=transform_to_reply_keyboard(keyboard),
            resize_keyboard=self.resize_keyboard,
            one_time_keyboard=self.one_time_keyboard,
            input_field_placeholder=placeholder,
            selective=self.selective,
            is_persistent=self.is_persistent,
        )
```

### 3.1. Параметры конструктора

| Параметр | Тип | По умолч. | Назначение (проксируется в `ReplyKeyboardMarkup`) |
|---|---|---|---|
| `resize_keyboard` | `bool \| None` | `None` | подгонять высоту клавиатуры под кнопки |
| `one_time_keyboard` | `bool \| None` | `None` | скрыть клавиатуру после первого нажатия |
| `input_field_placeholder` | `TextWidget \| None` | `None` | **TextWidget**, не строка! Плейсхолдер поля ввода; рендерится через `render_text(data, manager)` |
| `selective` | `bool \| None` | `None` | показывать клавиатуру только адресатам (reply/@mention) |
| `is_persistent` | `bool \| None` | `None` | держать клавиатуру всегда открытой |

> `input_field_placeholder` принимает виджет текста (`Const`, `Format`, `Multi`…),
> а не `str`. Это позволяет вычислять плейсхолдер по `data`/событию. Пример из
> mega: `Format("{event.from_user.username}")`.

### 3.2. `transform_to_reply_keyboard` — конвертация кнопок

`src/aiogram_dialog/utils.py:94-133`

```python
def _transform_to_reply_button(button) -> KeyboardButton:
    if isinstance(button, KeyboardButton):
        return button                       # уже reply-кнопка (Request*)
    if button.web_app:
        return KeyboardButton(text=button.text, web_app=button.web_app)
    if not button.callback_data:
        raise ValueError(
            "Cannot convert inline button without callback_data or web_app",
        )
    style = getattr(button, "style", button.model_extra.get("style"))
    emoji_id = getattr(button, "icon_custom_emoji_id",
                       button.model_extra.get("icon_custom_emoji_id"))
    return KeyboardButton(
        text=join_reply_callback(text=button.text,
                                 callback_data=button.callback_data),
        style=style,
        icon_custom_emoji_id=emoji_id,
    )
```

Логика для каждой кнопки:

1. Уже `KeyboardButton` (от `RequestContact`/`RequestLocation`/`RequestPoll`) →
   возвращается как есть.
2. `InlineKeyboardButton` с `web_app` → `KeyboardButton(text, web_app=...)`.
3. `InlineKeyboardButton` с `callback_data` (обычный `Button`, `Select`,
   `Checkbox`, `Radio`…) → становится **текстовой** `KeyboardButton`, где
   `callback_data` зашита в текст кнопки через zero-width-кодек (см. §6).
   Переносятся `style` и `icon_custom_emoji_id`.
4. `InlineKeyboardButton` **без** `callback_data` и без `web_app` (url,
   switch_inline_query, copy_text, login_url, pay…) → **`ValueError`**.

> Важно: `add_intent_id` вызывается **до** `transform_to_reply_keyboard`, поэтому
> в текст reply-кнопки зашивается уже `"<intent_id>\x1D<callback>"`.

### 3.3. Использование

```python
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import Row, RequestContact, RequestLocation, Checkbox, Radio
from aiogram_dialog.widgets.markup.reply_keyboard import ReplyKeyboardFactory
from aiogram_dialog.widgets.text import Const, Format

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
    markup_factory=ReplyKeyboardFactory(
        input_field_placeholder=Format("{event.from_user.username}"),
        resize_keyboard=True,
    ),
    state=states.ReplyKeyboard.MAIN,
)
```

(адаптировано из `example/mega/bot_dialogs/reply_buttons.py`)

---

## 4. `ForceReplyFactory`

`src/aiogram_dialog/widgets/markup/force_reply.py:13-35`

```python
class ForceReplyFactory(MarkupFactory):
    def __init__(
            self,
            input_field_placeholder: TextWidget | None = None,
            selective: bool | None = None,
    ): ...

    async def render_markup(self, data, manager, keyboard) -> MarkupVariant:
        if self.input_field_placeholder:
            placeholder = await self.input_field_placeholder.render_text(data, manager)
        else:
            placeholder = None
        # TODO validate keyboard
        return ForceReply(
            input_field_placeholder=placeholder,
            selective=self.selective,
        )
```

| Параметр | Тип | Назначение |
|---|---|---|
| `input_field_placeholder` | `TextWidget \| None` | плейсхолдер поля (TextWidget) |
| `selective` | `bool \| None` | force-reply только адресатам |

- Возврат — `ForceReply`: Telegram **открывает поле ответа** на сообщении бота.
- `keyboard` **полностью игнорируется** — клавиатура из виджетов не отрисовывается.
  Любые `Button`/`Select` в окне с этой фабрикой просто не появятся в UI (хотя
  их `on_click` недостижим). Для обработки ответа нужен `MessageInput`.
- `intent_id` не дописывается. Привязка к контексту при ответе пользователя идёт
  через `reply_to_message` (см. `intent_middleware._intent_id_from_reply`, §6.3),
  т.к. ответ — это reply на сообщение бота с inline-клавиатурой; для чистого
  ForceReply (без inline) контекст загрузится как default.

---

## 5. Стили: `Style`, `StyleCase`, `Or`

### 5.1. Протокол `StyleWidget`

`src/aiogram_dialog/api/internal/widgets.py:50-65`

```python
@runtime_checkable
class StyleWidget(Widget, Protocol):
    async def render_style(self, data, manager) -> ButtonStyle | None: ...
    async def render_emoji(self, data, manager) -> str | None: ...
```

`ButtonStyle` — из `aiogram.enums` (если доступен), иначе alias на `str`
(`api/internal/widgets.py:19-22`). Значения: `PRIMARY`, `SECONDARY`, `SUCCESS`,
`DANGER` и т.п.

### 5.2. `BaseStyle` и `Style`

`src/aiogram_dialog/widgets/style/base.py`

```python
class BaseStyle(Whenable, BaseWidget, StyleWidget):          # :18
    def __init__(self, when: WhenCondition = None): ...

    @add_exception_note
    async def render_style(self, data, manager) -> ButtonStyle | None:  # :22
        if not self.is_(data, manager):     # учитывает when=
            return None
        return await self._render_style(data, manager)

    @abstractmethod
    async def _render_style(self, data, manager) -> str | None: ...
    # аналогично render_emoji / _render_emoji

    def __or__(self, other): return Or(self, other)          # :72
    def __ror__(self, other): return Or(other, self)


class Style(BaseStyle):                                      # :79
    def __init__(
        self,
        style: ButtonStyle | None = None,
        emoji_id: str | None = None,
        when: WhenCondition = None,
    ): ...
    async def _render_style(...): return self.style
    async def _render_emoji(...): return self.emoji_id


EMPTY_STYLE = Style(style=None, emoji_id=None, when=None)    # :149
```

| Класс/объект | Назначение |
|---|---|
| `BaseStyle` | абстрактная база; наследует `Whenable` (поддержка `when=`), `BaseWidget`, `StyleWidget`. При переопределении переопределяй `_render_style`/`_render_emoji`, чтобы сохранить обработку `when` |
| `Style(style, emoji_id, when)` | конкретный стиль: цвет (`ButtonStyle`) и/или custom `emoji_id` |
| `EMPTY_STYLE` | дефолт `style=` у всех кнопочных виджетов (`Button`, `RequestContact`, …); рендерит `None/None` |

`when=` через `Whenable.is_()`: если условие ложно — `render_style/render_emoji`
возвращают `None` (стиль не применяется), но кнопка при этом **не скрывается** —
`when` стиля влияет только на сам стиль, а не на видимость кнопки.

### 5.3. Оператор `|` — цепочка fallback (`Or`)

`src/aiogram_dialog/widgets/style/base.py:105-147`

```python
class Or(StyleWidget):
    def __init__(self, *styles): ...
    async def render_style(self, data, manager):
        for style in self.styles:
            res = await style.render_style(data, manager)
            if res:
                return res
        return None
    # render_emoji — аналогично; __or__/__ror__/__ior__ «расплющивают» вложенность
```

`Style(...) | Style(...) | Style(...)` — берёт первый ненулевой результат.
Style и emoji выбираются **независимо** (отдельные проходы по `render_style` и
`render_emoji`). Проверено в `tests/widgets/style/test_base.py`:

```python
text = (
    Style(ButtonStyle.PRIMARY, when=F["a"]) |
    Style(ButtonStyle.SUCCESS, when=F["b"]) |
    Style(ButtonStyle.DANGER)
)
await text.render_style({"a": True}) == ButtonStyle.PRIMARY
await text.render_style({"b": True}) == ButtonStyle.SUCCESS
await text.render_style({})         == ButtonStyle.DANGER
```

### 5.4. `StyleCase` — multi-стиль по селектору

`src/aiogram_dialog/widgets/style/multi.py:16-58`

```python
class StyleCase(BaseStyle):
    def __init__(
        self,
        styles: dict[Any, StyleWidget],
        selector: str | Selector["StyleCase"] | MagicFilter,
        when: WhenCondition = None,
    ): ...
```

| Параметр | Тип | Назначение |
|---|---|---|
| `styles` | `dict[Any, StyleWidget]` | соответствие «ключ → стиль». Ключ `...` (Ellipsis) — дефолтная ветка |
| `selector` | `str` / `Selector` / `MagicFilter` | как вычислить ключ: имя поля в `data` (`new_case_field`), magic-фильтр (`new_magic_selector`) или callable |
| `when` | `WhenCondition` | стандартное условие |

Логика выбора (`_get_selection`, `multi.py:35-42`):

- вычисляет `selection = selector(data, self, manager)`;
- если ключа нет в `styles`, но есть `...` — берёт дефолт;
- если ключа нет и это **preview**-режим (`manager.is_preview()`) — берёт первый
  ключ из `styles` (чтобы preview не падал);
- иначе `selection` остаётся «как есть» → `KeyError` при `styles[selection]`.

> Подводный камень: без ветки `...` и при неизвестном ключе в боевом режиме
> `StyleCase` упадёт `KeyError`. Всегда добавляйте `...: Style(...)`.

### 5.5. Применение стиля и связь с reply

- `style=` есть у `Button`, `Url`(?), `RequestContact/Location/Poll`, `Checkbox`,
  `Radio`, `Calendar` и т.п. (по умолчанию `EMPTY_STYLE`).
- В `Button._render_keyboard` (`widgets/kbd/button.py:52-61`) стиль и emoji
  кладутся в `InlineKeyboardButton(style=..., icon_custom_emoji_id=...)`.
- При конвертации в reply (`_transform_to_reply_button`) `style` и
  `icon_custom_emoji_id` **переносятся** на `KeyboardButton` — стили работают и
  для reply-кнопок.

### 5.6. Экспорт

`src/aiogram_dialog/widgets/style/__init__.py`:
`EMPTY_STYLE`, `BaseStyle`, `Style`, `StyleCase`.
`Or` — внутренний (создаётся оператором `|`), не экспортируется напрямую.

---

## 6. Reply-клавиатура: как «прилетает» клик (zero-width-кодек)

Reply-кнопки в Telegram **не порождают** `callback_query` — пользователь просто
отправляет текст кнопки сообщением. aiogram_dialog решает это кодированием
`callback_data` невидимыми символами в конце текста кнопки и декодированием на
входящем сообщении.

### 6.1. Кодек

`src/aiogram_dialog/utils.py:30-91`

```python
REPLY_CALLBACK_SYMBOLS = "‌‍⁠⁡⁢⁣⁤­" \
                         "\U0001D173...\U0001D17A"  # 16 zero-width символов

def encode_reply_callback(data: str) -> str:   # каждый байт → 2 zero-width символа
def join_reply_callback(text, callback_data) -> str:   # text + encode(callback_data)
def split_reply_callback(data) -> tuple[text, callback]:  # обратно
def decode_reply_callback(data) -> str:
```

- Текст кнопки = `видимый_текст + <zero-width-кодированный callback_data>`.
- В UI пользователь видит только видимый текст; «хвост» невидим.

### 6.2. Декод на входящем сообщении → эмуляция callback

`src/aiogram_dialog/context/intent_middleware.py:298-330`

```python
async def process_message(self, handler, event, data):
    ...
    _, callback_data = split_reply_callback(event.text)
    if callback_data:
        query = ReplyCallbackQuery(
            id="",
            message=InaccessibleBusinessMessage(...),
            original_message=event,
            data=callback_data,
            from_user=event.from_user,
            chat_instance=str(event.chat.id),
        ).as_(data["bot"])
        router = data["event_router"]
        return await router.propagate_event(
            "callback_query", query,
            **{EVENT_SIMULATED: True}, **data,
        )
    ...
```

То есть из reply-нажатия конструируется **искусственный** `callback_query`
(`ReplyCallbackQuery`), который проходит обычный путь обработки клавиатур →
срабатывает `on_click` соответствующего виджета.

### 6.3. `ReplyCallbackQuery`

`src/aiogram_dialog/api/internal/fake_data.py:12-19`

```python
class ReplyCallbackQuery(CallbackQuery):
    original_message: Message
    def answer(self, *args, **kwargs):
        raise ValueError(
            "This callback query is generated from ReplyButton click. "
            "Support of `.answer()` call is impossible.",
        )
```

> Подводный камень: `callback.answer()` (например, всплывающий тост) **нельзя**
> вызвать в `on_click`, если виджет может быть в reply-режиме — будет `ValueError`.
> Настоящего `callback_query.id` у reply-кнопки нет.

### 6.4. Привязка контекста для reply без кодированного callback

Если в сообщении нет кодированного хвоста, но это reply на сообщение бота с inline-
клавиатурой — `_intent_id_from_reply` (`intent_middleware.py:281-296`) достаёт
`intent_id` из `callback_data` первой кнопки этого сообщения. Это поддерживает
ForceReply-сценарий и ручные reply.

---

## 7. Жизненный цикл reply-клавиатуры в `MessageManager`

`src/aiogram_dialog/manager/message_manager.py`

| Метод | Строки | Поведение |
|---|---|---|
| `need_reply_keyboard(new)` | :115-118 | `isinstance(new.reply_markup, ReplyKeyboardMarkup)` |
| `had_reply_keyboard(old)` | :110-113 | флаг `old_message.has_reply_keyboard` |
| `_can_edit` | :155-166 | **нельзя редактировать**, если старое или новое сообщение имеет reply-клавиатуру → всегда delete+send |
| `_message_changed` | :129-153 | reply-клавиатуру нельзя сравнить → если есть reply (старая или новая), считается «изменилось» |
| `remove_reply_kbd` | :266-280 | убирает reply через отправку сообщения `"..."` с `ReplyKeyboardRemove()` |
| `show_message` DELETE_AND_SEND | :175-187 | при reply — сначала шлёт новое, потом удаляет старое (чтобы не «мигало» поле ввода) |
| `_combine`/sent | :67-68 | `has_reply_keyboard` вычисляется по факту отправленного `ReplyKeyboardMarkup` |

Ключевые следствия:
- Любое окно с reply-клавиатурой **не редактируется in-place** — каждый показ
  это новое сообщение (старое удаляется). Это нормально, но влечёт «прыжки» чата
  и потерю edit-оптимизаций.
- Снятие reply-клавиатуры стоит лишнего сообщения `"..."` + `ReplyKeyboardRemove`.

---

## 8. Связь со scope / стеками

`src/aiogram_dialog/manager/manager.py:370-378`

```python
def _ensure_stack_compatible(self, stack, new_message) -> None:
    if stack.id == DEFAULT_STACK_ID:
        return  # no limitations for default stack
    if isinstance(new_message.reply_markup, ReplyKeyboardMarkup):
        raise InvalidKeyboardType(
            "Cannot use ReplyKeyboardMarkup in non default stack",
        )
```

- Reply-клавиатура допустима **только** в основном стеке (`DEFAULT_STACK_ID`).
- В дополнительных стеках (отдельные ветки/окна, запущенные не в главном стеке) —
  `InvalidKeyboardType` (`api/exceptions.py:59`, наследник `DialogsError`).
- Причина: reply-клавиатура принадлежит **чату целиком** (одна на пользователя),
  а не конкретному сообщению; несколько стеков с reply конфликтовали бы.
- `InlineKeyboardMarkup` и `ForceReply` ограничений по стеку не имеют.

---

## 9. Совместимость виджетов с фабриками

| Виджет | Inline (`InlineKeyboardFactory`) | Reply (`ReplyKeyboardFactory`) | ForceReply |
|---|---|---|---|
| `Button`, `Url`(*), `Select`, `Radio`, `Checkbox`, `Counter`, `Calendar`, `Multiselect` | ✅ | ⚠️ становятся текстовыми `KeyboardButton`, клик эмулируется через кодек | ❌ игнорируется |
| `RequestContact` / `RequestLocation` / `RequestPoll` | ❌ (в Telegram request_* допустим только в reply-клавиатуре) | ✅ родные `KeyboardButton(request_*)` | ❌ |
| `WebApp`-кнопка (web_app) | ✅ | ✅ (`KeyboardButton(web_app=...)`) | ❌ |
| `Url` / `SwitchInlineQuery` / `CopyText` / `LoginURL` (без `callback_data`, без `web_app`) | ✅ | ❌ **`ValueError`** при конвертации | ❌ |

(*) `Url` — это `InlineKeyboardButton(url=...)` без `callback_data` → в reply
вызовет `ValueError`.

`Request*`-виджеты (`widgets/kbd/request.py`) изначально генерируют
`KeyboardButton`, поэтому имеют смысл **только** с `ReplyKeyboardFactory`. В inline-
окне они дадут невалидную inline-клавиатуру.

---

## 10. Подводные камни и краевые случаи (для продакшн-шаблона)

1. **Одна фабрика на окно.** `markup_factory` один на `Window`. Нельзя смешивать
   inline и reply кнопки в одном окне — фабрика определяет тип всей клавиатуры.
   Для смешанного UX делайте отдельные окна/состояния.

2. **`callback.answer()` недоступен для reply.** `ReplyCallbackQuery.answer()`
   бросает `ValueError`. Если `on_click` универсального виджета вызывает
   `.answer()` (тост/алерт), он сломается в reply-окне. Проверяйте тип или не
   используйте `.answer()` в shared-виджетах.

3. **`input_field_placeholder` — это `TextWidget`, а не `str`.**
   `ReplyKeyboardFactory(input_field_placeholder="text")` некорректно — нужен
   `Const("text")` / `Format(...)`. Иначе у строки нет `render_text` → ошибка.

4. **`Url`/`SwitchInlineQuery`/`CopyText` в reply-окне → `ValueError`.**
   Inline-кнопки без `callback_data` и без `web_app` не конвертируются в reply.

5. **Reply запрещён вне default-стека** → `InvalidKeyboardType`. Не используйте
   `ReplyKeyboardFactory` в окнах, которые могут запускаться в дополнительном
   стеке (через `bg`/отдельные ветки).

6. **Reply-окна не редактируются in-place.** `_can_edit` всегда `False` при
   reply → каждый показ = delete+send. Чат «прыгает», edit-оптимизации не работают.

7. **Лимит 64 байта на `callback_data`.** `intent_id` + ваша `callback_data`
   должны уложиться. Короткие `id` виджетов. В reply этот же текст ещё и
   кодируется в zero-width-хвост (длина текста кнопки растёт, но в видимый лимит
   текста кнопки укладываются обычно).

8. **ForceReply игнорирует клавиатуру.** Виджеты-кнопки в окне с
   `ForceReplyFactory` не отрисуются. Обрабатывайте ответ только через
   `MessageInput`.

9. **`StyleCase` без ветки `...` падает `KeyError`** при неизвестном ключе в
   боевом режиме (в preview берётся первый ключ). Всегда задавайте дефолт.

10. **`when=` у `Style` влияет только на стиль, не на видимость кнопки.** Чтобы
    скрыть кнопку, используйте `when=` самого виджета, а не его `style`.

11. **`add_intent_id` мутирует `keyboard` на месте** и идемпотентен (повторно не
    префиксует). Кастомная фабрика, вызывающая его дважды, безопасна, но помните о
    мутации входного списка кнопок.

12. **Custom emoji (`emoji_id`) и `ButtonStyle`** требуют поддержки на стороне
    Telegram/aiogram (`ButtonStyle` — `aiogram.enums`, иначе деградирует до `str`).
    Это относительно новые поля API; проверяйте версию.

---

## 11. Кастомная `MarkupFactory` (шаблон)

Поскольку `MarkupFactory` — `runtime_checkable Protocol`, достаточно реализовать
`render_markup`. Можно обернуть существующую фабрику:

```python
from aiogram.types import InlineKeyboardMarkup
from aiogram_dialog import DialogManager
from aiogram_dialog.api.internal.widgets import MarkupFactory, MarkupVariant, RawKeyboard
from aiogram_dialog.utils import add_intent_id


class MyInlineFactory(MarkupFactory):
    async def render_markup(
            self, data: dict, manager: DialogManager, keyboard: RawKeyboard,
    ) -> MarkupVariant:
        # своя валидация/трансформация keyboard
        add_intent_id(keyboard, manager.current_context().id)  # не забыть intent!
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
```

> Если своя фабрика возвращает inline-клавиатуру, **обязательно** вызовите
> `add_intent_id`, иначе клики не привяжутся к контексту диалога и
> `on_click` не сработают.

---

## 12. Карта файлов зоны

| Файл | Что внутри |
|---|---|
| `widgets/markup/inline_keyboard.py` | `InlineKeyboardFactory` (дефолт) |
| `widgets/markup/reply_keyboard.py` | `ReplyKeyboardFactory` |
| `widgets/markup/force_reply.py` | `ForceReplyFactory` |
| `widgets/markup/__init__.py` | пустой (импорт по полному пути) |
| `widgets/style/base.py` | `BaseStyle`, `Style`, `Or`, `EMPTY_STYLE` |
| `widgets/style/multi.py` | `StyleCase` |
| `widgets/style/__init__.py` | экспорт `EMPTY_STYLE`, `BaseStyle`, `Style`, `StyleCase` |
| `api/internal/widgets.py` | протоколы `MarkupFactory`, `StyleWidget`, `RawKeyboard`, `ButtonVariant` |
| `api/entities/new_message.py` | `MarkupVariant`, `NewMessage`, `OldMessage` |
| `utils.py` | `add_intent_id`, `remove_intent_id`, `transform_to_reply_keyboard`, zero-width-кодек |
| `window.py` | интеграция `markup_factory` (`render_kbd`) |
| `manager/manager.py` | `_ensure_stack_compatible` (scope-запрет reply) |
| `manager/message_manager.py` | send/edit/remove reply-клавиатуры |
| `context/intent_middleware.py` | декод reply-callback → эмуляция `callback_query` |
| `api/internal/fake_data.py` | `ReplyCallbackQuery` |
| `api/exceptions.py` | `InvalidKeyboardType` |
| `docs/widgets/style/index.rst` | дока по `Style` |
| `example/mega/bot_dialogs/reply_buttons.py` | рабочий пример reply-клавиатуры |
| `tests/widgets/style/test_base.py` | тесты `Style` + `|` |
