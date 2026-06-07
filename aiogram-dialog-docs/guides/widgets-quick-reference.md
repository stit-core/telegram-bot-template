---
title: "Шпаргалка по виджетам aiogram_dialog"
kind: quick-reference
source_repo: "aiogram_dialog (develop @ 08abdf0, 2026-05-02)"
aiogram_min: ">=3.14.0"
based_on: reference/08..18
updated: 2026-06-07
---

# Шпаргалка по виджетам aiogram_dialog

Компактный справочник: один виджет — одна строка. Колонки таблиц:

- **Виджет** — класс (импорт см. ниже).
- **Сигнатура** — ключевые параметры конструктора (порядок реальный; `=` показывает дефолт).
- **Назначение** — что делает.
- **Состояние / Managed** — где хранится стейт (`widget_data` / нет) и Managed-обёртка с методом чтения.
- **Подводный камень** — самое важное, что ломает в проде.
- **Глава** — файл `reference/`.

Импорты:
```python
from aiogram_dialog.widgets.text import Const, Format, Multi, Case, Jinja, List, Progress, ScrollingText, setup_jinja
from aiogram_dialog.widgets.kbd import (
    Button, Url, WebApp, LoginURLButton, CopyText,
    SwitchInlineQuery, SwitchInlineQueryCurrentChat, SwitchInlineQueryChosenChatButton,
    Group, Row, Column,
    Start, SwitchTo, Next, Back, Cancel,
    Select, Radio, Multiselect, Toggle, Checkbox, Counter,
    Calendar, CalendarConfig, CalendarScope,
    RequestContact, RequestLocation, RequestPoll,
    ScrollingGroup, ListGroup, FirstPage, PrevPage, CurrentPage, NextPage, LastPage, NumberedPager,
)
from aiogram_dialog.widgets.kbd.stub_scroll import StubScroll   # экспортируется отдельно
from aiogram_dialog.widgets.kbd.time import TimeSelect
from aiogram_dialog.widgets.common import sync_scroll
from aiogram_dialog.widgets.input import MessageInput, TextInput, CombinedInput
from aiogram_dialog.widgets.media import StaticMedia, DynamicMedia, MediaScroll
from aiogram_dialog.widgets.link_preview import LinkPreview
from aiogram_dialog.widgets.markup.inline_keyboard import InlineKeyboardFactory
from aiogram_dialog.widgets.markup.reply_keyboard import ReplyKeyboardFactory
from aiogram_dialog.widgets.markup.force_reply import ForceReplyFactory
from aiogram_dialog.widgets.style import Style, StyleCase, EMPTY_STYLE
from aiogram_dialog.api.entities import MediaAttachment, MediaId
```

---

## 1. Text — текст сообщения окна

В одном окне ровно **один** `TextWidget` (обычно `Multi`/`Const`/`Format`). `when: str | MagicFilter | Predicate | None`. Скрытый `when` даёт `""`.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Const` | `Const(text: str, when=None)` | статический текст, `{}` НЕ интерполируются | нет | используется как обёртка `str` в `+`/`\|`; никакого `.format` | 08 |
| `Format` | `Format(text: str, when=None)` | `str.format_map(data)`: `{key}`, `{d[k]}`, `{x:.2f}` | нет | `KeyError`, если ключа нет в `data` (нет тихого дефолта); `{{`/`}}` для литералов | 08 |
| `Multi` | `Multi(*texts, sep="\n", when=None)` | склейка нескольких текстов | нет | `filter(None,...)` отбрасывает пустые — скрытые элементы не дают лишних `\n`; `a+b ≡ Multi(a,b,sep="")` | 08 |
| `Or` (через `\|`) | `text1 \| text2 \| ...` | первый непустой рендер (fallback) | нет | конструктора с `when` нет; создаётся только оператором `\|` | 08 |
| `Case` | `Case(texts: dict, selector, when=None)` | выбор текста по селектору; ключ `...` = дефолт | нет | без `...`-ветки и неизвестном значении → `KeyError` (в проде); тип ключа == тип селектора | 08 |
| `Jinja` | `Jinja(text: str, when=None)` | рендер Jinja2-шаблона (`text` = сам шаблон) | нет | нужен `parse_mode="HTML"`; `autoescape=True` экранирует значения; кастом-фильтры — только через `setup_jinja(dp, ...)` | 08 |
| `List` | `List(field, items, sep="\n", when=None, id=None, page_size=None, on_page_changed=None)` | повтор `field` на каждый элемент | страница в `widget_data[id]` (нужен `id`); `ManagedScroll` | `items="key"` → `KeyError` (itemgetter); в шаблоне внешние данные через `{data[...]}`, не верхний уровень | 08/15 |
| `Progress` | `Progress(field: str, width=10, filled="🟥", empty="⬜", when=None)` | текстовый прогресс-бар из `data[field]` (0..100) | нет | `data.get(field)` → `None` при отсутствии → `TypeError`; значение не клампится | 08 |
| `ScrollingText` | `ScrollingText(text, id: str, page_size=0, when=None, on_page_changed=None)` | режет длинный текст на страницы по символам | страница в `widget_data[id]`; `ManagedScroll` | `page_size=0` (дефолт) → `ZeroDivisionError`; режет по символам — может рвать HTML-теги | 08/15 |

`setup_jinja(dp, filters=..., **env_kwargs)` — регистрирует Jinja-окружение; `dp` должен быть `Dispatcher` (`Bot` → `DeprecationWarning`).

---

## 2. Keyboard: базовые / контейнеры

Листовые кнопки рендерят `[[InlineKeyboardButton]]`. `text`/`url`/`query` — это `TextWidget`, не `str`. `style: StyleWidget = EMPTY_STYLE`. `on_click(callback, button, manager)` — async, 3 позиционных; `callback.answer()` вызывать НЕ нужно (диалог делает сам).

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Button` | `Button(text, id: str, on_click=None, when=None, style=EMPTY_STYLE)` | inline-кнопка с callback | нет; `manager.find` → сам `Button` | `id` ОБЯЗАТЕЛЕН; `on_click` async-only; не вызывать `callback.answer()` | 09 |
| `Url` | `Url(text, url, id=None, when=None, style=EMPTY_STYLE)` | кнопка-ссылка | нет | НЕТ `on_click` (callback не приходит); url — HTTPS; в reply → `ValueError` | 09 |
| `WebApp` | `WebApp(text, url, id=None, when=None, style=EMPTY_STYLE)` | открыть Telegram Web App | нет | url обязан быть HTTPS; наследует `Url` | 09 |
| `LoginURLButton` | `LoginURLButton(text, url, forward_text=None, bot_username=None, request_write_access=None, id=None, when=None, style=EMPTY_STYLE)` | Telegram Login | нет | url HTTPS; без `callback_data` → в reply `ValueError` | 09 |
| `CopyText` | `CopyText(text, copy_text, when=None, style=EMPTY_STYLE)` | копировать текст в буфер (Bot API 7.11+) | нет; `id` НЕ принимается | нет callback/on_click; нет `id`; требует свежий aiogram | 09/12 |
| `SwitchInlineQuery` | `SwitchInlineQuery(text, switch_inline_query, id=None, when=None, style=EMPTY_STYLE)` | выбрать чат, вставить `@bot query` | нет | нет callback; в reply → `ValueError` | 09 |
| `SwitchInlineQueryCurrentChat` | `SwitchInlineQueryCurrentChat(text, switch_inline_query_current_chat, id=None, when=None, style=EMPTY_STYLE)` | вставить inline-query в текущий чат | нет | то же | 09 |
| `SwitchInlineQueryChosenChatButton` | `SwitchInlineQueryChosenChatButton(text, query, allow_user_chats=None, allow_bot_chats=None, allow_group_chats=None, allow_channel_chats=None, id=None, when=None, style=EMPTY_STYLE)` | inline-query в выбранный чат с фильтрами | нет | имя класса с суффиксом `Button` (в отличие от двух других) | 09 |
| `Group` | `Group(*buttons, id=None, width: int\|None=None, when=None)` | контейнер раскладки | нет (layout) | `width=None` сохраняет строки детей; `width=N` СПЛЮЩИВАЕТ иерархию вложенных `Row`/`Column` | 09 |
| `Row` | `Row(*buttons, id=None, when=None)` | всё в одну строку (`Group(width=9999)`) | нет | сплющивает вложенную иерархию | 09 |
| `Column` | `Column(*buttons, id=None, when=None)` | по одной кнопке в строке (`Group(width=1)`) | нет | `Column` ≠ `Group(width=None)`: расплющит вложенный `Row` в столбец | 09 |

---

## 3. Keyboard: навигация (кнопки-переходы)

Все наследуют `Button`. Сначала вызывается `user_on_click`, ПОТОМ встроенный переход (`manager.start/switch_to/next/back/done`). Отменить переход можно только `raise CancelEventProcessing` из `user_on_click`. Доп. параметр `show_mode: ShowMode | None`.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Метод менеджера / `id` | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Start` | `Start(text, id: str, state, data=None, on_click=None, show_mode=None, mode=StartMode.NORMAL, when=None, style=EMPTY_STYLE)` | запустить ДРУГОЙ диалог | `manager.start(...)`; `id` ОБЯЗАТЕЛЕН | без `RESET_STACK` контексты копятся (лимит ~100); старт поверх EXCLUSIVE → `ValueError` | 10 |
| `SwitchTo` | `SwitchTo(text, id: str, state, on_click=None, when=None, show_mode=None, style=EMPTY_STYLE)` | окно ВНУТРИ диалога | `manager.switch_to(...)`; `id` ОБЯЗАТЕЛЕН | чужой `StatesGroup` → `ValueError` «Cannot switch to another state group» | 10 |
| `Next` | `Next(text=Const("Next"), id="__next__", on_click=None, show_mode=None, when=None, style=EMPTY_STYLE)` | след. окно по порядку в `Dialog(...)` | `manager.next(...)`; `id` опц. | на последнем окне → `ValueError`; порядок = порядок `Window` в `Dialog`, не в `StatesGroup` | 10 |
| `Back` | `Back(text=Const("Back"), id="__back__", on_click=None, show_mode=None, when=None, style=EMPTY_STYLE)` | пред. окно по порядку | `manager.back(...)`; `id` опц. | на первом окне → `ValueError` | 10 |
| `Cancel` | `Cancel(text=Const("Cancel"), id="__cancel__", result=None, on_click=None, when=None, show_mode=None, style=EMPTY_STYLE)` | закрыть текущий диалог | `manager.done(result, ...)`; `id` опц. | `result` → родителю в `on_process_result`; несколько Cancel/Next/Back с `on_click` → задать РАЗНЫЕ `id` (иначе конфликт дефолтных) | 10 |

`StartMode`: `NORMAL` / `RESET_STACK` / `NEW_STACK`. `ShowMode`: `AUTO` / `EDIT` / `SEND` / `DELETE_AND_SEND` / `NO_UPDATE`.

---

## 4. Keyboard: выбор из списка

`item_id_getter: item -> str|int`. `items: str | Callable | MagicFilter | Sequence`. `type_factory: str -> T` (дефолт `str`) — приводит id обратно, влияет на `get_checked`/аргумент `on_click`; внутри хранится/сравнивается строка. `on_click(event, managed, manager, item_id: T)`.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Select` | `Select(text, id, item_id_getter, items, type_factory=str, on_click=None, when=None, style=EMPTY_STYLE)` | список кнопок, одиночный клик без состояния | нет состояния; `manager.find` → `ManagedSelect` | все кнопки в ОДИН ряд — оборачивай в `Column`/`Group` | 11 |
| `Radio` | `Radio(checked_text, unchecked_text, id, item_id_getter, items, type_factory=str, on_click=None, on_state_changed=None, when=None, checked_style=EMPTY_STYLE, unchecked_style=EMPTY_STYLE)` | одиночный выбор | строка-id в `widget_data[id]`; `ManagedRadio.get_checked() -> T\|None`, `is_checked`, `set_checked` | начального выбора нет — задать `set_checked(...)` на старте | 11 |
| `Multiselect` | `Multiselect(checked_text, unchecked_text, id, item_id_getter, items, min_selected=0, max_selected=0, type_factory=str, on_click=None, on_state_changed=None, when=None, checked_style=EMPTY_STYLE, unchecked_style=EMPTY_STYLE)` | множественный выбор | `list[str]` в `widget_data[id]`; `ManagedMultiselect.get_checked() -> list[T]`, `is_checked`, `set_checked`, `reset_checked` | `max_selected=0` = безлимит; `min_selected` не задаёт старт; помнит исчезнувшие id; `reset_checked` игнорит min и НЕ зовёт `on_state_changed` | 11 |
| `Toggle` | `Toggle(text, id, item_id_getter, items, type_factory=str, on_click=None, on_state_changed=None, when=None, style=EMPTY_STYLE)` | одна кнопка-переключатель (цикл по элементам) | как `Radio` (общий `widget_data`); `ManagedToggle` = `ManagedRadio` | ОДИН `text` (не checked/unchecked); делит состояние с `Radio` при общем `id` | 11 |

---

## 5. Keyboard: состояние (stateful single-кнопки)

Состояние в `widget_data[id]`; `default` «прилипает» после первого чтения (`setdefault`). `manager.find(id)` → Managed-обёртка (методы без `manager`). `set_checked`/`set_value` — АБСОЛЮТНАЯ установка, не toggle.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Checkbox` | `Checkbox(checked_text, unchecked_text, id, on_click=None, on_state_changed=None, default=False, when=None, checked_style=EMPTY_STYLE, unchecked_style=EMPTY_STYLE)` | вкл/выкл одной кнопкой | `bool` в `widget_data[id]`; `ManagedCheckbox.is_checked() -> bool`, `set_checked(bool)` | `id` обязателен; `set_checked` не toggle — для инверсии `set_checked(not is_checked())`; `default` прилипает | 12 |
| `Counter` | `Counter(id, plus=Const("+"), minus=Const("-"), text=Format("{value:g}"), min_value=0, max_value=999999, increment=1, default=0, cycle=False, on_click=None, on_text_click=None, on_value_changed=None, when=None, plus_style=EMPTY_STYLE, minus_style=EMPTY_STYLE, value_style=EMPTY_STYLE)` | ввод числа −/значение/+ | `float` в `widget_data[id]`; `ManagedCounter.get_value() -> float`, `set_value(float)` | `set_value` МОЛЧА игнорит вне `[min,max]` (не клампит); без `cycle` упирается в границу; тип `float` (приводи `int(...)`); `on_click` срабатывает и на клике по значению | 12 |

---

## 6. Keyboard: дата / время

Оба сами рендерят многострочную клавиатуру и хранят стейт в `widget_data[id]`. У `TimeSelect` 2-й позиционный — `when`, не колбэк (колбэки только по имени!).

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `Calendar` | `Calendar(id, on_click=None, config: CalendarConfig\|None=None, when=None)` | выбор даты (scope DAYS/MONTHS/YEARS) | `current_scope`/`current_offset` в `widget_data[id]`; `ManagedCalendar.get_scope/get_offset/set_scope/set_offset` | `on_click(event, widget, manager, date)` ТОЛЬКО для дней (не месяц/год); `config.timezone` фиксируется на импорте → задавай явно; выбранная дата naive `date` | 13 |
| `TimeSelect` | `TimeSelect(id, when=None, hour_header=..., minute_header=..., button_text=..., button_selected_text=..., *_style=EMPTY_STYLE, on_hour_click=None, on_minute_click=None, on_value_changed=None, hour_width=6, minute_precision=5, minute_width=6)` | выбор часа+минуты | `[hour, minute]` в `widget_data[id]`; `ManagedTimeSelect.get_value() -> time\|None`, `set_value(time\|None)` | 2-й позиционный = `when`; `value=None` пока не выбраны ОБА компонента; нет секунд/AM-PM | 13 |

Тонкая кастомизация — наследование `Calendar` + переопределение `_init_views()`/`_get_user_config()` (см. mega-пример, не `docs/.../custom.py` — он устарел).

---

## 7. Keyboard: reply-request

Все три — `KeyboardButton` (**reply**-клавиатура), работают ТОЛЬКО с `markup_factory=ReplyKeyboardFactory(...)`. НЕТ `on_click`/callback/`id`; результат ловится `MessageInput` по `content_type`. `text` — `TextWidget`.

> **`RequestUser` / `RequestUsers` / `RequestChat` в библиотеке НЕТ** — делать вручную подклассом `Keyboard`, возвращающим `KeyboardButton(request_users=KeyboardButtonRequestUsers(...))` и т.п. (см. глава 14, §11).

| Виджет | Сигнатура (ключевые параметры) | Назначение | Что присылает Telegram | Подводный камень | Глава |
|---|---|---|---|---|---|
| `RequestContact` | `RequestContact(text, when=None, style=EMPTY_STYLE)` | поделиться своим номером | `message.contact` | reply-only; ловить через `MessageInput(..., content_types=ContentType.CONTACT)` | 14 |
| `RequestLocation` | `RequestLocation(text, when=None, style=EMPTY_STYLE)` | поделиться геопозицией | `message.location` | reply-only; `content_types=ContentType.LOCATION` | 14 |
| `RequestPoll` | `RequestPoll(text, poll_type=None, when=None, style=EMPTY_STYLE)` | создать опрос | `message.poll` | `poll_type` (`"quiz"`/`"regular"`) НЕ валидируется библиотекой; `content_types=ContentType.POLL` | 14 |

Общее ограничение: результат корректно доезжает только в **дефолтном стеке** (нет callback/intent-id у reply-кнопок). Reply-клавиатура персистентна и не редактируется in-place.

---

## 8. Scroll / пагинация

Единый механизм: страница хранится в `widget_data[id]` самого **скролла**, пейджеры лишь находят скролл по `id` и зовут `set_page`. `manager.find(id)` → `ManagedScroll.get_page()/set_page(page)/get_page_count(data)`. Скролл и его пейджер ОБЯЗАНЫ быть в одном окне.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `ScrollingGroup` | `ScrollingGroup(*buttons, id, width=None, height=0, when=None, on_page_changed=None, hide_on_single_page=False, hide_pager=False)` | клавиатура постранично (+ встроенный пейджер) | страница в `widget_data[id]`; `ManagedScroll` | `height=0` (дефолт) → `ZeroDivisionError` — ВСЕГДА задавай `height>0`; встроенный пейджер не настраивается (для кастома `hide_pager=True`) | 15 |
| `ListGroup` | `ListGroup(*buttons, id, item_id_getter, items, when=None, page_size=0, on_page_changed=None)` | повтор набора виджетов на каждый item | per-item стейт в `widget_data[id][item_id]`; страница в `[id][""]`; `ManagedListGroup.find_for_item(wid, item_id)` | внутри — `SubManager`: `find` ищет В строке, вне строки — `find_in_parent`; `item_id_getter` обязан давать стабильные id | 15 |
| `StubScroll` | `StubScroll(id, pages: str\|int\|Callable\|MagicFilter, on_page_changed=None)` | хранит страницу без своей клавиатуры (рисует `[[]]`) | страница в `widget_data[id]`; `ManagedScroll` | для пагинации текста/медиа из getter; getter читает `get_page()` (`+1` для UI) | 15 |
| `FirstPage` | `FirstPage(scroll, id="__pager__", text=Const("<<"), when=None, style=EMPTY_STYLE)` | на первую страницу | состояния нет (кнопка) | пейджеры по умолчанию делят `id="__pager__"` — задавай явные `id`, если их несколько | 15 |
| `PrevPage` | `PrevPage(scroll, id="__pager__", text=Const("<"), when=None, style=EMPTY_STYLE)` | предыдущая | нет | `scroll` = id-строка или объект `Scroll` | 15 |
| `CurrentPage` | `CurrentPage(scroll, id="__pager__", text=Format("{current_page1}"), when=None, style=EMPTY_STYLE)` | индикатор текущей (клик ничего не меняет) | нет | поля текста: `current_page1`, `target_page1`, `pages`, `data` | 15 |
| `NextPage` | `NextPage(scroll, id="__pager__", text=Const(">"), when=None, style=EMPTY_STYLE)` | следующая | нет | — | 15 |
| `LastPage` | `LastPage(scroll, id="__pager__", text=Const(">>"), when=None, style=EMPTY_STYLE)` | на последнюю | нет | — | 15 |
| `NumberedPager` | `NumberedPager(scroll, id="__pager__", page_text=Format("{target_page1}"), current_page_text=Format("[ {current_page1} ]"), when=None, length: int\|None=None, style=EMPTY_STYLE, current_page_style=EMPTY_STYLE)` | кнопка на каждую страницу | нет | без `length` при многих страницах — слишком длинный ряд (Telegram режет до 8) | 15 |

`sync_scroll(scroll_id, on_page_chaged=None)` — фабрика `on_page_changed`, синхронизирующая несколько скроллов одним пейджером (вешать на «ведущий» скролл). NB: параметр назван `on_page_chaged` (опечатка в либе).

---

## 9. Input — приём входящего сообщения

В окне ровно **один** input-слот; несколько input → авто-`CombinedInput` (первый принявший `True` выигрывает; catch-all — последним). Не рисуются на экране. Колбэк-переходы (`Next()`, `SwitchTo()`...) можно передавать в `on_success`/`func` напрямую.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `MessageInput` | `MessageInput(func, content_types=ContentType.ANY, filter=None, id=None)` | ловит сообщение, зовёт `func(message, widget, manager)` | ничего не хранит (логика в `func`) | сам не пишет в контекст; `ContentType.ANY` в списке отключает фильтр типов; `func=None` = «поглотитель» | 16 |
| `TextInput` | `TextInput(id, type_factory=str, on_success=None, on_error=None, filter=None)` | валидирует+сохраняет текст; `Generic[T]` | исходная СТРОКА в `widget_data[id]`; `ManagedTextInput.get_value() -> T\|None` (пере-парсит) | `id` обязателен; ловит ТОЛЬКО `ValueError` в `on_error` (прочее пробрасывается — делай `raise ValueError`); не-текст → `False`; нет `set_value`/`clear` у Managed | 16 |
| `CombinedInput` | `CombinedInput(*inputs, filter=None)` | объединяет несколько input | без `id` | создаётся авто; общий `filter` — «гейт»; ищи вложенные `TextInput` по их `id` | 16 |

Общее: обычное сообщение грузит контекст из `DEFAULT_STACK_ID` — ввод в неосновном стеке без reply на inline-сообщение бота не дойдёт.

---

## 10. Media — одно вложение на окно

В окне ровно **один** медиа-виджет (несколько → `ValueError`; для выбора источника — оператор `|`/`Or` или `when`). `path`/`url` у `StaticMedia` — `TextWidget`/`str`. Приоритет источника: `file_id` > `url` > `path`.

| Виджет | Сигнатура (ключевые параметры) | Назначение | Состояние / Managed | Подводный камень | Глава |
|---|---|---|---|---|---|
| `StaticMedia` | `StaticMedia(*, path=None, url=None, type=ContentType.PHOTO, use_pipe=False, media_params=None, when=None)` | медиа по пути/URL (с кешем `file_id`) | нет | все параметры keyword-only; относительный `path` резолвится от CWD — давай абсолютные; `file_id` напрямую НЕ задаётся | 17 |
| `DynamicMedia` | `DynamicMedia(selector: str\|Callable, when=None)` | готовый `MediaAttachment` из `data` | нет | `selector` СИНХРОННЫЙ (async-работу делай в getter); `DynamicMedia("key")` → `KeyError`, если ключа нет | 17 |
| `MediaScroll` | `MediaScroll(media: Media, items, id, when=None, on_page_changed=None)` | карусель (1 item = 1 страница) | страница в `widget_data[id]`; `ManagedScroll` | пустой/укороченный `items` → `IndexError` (`items[pages]`); сбрасывай страницу при удалении / оборачивай в `when` | 17 |
| `LinkPreview` | `LinkPreview(url: TextWidget\|None=None, is_disabled=False, prefer_small_media=False, prefer_large_media=False, show_above_text=False, when=None)` | настройка превью ссылок | нет | `url` ТОЛЬКО `TextWidget` (строку — в `Const(...)`); влияет лишь на текстовые сообщения; несовместим с `disable_web_page_preview` | 17 |

`MediaAttachment(type, url=None, path=None, file_id: MediaId|None=None, use_pipe=False, **kwargs)` — хотя бы один из `url`/`path`/`file_id` обязателен. Редактирование медиа поддерживает только 5 типов (`ANIMATION/DOCUMENT/AUDIO/PHOTO/VIDEO`).

---

## 11. Markup-фабрики (`markup_factory=` у `Window`)

Одна фабрика на окно — inline и reply несовместимы. По умолчанию `InlineKeyboardFactory`. `input_field_placeholder` — `TextWidget`, не `str`.

| Фабрика | Сигнатура (ключевые параметры) | Назначение | Подводный камень | Глава |
|---|---|---|---|---|
| `InlineKeyboardFactory` | `InlineKeyboardFactory()` | inline-кнопки + `add_intent_id` в `callback_data` | дефолт окна; своя фабрика обязана звать `add_intent_id`, иначе клики не привяжутся | 18 |
| `ReplyKeyboardFactory` | `ReplyKeyboardFactory(resize_keyboard=None, one_time_keyboard=None, input_field_placeholder: TextWidget\|None=None, selective=None, is_persistent=None)` | reply-клавиатура; inline-кнопки → текстовые с zero-width callback | разрешена ТОЛЬКО в `DEFAULT_STACK_ID` (иначе `InvalidKeyboardType`); `Url`/`SwitchInline*`/`CopyText` → `ValueError`; `callback.answer()` → `ValueError`; окно не редактируется in-place | 18 |
| `ForceReplyFactory` | `ForceReplyFactory(input_field_placeholder: TextWidget\|None=None, selective=None)` | открыть поле ответа без кнопок | `keyboard` ПОЛНОСТЬЮ игнорируется — кнопки не отрисуются; ответ ловить через `MessageInput` | 18 |

Стили: `Style(style: ButtonStyle|None=None, emoji_id=None, when=None)`, `StyleCase(styles: dict, selector, when=None)` (без ветки `...` → `KeyError`), цепочка `Style(...) | Style(...)` (первый ненулевой). `when=` стиля влияет только на стиль, не на видимость кнопки. `EMPTY_STYLE` — нейтральный дефолт.

---

## Общие правила для всех виджетов

1. **Валидация `id`:** `ID_PATTERN = ^[a-zA-Z0-9_.]+$` — только латиница, цифры, `_`, `.`. Пробел, дефис, `:`, кириллица → `InvalidWidgetIdError` уже при конструировании виджета (импорт модуля). `:` запрещён, т.к. это разделитель `widget_id:item` в callback.

2. **Лимит `callback_data` — 64 байта (UTF-8), без явной проверки в либе.** Реальная строка = `<intent_id>\x1D<widget_id>[:<item>]`. На твой `id`+`item` остаётся меньше 64 байт; превышение всплывёт как ошибка Telegram API при показе окна, не при сборке. Держи `id` короткими (особенно у `Select`/`Radio`/`ListGroup`, где добавляется `:item`).

3. **`id` уникален в пределах окна.** Дубли дают одинаковый `callback_data` → часть кнопок «мёртвая», stateful-виджеты затирают состояние друг друга. Для пагинаторов с дефолтным `__pager__` и переходных кнопок с дефолтными `id` — задавай явные `id`, если их несколько.

4. **`when`-формы:** `None` (всегда показывать) · `str` (`bool(data.get(name))`) · `MagicFilter` (`F[...].resolve(data)`) · `Predicate(data, widget, manager) -> bool`. Скрытый `when` ПОЛНОСТЬЮ убирает виджет (`[]`/`None`/`""`), а не делает его неактивным; для условных блоков оборачивай в `Group(when=...)`. Виджет, скрытый через `when`, всё равно есть в дереве и находится `manager.find`.

5. **`manager.find(id)` → Managed-обёртка** (`widget.managed(self)`), не сам виджет; у обёртки методы без аргумента `manager`. Методы чтения состояния: `Checkbox.is_checked()` · `Counter.get_value()` · `Radio/Toggle.get_checked()` · `Multiselect.get_checked()/is_checked()` · `Calendar.get_scope()/get_offset()` · `TimeSelect.get_value()` · `TextInput.get_value()` · скроллы `get_page()/get_page_count(data)`. У `Button`/`Url`/контейнеров/`Request*`/`CopyText` своей обёртки нет (либо нет `id`). Возвращает `None`, если виджета с таким `id` нет в дереве текущего окна.

6. **Один слот на окно:** ровно один `TextWidget`, один медиа-виджет (`ensure_media`), один `link_preview`, один input-слот (несколько input → авто-`CombinedInput`), одна `markup_factory`. Несколько клавиатурных виджетов объединяются контейнером (`Group`/`Row`/`Column`). Нарушение для media/link_preview → `ValueError`.

7. **При собственных виджетах переопределяй `_render_*` (`_render_text`/`_render_keyboard`/`_render_media`/`_render_style`), а не `render_*`** — иначе теряешь обработку `when` и note об ошибке (`@add_exception_note`).

8. **Состояние живёт в `manager.current_context().widget_data[id]`** — переживает перерисовки и сериализуется в FSM storage, но сбрасывается при пересоздании контекста (`RESET_STACK`, новый запуск стейта). `default`/`min_selected` НЕ задают начальный выбор автоматически (`default` «прилипает» после первого чтения).
