---
zone: 13
title: "Calendar и Time (TimeSelect): сложные виджеты выбора даты/времени и кастомизация"
source_repo: /tmp/aiogram_dialog
source_rev: "develop, 08abdf0 (2026-05-02)"
aiogram_min: ">=3.14.0"
main_files:
  - src/aiogram_dialog/widgets/kbd/calendar_kbd.py
  - src/aiogram_dialog/widgets/kbd/time.py
docs:
  - docs/widgets/keyboard/calendar/index.rst
  - docs/widgets/keyboard/calendar/example.py
  - docs/widgets/keyboard/calendar/custom.py
  - docs/widgets/keyboard/time/index.rst
tests:
  - tests/widgets/kbd/test_calendar.py
  - tests/widgets/kbd/test_time.py
example:
  - example/mega/bot_dialogs/calendar.py
status: reference
---

# Зона 13. Calendar и TimeSelect

Два «тяжёлых» клавиатурных виджета aiogram_dialog: `Calendar` (выбор даты с тремя
масштабами DAYS/MONTHS/YEARS) и `TimeSelect` (выбор часа+минуты). Оба наследуют
`Keyboard`, оба обходят стандартный механизм одной кнопки и рендерят клавиатуру
целиком, оба хранят своё состояние в `widget_data` текущего контекста диалога.

> ВАЖНО про доки. `docs/.../calendar/custom.py` и `example/mega/.../calendar.py`
> вызывают `CalendarDaysView(self._item_callback_data, self.config, ...)` —
> передают `self.config` **вторым позиционным** аргументом. В текущем коде
> (`calendar_kbd.py:187`) второй позиционный параметр `__init__` — это
> `date_text: TextWidget`, а `config` view вообще не принимает (получает его в
> `render()`). То есть `custom.py` устарел и в текущем develop **упадёт/сломает
> рендер** (передан `CalendarConfig` туда, где ждут `Text`). Mega-пример
> (`calendar.py:56-79`) использует исправленный вариант — **только**
> `self._item_callback_data` без `self.config`. Ориентируйтесь на mega-пример.

---

## 1. Calendar — общая модель

`Calendar` (`calendar_kbd.py:813`) — это «контейнер» из трёх *view*-объектов,
по одному на масштаб (`CalendarScope`). При рендере выбирается текущий scope,
берётся `offset` (опорная дата) и `config`, и управление делегируется
`view.render(config, offset, data, manager)`.

Поток данных:

```
get_scope(manager)  ->  выбор view из self.views
get_offset(manager) ->  опорная дата (если None -> сегодня, и сохраняется)
self.config.merge(_get_user_config(...)) -> итоговый CalendarConfig
view.render(config, offset, data, manager) -> list[list[InlineKeyboardButton]]
```

### 1.1. Сигнатура и параметры

```python
Calendar(
    id: str,
    on_click: OnDateSelected | WidgetEventProcessor | None = None,
    config: CalendarConfig | None = None,
    when: WhenCondition = None,
) -> None
```
`calendar_kbd.py:820`.

| Параметр   | Назначение |
|------------|------------|
| `id`       | ID виджета. Обязателен (от него строится `callback_prefix` `"{id}:"`). Должен матчить `^[a-zA-Z0-9_.]+$` (`action.py:8`) — иначе `InvalidWidgetIdError`. |
| `on_click` | Колбэк выбора **дня** (не месяца/года). Оборачивается `ensure_event_processor`, поэтому можно передать и обычную async-функцию, и `WidgetEventProcessor`. |
| `config`   | `CalendarConfig`; если `None` — берётся `CalendarConfig()` со значениями по умолчанию (`calendar_kbd.py:837`). |
| `when`     | Условие показа (как у всех `Whenable`-виджетов). При `False` `render_keyboard` вернёт `[]` (`base.py:32`). |

В `__init__` вызывается `self._init_views()` (заполняет `self.views`) и строится
словарь `self._handlers` навигационных колбэков (`calendar_kbd.py:841`).

### 1.2. Наследование и протоколы

- Базовый класс: `Keyboard` (`base.py:15`) → `Actionable, Whenable, KeyboardWidget`.
  - От `Actionable` (`action.py`): `widget_id`, `find()`, `get_widget_data()`,
    `set_widget_data()`.
  - От `Whenable`: обработка `when`.
- `on_click` типизирован протоколом `OnDateSelected` (`calendar_kbd.py:103`).

### 1.3. `OnDateSelected` — сигнатура колбэка

```python
class OnDateSelected(Protocol):
    async def __call__(
        self,
        event: ChatEvent,           # фактически CallbackQuery
        widget: ManagedCalendar,
        dialog_manager: DialogManager,
        date: date,                 # выбранная дата (datetime.date)
        /,
    ) -> Any: ...
```
`calendar_kbd.py:103`. Все 4 аргумента позиционные (`/`). `date` — это
`datetime.date` (naive, без времени и tz). `ChatEvent` — union из
`CallbackQuery | Message | ...` (`events.py:16`), но для календаря всегда
прилетает `CallbackQuery`, так что `callback.answer(...)` валиден.

Рабочий минимум (`docs/.../calendar/example.py`):

```python
async def on_date_selected(callback: CallbackQuery, widget,
                           manager: DialogManager, selected_date: date):
    await callback.answer(str(selected_date))

calendar = Calendar(id='calendar', on_click=on_date_selected)
```

---

## 2. CalendarConfig и CalendarUserConfig

### 2.1. CalendarConfig (`calendar_kbd.py:135`)

`@dataclass(frozen=True)`. Это статическая конфигурация, заданная при создании
виджета.

| Поле | Тип | Дефолт | Назначение / эффект |
|------|-----|--------|---------------------|
| `firstweekday`   | `int` | `0`  | Первый день недели (0 = понедельник, как `date.weekday()`). Влияет на выравнивание сетки дней и порядок шапки дней недели. Используется в `_render_days`/`_render_week_header`. |
| `timezone`       | `timezone` | `datetime.now().astimezone().tzinfo` | TZ для вычисления «сегодня» (`get_today`, `calendar_kbd.py:94`). На выбранную дату НЕ влияет — только подсветка today. ВНИМАНИЕ: дефолт вычисляется один раз при импорте модуля (см. подводные камни). |
| `min_date`       | `date` | `date(1900,1,1)`   | Нижняя граница выбора. Дни/месяцы/годы ниже неё рендерятся `empty_button()` и пэйджер блокируется. |
| `max_date`       | `date` | `date(2100,12,31)` | Верхняя граница выбора. |
| `month_columns`  | `int` | `3`  | Кол-во колонок в сетке месяцев (scope MONTHS). 12 месяцев / `month_columns` строк. |
| `years_per_page` | `int` | `20` | Сколько лет на странице scope YEARS; также шаг перелистывания страниц лет и шаг `±YY`. |
| `years_columns`  | `int` | `5`  | Кол-во колонок в сетке лет. |

Метод `merge(other: CalendarUserConfig) -> CalendarConfig` (`calendar_kbd.py:145`)
— накладывает пер-пользовательский конфиг поверх базового (через `_coalesce`:
берёт значение из `other`, если оно не `None`, иначе из базового).

### 2.2. CalendarUserConfig (`calendar_kbd.py:115`)

`@dataclass(frozen=True)`. Те же поля, но **все `Optional` и по умолчанию `None`**.
Возвращается из `Calendar._get_user_config(...)` и мёржится в итоговый
`CalendarConfig` на каждом рендере. Позволяет менять конфиг динамически
(например, `min_date` в зависимости от пользователя/данных).

```python
class CustomCalendar(Calendar):
    async def _get_user_config(self, data, manager) -> CalendarUserConfig:
        return CalendarUserConfig(firstweekday=7, min_date=date.today())
```

`firstweekday=7` валиден: в `_render_week_header` берётся `week_day % 7 + 1`
(`calendar_kbd.py:300`), т.е. 7 эквивалентно воскресенью-как-первому-дню — именно
так в `docs/.../custom.py` делают «неделя с воскресенья». В `_render_days`
смещение считается через `start_date.weekday() - config.firstweekday` с
коррекцией `+= 7` при отрицательном (`calendar_kbd.py:265`), так что `firstweekday`
в диапазоне 0..7 работает корректно.

---

## 3. CalendarScope и переключение масштаба

`CalendarScope(Enum)` (`calendar_kbd.py:67`): `DAYS`, `MONTHS`, `YEARS`.

Текущий scope хранится в `widget_data` под ключом `current_scope` (строка),
опорная дата — под `current_offset` (ISO-строка). Структура — `CalendarData`
(`TypedDict`, `calendar_kbd.py:98`).

Геттеры/сеттеры на самом `Calendar`:

| Метод | Строка | Поведение |
|-------|--------|-----------|
| `get_scope(manager) -> CalendarScope` | `:896` | Читает `current_scope`; если пусто или невалидно — `DAYS` (тихо, с TODO-логом). |
| `get_offset(manager) -> date \| None`  | `:907` | Читает `current_offset` через `date.fromisoformat`; `None`, если ещё не задан. |
| `set_offset(date, manager)`            | `:914` | Пишет `current_offset` как `isoformat()`. |
| `set_scope(CalendarScope, manager)`    | `:919` | Пишет `current_scope` как `.value`. |

Переключение масштабов происходит через навигационные кнопки (zoom-out 🔍 и
заголовки), их callback'и обрабатываются в `_process_item_callback`
(`calendar_kbd.py:1006`):

| callback_data | Константа | Handler | Эффект |
|---------------|-----------|---------|--------|
| `M`   | `CALLBACK_SCOPE_MONTHS` | `_handle_scope_months` | scope → MONTHS |
| `Y`   | `CALLBACK_SCOPE_YEARS`  | `_handle_scope_years`  | scope → YEARS |
| `+`/`-`   | `CALLBACK_NEXT/PREV_MONTH` | `_handle_next/prev_month` | offset ±1 месяц |
| `+Y`/`-Y` | `CALLBACK_NEXT/PREV_YEAR`  | `_handle_next/prev_year`  | offset ±1 год |
| `+YY`/`-YY` | `CALLBACK_NEXT/PREV_YEARS_PAGE` | `_handle_next/prev_years_page` | offset ± `years_per_page` лет |
| `MONTH<n>` | `CALLBACK_PREFIX_MONTH` | `_handle_click_month` | offset → выбранный месяц, scope → DAYS |
| `YEAR<n>`  | `CALLBACK_PREFIX_YEAR`  | `_handle_click_year`  | offset → выбранный год, scope → MONTHS |
| иное (raw int) | — | `_handle_click_date` | вызов `on_click` с выбранной датой |

Логика выбора handler'а: точное совпадение в `self._handlers` → префикс `MONTH`
→ префикс `YEAR` → иначе трактуется как «кликнут день» (raw-секунды от EPOCH).

Кодирование даты: `raw_from_date(d)` = секунды между `d` и `EPOCH=1970-01-01`
(`calendar_kbd.py:73`), обратно — `date_from_raw` (`:78`). День кодируется в
callback_data как это число секунд (компактнее, чем ISO).

---

## 4. View-классы (рендер по масштабам)

Все три реализуют протокол `CalendarScopeView` (`calendar_kbd.py:158`):

```python
async def render(
    self, config: CalendarConfig, offset: date,
    data: dict, manager: DialogManager,
) -> list[list[InlineKeyboardButton]]: ...
```
`offset` — опорная дата, `data` — данные из getter окна, `config` — уже
смёрженный итоговый конфиг.

`callback_generator: CallbackGenerator = Callable[[str], str]` — функция,
строящая callback_data кнопки из «полезной нагрузки». На практике это
`Calendar._item_callback_data` (`base.py:58`), оборачивающее значение в
`"{id}:{value}"`.

### 4.1. CalendarDaysView (`calendar_kbd.py:186`)

Полная сигнатура `__init__`:

```python
CalendarDaysView(
    callback_generator: CallbackGenerator,
    date_text: TextWidget        = DATE_TEXT,       # "{date:%d}"
    today_text: TextWidget       = TODAY_TEXT,      # "[ {date:%d} ]"
    weekday_text: TextWidget     = WEEK_DAY_TEXT,   # "{date:%a}"
    header_text: TextWidget      = DAYS_HEADER_TEXT,# "🗓 {date:%B %Y}"
    zoom_out_text: TextWidget    = ZOOM_OUT_TEXT,   # "🔍"
    next_month_text: TextWidget  = NEXT_MONTH_TEXT, # "{date:%B %Y} >>"
    prev_month_text: TextWidget  = PREV_MONTH_TEXT, # "<< {date:%B %Y}"
    date_style: StyleWidget      = EMPTY_STYLE,
    today_style, weekday_style, header_style,
    zoom_out_style, next_month_style, prev_month_style: StyleWidget = EMPTY_STYLE,
)
```

`render()` собирает: `[header]` (заголовок-кнопка с zoom→MONTHS),
`[week_header]` (7 кнопок-«заглушек» с пустым callback), строки дней,
`[pager]` (`<<`, 🔍, `>>`). Заметки:
- Сетка дней выравнивается по неделям относительно `firstweekday`; дни вне
  `[min_date, max_date]` или вне месяца — `empty_button()`.
- Today определяется через `get_today(config.timezone)`; для него используется
  `today_text`/`today_style` вместо `date_text`.
- Пэйджер целиком исчезает (`return []`), если и предыдущий, и следующий месяц
  выходят за границы (`calendar_kbd.py:329`).
- В data для текста кнопки дня передаётся `{"date": <date>, "data": <getter-data>}`
  (`calendar_kbd.py:230`) — отсюда `{date:%d}` и доступ к `data` в кастомных Text.

### 4.2. CalendarMonthView (`calendar_kbd.py:432`)

```python
CalendarMonthView(
    callback_generator,
    month_text       = MONTH_TEXT,        # "{date:%B}"
    this_month_text  = THIS_MONTH_TEXT,   # "[ {date:%B} ]"
    header_text      = MONTHS_HEADER_TEXT,# "🗓 {date:%Y}"
    zoom_out_text    = ZOOM_OUT_TEXT,
    next_year_text   = NEXT_YEAR_TEXT,    # "{date:%Y} >>"
    prev_year_text   = PREV_YEAR_TEXT,    # "<< {date:%Y}"
    *_style: StyleWidget = EMPTY_STYLE,
)
```
12 кнопок в сетке `month_columns`. Заголовок переключает scope→YEARS, кнопка
месяца кодируется как `MONTH<n>` и ведёт в DAYS этого месяца. Месяцы вне
`[min_date, max_date]` — `empty_button()` (`_is_month_allowed`, `:546`). В data
кнопки: `{"month": n, "date": BEARING_DATE.replace(month=n), "data": ...}`, где
`BEARING_DATE = date(2018,1,1)` — «несущая» дата, чтобы `{date:%B}` дал имя
месяца (`calendar_kbd.py:60`).

### 4.3. CalendarYearsView (`calendar_kbd.py:647`)

```python
CalendarYearsView(
    callback_generator,
    year_text       = YEAR_TEXT,            # "{date:%Y}"
    this_year_text  = THIS_YEAR_TEXT,       # "[ {date:%Y} ]"
    next_page_text  = NEXT_YEARS_PAGE_TEXT, # "{date:%Y} >>"
    prev_page_text  = PREV_YEARS_PAGE_TEXT, # "<< {date:%Y}"
    *_style: StyleWidget = EMPTY_STYLE,
)
```
`years_per_page` лет, сетка `years_columns`. Кнопка года → `YEAR<n>`, ведёт в
MONTHS. Пэйджер `±years_per_page` (исчезает, если обе стрелки — заглушки).
Заголовка как такового нет — только сетка + пэйджер.

> Все три view принимают `callback_generator` первым позиционным; остальное —
> keyword. Дефолтные `*_TEXT` — это `Format(...)`-объекты, объявленные в начале
> модуля (`calendar_kbd.py:42-58`), их можно переиспользовать и комбинировать
> (`Const(...) | DATE_TEXT`, `Month() + " >>"`).

---

## 5. Кастомизация Calendar

Два уровня (см. `docs/.../calendar/index.rst`):

1. **Лёгкий** — передать `CalendarConfig` в `__init__` (границы дат, колонки,
   firstweekday, tz).
2. **Глубокий** — наследовать `Calendar` и переопределить:
   - `_init_views()` (`calendar_kbd.py:852`) → вернуть свой
     `dict[CalendarScope, CalendarScopeView]`. Можно подменить `Text`/`Style`
     в стандартных view либо подставить полностью свой класс, реализующий
     `CalendarScopeView`.
   - `_get_user_config()` (`calendar_kbd.py:866`) → динамический
     `CalendarUserConfig` (зависящий от `data`/`manager`).

Рабочий пример локализации (из `example/mega/bot_dialogs/calendar.py`, через
`babel`):

```python
from babel.dates import get_day_names, get_month_names
from aiogram_dialog.widgets.text import Text, Const, Format
from aiogram_dialog.widgets.kbd.calendar_kbd import (
    DATE_TEXT, TODAY_TEXT, CalendarDaysView, CalendarMonthView,
    CalendarYearsView, CalendarScopeView,
)

class WeekDay(Text):
    async def _render_text(self, data, manager):
        d: date = data["date"]
        loc = manager.event.from_user.language_code
        return get_day_names("short", context="stand-alone", locale=loc)[d.weekday()].title()

class Month(Text):
    async def _render_text(self, data, manager):
        d: date = data["date"]
        loc = manager.event.from_user.language_code
        return get_month_names("wide", context="stand-alone", locale=loc)[d.month].title()

def is_date_selected(data, widget, manager) -> bool:
    return data["date"].isoformat() in manager.dialog_data.get("selected_dates", [])

class CustomCalendar(Calendar):
    def _init_views(self) -> dict[CalendarScope, CalendarScopeView]:
        return {
            CalendarScope.DAYS: CalendarDaysView(
                self._item_callback_data,                       # ТОЛЬКО callback_gen
                date_text=Const("🔴", when=is_date_selected) | DATE_TEXT,
                today_text=Const("⭕", when=is_date_selected) | TODAY_TEXT,
                header_text="~~~~~ " + Month() + " ~~~~~",
                weekday_text=WeekDay(),
                next_month_text=Month() + " >>",
                prev_month_text="<< " + Month(),
                date_style=Style(ButtonStyle.SUCCESS, when=is_date_selected),
                today_style=Style(ButtonStyle.SUCCESS, when=is_date_selected),
            ),
            CalendarScope.MONTHS: CalendarMonthView(
                self._item_callback_data,
                month_text=Month(),
                header_text="~~~~~ " + Format("{date:%Y}") + " ~~~~~",
                this_month_text="[" + Month() + "]",
            ),
            CalendarScope.YEARS: CalendarYearsView(self._item_callback_data),
        }
```

> Локализация дат целиком на стороне пользователя — библиотека НЕ переводит
> `%B`/`%a` (это зависит от locale процесса). В `index.rst` это явно оговорено
> (note). Для перевода — свой `Text` (как `Month`/`WeekDay` выше) поверх `babel`.

Доступные в data Text-виджета кнопок поля: `date` (опорная дата кнопки), `data`
(данные из getter окна), плюс `month`/`year`/`week_day` в зависимости от
конкретной кнопки (см. словари в `_render_*`).

`Style` (`style/base.py:79`) — задаёт `ButtonStyle` (aiogram 3.14+,
`enum ButtonStyle`) и/или `emoji_id`; поддерживает `when` и `|` (Or). Стиль
применяется к `InlineKeyboardButton(style=..., icon_custom_emoji_id=...)`.

---

## 6. ManagedCalendar (`calendar_kbd.py:1025`)

`ManagedWidget[Calendar]` — обёртка, которую получают колбэки и которую можно
достать через `manager.find(id)`. Делегирует на `Calendar` с текущим `manager`:

| Метод | Возврат | Делегирует |
|-------|---------|------------|
| `get_scope()`        | `CalendarScope` | `widget.get_scope(manager)` |
| `get_offset()`       | `date \| None`  | `widget.get_offset(manager)` |
| `set_offset(date)`   | `None`          | `widget.set_offset(...)` |
| `set_scope(scope)`   | `None`          | `widget.set_scope(...)` |

`ManagedWidget.__getattr__` (`managed.py:14`) проксирует прочие атрибуты на сам
виджет, так что `managed.config` и т.п. доступны.

Управление извне (например, программно открыть нужный месяц в `on_start`/getter):

```python
async def open_today(_, dialog: Dialog, manager: DialogManager):
    cal: ManagedCalendar = manager.find("calendar")
    cal.set_offset(date.today().replace(day=1))
    cal.set_scope(CalendarScope.DAYS)
```

---

## 7. TimeSelect (`time.py:53`)

Отдельный виджет (НЕ часть Calendar). Доки: `docs/widgets/keyboard/time/index.rst`.
Рендерит два блока: «Hour» (0..23) и «Minute» (0..59 с шагом `minute_precision`),
сохраняет выбор в `widget_data` как `[hour, minute]`.

### 7.1. Сигнатура

```python
TimeSelect(
    id: str,
    when: WhenCondition = None,
    hour_header: TextWidget          = HOUR_TEXT,            # Const("Hour")
    minute_header: TextWidget        = MINUTE_TEXT,          # Const("Minute")
    button_text: TextWidget          = BUTTON_TEXT,          # "{value}"
    button_selected_text: TextWidget = BUTTON_SELECTED_TEXT, # "[{value}]"
    header_style: StyleWidget          = EMPTY_STYLE,
    button_style: StyleWidget          = EMPTY_STYLE,
    button_selected_style: StyleWidget = EMPTY_STYLE,
    on_hour_click: OnClickVariant       = None,  # OnClick | WidgetEventProcessor | None
    on_minute_click: OnClickVariant     = None,
    on_value_changed: OnValueChangedVariant = None,
    hour_width: int       = 6,   # колонок в строке часов
    minute_precision: int = 5,   # шаг минут
    minute_width: int     = 6,   # колонок в строке минут
)
```
`time.py:54`.

> ВНИМАНИЕ к порядку аргументов: второй позиционный — `when`, а НЕ `on_click`
> (в отличие от большинства kbd-виджетов). Все колбэки — только по имени.

### 7.2. Колбэки

- `OnClick` (`time.py:19`): `(event, widget: ManagedTimeSelect, manager, value: int)`
  — `value` это число часа или минуты в зависимости от того, кликнут час/минута.
  Используется и для `on_hour_click`, и для `on_minute_click`.
- `OnValueChanged` (`time.py:31`): `(event, widget, manager, value: time | None)`
  — вызывается после любого клика и при `set_value`. `value` — `datetime.time`
  или `None`, если ещё не выбраны оба компонента.

Последовательность при клике (`_process_item_callback`, `time.py:215`):
1. Парсит `h<n>`/`m<n>`; обновляет соответствующий компонент.
2. Вызывает `on_hour_click`/`on_minute_click` с `int`.
3. Пишет `[hour, minute]` в `widget_data`.
4. Вызывает `on_value_changed` с `time | None`.
5. Неизвестный префикс → `ValueError`.

### 7.3. Состояние и геттеры

- Хранилище: `widget_data = [hour, minute]` (или `(None, None)` по умолчанию).
- `_value_from_raw((h, m)) -> time | None` (`time.py:87`): `None`, если хоть один
  компонент `None`; иначе `time(h, m)`. То есть пока выбран только час — итоговое
  значение всё ещё `None`.
- `get_value(manager) -> time | None` (`time.py:95`).
- `set_value(event, manager, value: time | None)` (`time.py:99`): пишет состояние
  и вызывает `on_value_changed`. На самом виджете требует `event` явно.

### 7.4. ManagedTimeSelect (`time.py:261`)

`ManagedWidget[TimeSelect]`:
- `get_value() -> time | None` — делегирует.
- `async set_value(value: time | None)` — берёт `event` из `manager.event`.

Пример (mega, `calendar.py:164`):
```python
TimeSelect("time", button_selected_style=Style(style="success"))
```
Клавиатура из 8 строк: 1 (заголовок Hour) + 4 (24/6) + 1 (заголовок Minute)
+ 2 (12 значений минут при precision=5, width=6) — совпадает с `test_time.py`
(`len(keyboard) == 8`).

---

## 8. Связи с остальной библиотекой

- Размещаются как обычные `Keyboard`-виджеты внутри `Window`; их можно
  оборачивать в `Group/Column/Row`, но обычно ставят как самостоятельный блок
  (они сами генерируют многострочную клавиатуру).
- `_item_callback_data`/`_own_callback_data` и `process_callback` — из `Keyboard`
  (`base.py`). Маршрутизация по префиксу `"{id}:"` стандартная.
- Текстовые подписи кнопок — это полноценные `Text`-виджеты
  (`Const`/`Format`/кастомные), поддерживают `when`, `+` (`Multi`), `|` (`Or`).
- Стили — `StyleWidget` (`Style`/`StyleCase`/`EMPTY_STYLE`), требуют aiogram
  >=3.14 (`ButtonStyle`, `style=`/`icon_custom_emoji_id=` у `InlineKeyboardButton`).
- Состояние живёт в `manager.current_context().widget_data[id]` — то есть
  привязано к стеку/контексту диалога и переживает рендеры, но сбрасывается при
  пересоздании контекста (новый запуск стейта).
- `manager.find(id)` возвращает `ManagedCalendar`/`ManagedTimeSelect`.

---

## 9. Подводные камни и краевые случаи

| Тема | Деталь |
|------|--------|
| **Устаревший `custom.py`** | `docs/.../calendar/custom.py` передаёт `self.config` 2-м позиционным во view — в текущем коде сигнатуры это сломает. Используйте mega-вариант (только `self._item_callback_data`). |
| **`timezone` дефолт вычисляется на импорте** | `CalendarConfig.timezone = datetime.now().astimezone().tzinfo` (`calendar_kbd.py:138`) — это значение поля по умолчанию, зафиксированное при импорте модуля. В долгоживущем процессе при смене летнего/зимнего времени оно не обновится. Для серверов задавайте `timezone` явно (`timezone.utc` или нужная зона). |
| **tz влияет только на "today"** | Выбранная дата — naive `datetime.date`, без tz. `timezone` нужна лишь для подсветки сегодняшнего дня/месяца/года. Не путайте с tz пользователя для бизнес-логики. |
| **`on_click` только для дней** | Клик по месяцу/году НЕ вызывает `on_click` — он лишь меняет scope/offset. Перехватить выбор месяца/года стандартно нельзя без переопределения handler'ов. |
| **min/max — это `date`, не диапазон scope** | `min_date`/`max_date` ограничивают и дни, и месяцы (`_is_month_allowed`), и годы (`_is_year_allowed`). Месяц «частично доступен», если хотя бы один его день в диапазоне. Кнопки вне диапазона — пустые (callback_data `""`, кликабельны, но ничего не делают). |
| **Пустые кнопки** | `empty_button()` = текст `" "`, `callback_data=""` (`calendar_kbd.py:63`). Telegram требует непустой callback_data — здесь пустая строка; кнопки-заглушки шапки недели тоже с `callback_data=""`. На практике работает, но клики по ним игнорируются библиотекой. |
| **offset инициализируется лениво** | Если `current_offset` не задан, при первом рендере ставится `today` и сохраняется (`calendar_kbd.py:891`). До первого рендера `get_offset()` вернёт `None`. |
| **Невалидный scope → DAYS** | `get_scope` молча падает в `DAYS` при битом значении (есть `# LOG` TODO, `calendar_kbd.py:904`). |
| **`set_scope`/`set_offset` сами не перерисовывают** | Они только меняют `widget_data`. Перерисовка произойдёт штатно при обработке апдейта; в кастомных потоках может понадобиться `manager.show()`/`update()`. |
| **`years_per_page` ≠ `years_columns*rows` строго** | Сетка лет идёт `range(0, years_per_page, years_columns)` — если `years_per_page` не кратно `years_columns`, последняя строка будет содержать лишние года за `years_per_page` (цикл по column фиксированной ширины). Подбирайте кратные значения (дефолт 20/5 кратен). |
| **TimeSelect: порядок аргументов** | 2-й позиционный — `when`, не колбэк. Передавайте колбэки только по имени. |
| **TimeSelect: `value` = None пока не выбраны оба** | `get_value`/`on_value_changed` вернут `None`, если выбран только час или только минута. Учитывайте при валидации. |
| **TimeSelect: нет масштабов/секунд** | Только часы 0..23 и минуты с фиксированным шагом; секунд нет, AM/PM нет. Для нестандартного шага — `minute_precision`. |
| **Кастомные view-классы** | Свой класс должен реализовать `async render(config, offset, data, manager)` и сам строить callback_data через переданный `callback_generator`, иначе клики не замаршрутизируются (handler'ы `Calendar` опираются на конкретные константы/префиксы `M/Y/+/-/MONTH<n>/YEAR<n>/raw-int`). |
| **Naming в доках** | В `time/index.rst` колбэк `OnClick.counter` назван `counter` (копипаст из Counter) — это просто имя параметра в Protocol, на поведение не влияет. |
