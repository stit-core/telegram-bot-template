---
title: "Текстовые виджеты aiogram_dialog: Const, Format, Multi, Case, Or, Jinja, List, Progress, ScrollingText"
zone: 08
area: widgets/text
source_repo: aiogram_dialog (develop, commit 08abdf0, 2026-05-02)
aiogram: ">=3.14.0"
package_path: src/aiogram_dialog/widgets/text/
public_import: from aiogram_dialog.widgets.text import ...
tags: [text, render_text, when, whenable, scroll, jinja, format, preview]
updated: 2026-06-07
---

# Зона 08. Текстовые виджеты (`aiogram_dialog.widgets.text`)

Группа виджетов, отвечающих за рендеринг **текста сообщения** окна (`Window`/`Dialog`).
Все они — наследники базового класса `Text` и реализуют протокол `TextWidget`.
Текст одного окна — это **ровно один** `TextWidget` (обычно `Multi`/`Const`/`Format`/`Jinja`),
который Window рендерит в строку для поля `text` отправляемого сообщения.

> Публичный API экспортируется из `aiogram_dialog/widgets/text/__init__.py`:
> `Case, Const, Format, Jinja, List, Multi, Progress, ScrollingText, Text, setup_jinja`.
> **`Or` НЕ экспортируется** (создаётся только оператором `|`), хотя определён в `base.py`.

## Карта файлов

| Класс / функция | Файл | Примечание |
|---|---|---|
| `Text` (база), `Const`, `Multi`, `Or` | `base.py` | внимание: `Const`, `Multi`, `Or` лежат в `base.py`, а не в отдельных файлах |
| `Format`, `_FormatDataStub` | `format.py` | |
| `Case` | `multi.py` | **не в `case.py`!** Файла `case.py` в `widgets/text/` нет |
| `Jinja`, `setup_jinja`, `_create_env`, `default_env`, `StubLoader` | `jinja.py` | |
| `List` | `list.py` | наследует `BaseScroll` |
| `Progress` | `progress.py` | |
| `ScrollingText` | `scrolling_text.py` | наследует `BaseScroll` |

Связанные модули (общие):
- `widgets/common/when.py` — `Whenable`, `WhenCondition`, `Predicate`, `true_condition`.
- `widgets/common/case.py` — `Selector`, `new_case_field`, `new_magic_selector`.
- `widgets/common/items.py` — `ItemsGetterVariant`, `get_items_getter`.
- `widgets/common/scroll.py` — `BaseScroll`, `Scroll`, `ManagedScroll`, `OnPageChangedVariants`, `sync_scroll`.
- `api/internal/widgets.py:41` — протокол `TextWidget`.
- `utils.py:230` — декоратор `add_exception_note`.

---

## 1. Базовый класс `Text`

`src/aiogram_dialog/widgets/text/base.py:14`

```python
class Text(Whenable, BaseWidget, TextWidget):
    def __init__(self, when: WhenCondition = None): ...

    @add_exception_note
    async def render_text(self, data: dict, manager: DialogManager) -> str: ...

    @abstractmethod
    async def _render_text(self, data, manager: DialogManager) -> str: ...
```

### MRO и базы
- `Whenable` (`widgets/common/when.py:56`) — даёт параметр `when=` и метод `is_(data, manager)`.
- `BaseWidget` (`widgets/common/base.py`) — `find(widget_id)` (по умолчанию `None`, т.к. у `Text` нет `id`).
- `TextWidget` (`api/internal/widgets.py:41`) — Protocol с `render_text`.

### `render_text(data, manager) -> str` — `base.py:18`
Публичная точка входа. Логика:
```python
if not self.is_(data, manager):   # проверка when-условия
    return ""                     # скрытый виджет → пустая строка
return await self._render_text(data, manager)
```
- Декорирован `@add_exception_note` (`utils.py:230`): на Python ≥ 3.11 при любом исключении
  добавляет к нему note `at <repr(self)>` через `e.add_note(...)` — помогает локализовать упавший
  виджет в дереве. На 3.10 и ниже — no-op (просто пробрасывает).
- **Возврат**: уже готовая строка. Если `when` не прошёл — `""` (пустая строка, не `None`).

### `_render_text(data, manager) -> str` — `base.py:32`
Абстрактный. **Именно его переопределяют** при создании собственных текстовых виджетов —
тогда обработка `when` остаётся в базовом `render_text`. Вызывается только если виджет не скрыт.

### `data` — что внутри
`data` — это словарь, собираемый Window/Dialog перед рендером
(`window.py:113 load_data` → `dialog.py:115 load_data` → `manager.load_data()` `manager/manager.py:130`).
Гарантированно содержит спец-ключи **плюс** всё, что вернул `getter`:

| Ключ | Источник | `manager.py` |
|---|---|---|
| `dialog_data` | `context.dialog_data` (мутабельный стейт текущего диалога) | `:137` |
| `start_data` | `context.start_data` (данные, переданные в `dialog.start(..., data=)`) | `:138` |
| `middleware_data` | весь middleware-словарь aiogram (`bot`, `event_*`, `state`, DI…) | `:139` |
| `event` | текущий `ChatEvent` (Message/CallbackQuery/…) | `:140` |
| `**data` | результат `getter(**middleware_data)` — перекрывает спец-ключи при совпадении имён | `:141` |

> Важно: ключи `getter`'а раскрываются **поверх** спец-ключей (`**data` в конце), поэтому
> getter может затереть `dialog_data`/`event`/… если вернёт одноимённый ключ. Обычно не нужно.

### Операторы (DSL композиции)

| Оператор | Метод | Результат |
|---|---|---|
| `text + other` | `__add__` `base.py:41` | `Multi(self, other, sep="")`; `str` оборачивается в `Const`; если `other` — `Multi`, возвращает `NotImplemented` (диспетчеризуется в `Multi.__radd__`) |
| `other + text` | `__radd__` `base.py:48` | `Multi(other, self, sep="")` |
| `text \| other` | `__or__` `base.py:53` | `Or(self, other)`; для `Or`-операнда → `NotImplemented` (→ `Or.__ror__`) |
| `other \| text` | `__ror__` `base.py:60` | `Or(other, self)` |

`find(widget_id)` `base.py:65` — переопределён только ради сужения типа возврата к `TextWidget | None`.

---

## 2. `Const` — статический текст

`src/aiogram_dialog/widgets/text/base.py:70`

```python
class Const(Text):
    def __init__(self, text: str, when: WhenCondition = None): ...
    async def _render_text(self, data, manager) -> str:
        return self.text
```
- Возвращает строку **без изменений**. Никакого `.format`, фигурные скобки `{}` не интерпретируются.
- Используется как «обёртка» для `str` во всех операторах (`+`, `|`).
- Пример: `Const("Привет!")`. Со скрытием: `Const("Только админу", when="is_admin")`.

---

## 3. `Format` — подстановка `str.format_map`

`src/aiogram_dialog/widgets/text/format.py:29`

```python
class Format(Text):
    def __init__(self, text: str, when: WhenCondition = None): ...
    async def _render_text(self, data, manager) -> str:
        if manager.is_preview():
            return self.text.format_map(_FormatDataStub(data=data))
        return self.text.format_map(data)
```

- Использует стандартный механизм **`str.format_map(data)`** — поддерживает весь синтаксис формата:
  - доступ к ключам: `{name}`;
  - вложенный доступ через `[]`: `{dialog_data[project][name]}` (см. `format/example.py`);
  - атрибуты: `{user.name}`;
  - спецификаторы: `{price:.2f}`, `{n:>5}`, `{pct:.0%}`.
- **Доступные ключи** — это весь словарь `data` (см. §1): результат `getter` + спец-ключи
  (`dialog_data`, `start_data`, `middleware_data`, `event`).
- **Подводный камень — `KeyError`**: если в шаблоне есть `{missing}`, а ключа в `data` нет —
  будет `KeyError` при рендере (и весь показ окна упадёт). Нет «тихого» значения по умолчанию.
  - `{a[b]}` при отсутствии `a` → `KeyError`; при отсутствии вложенного ключа в существующем
    словаре `a` → тоже `KeyError`/`TypeError`.
  - Литеральные `{`/`}` в тексте экранируются удвоением: `{{` и `}}`.
- **Preview-режим** (`manager.is_preview()` == True, только в инструменте превью `tools/preview.py`):
  вместо `data` подставляется `_FormatDataStub` (`format.py:6`), который для отсутствующих ключей
  возвращает не значение, а **placeholder-строку** вида `{name}`/`{dialog_data[project]}` —
  чтобы превью не падало на незаполненных данных. В реальном боте `is_preview()` всегда `False`
  (`manager/manager.py:144`, `sub_manager.py:67`).

---

## 4. `Multi` — конкатенация нескольких текстов

`src/aiogram_dialog/widgets/text/base.py:81`

```python
class Multi(Text):
    def __init__(self, *texts: TextWidget, sep="\n", when: WhenCondition = None): ...
    async def _render_text(self, data, manager) -> str:
        texts = [await t.render_text(data, manager) for t in self.texts]
        return self.sep.join(filter(None, texts))
```

- Рендерит **все** вложенные тексты и склеивает их через `sep` (по умолчанию `"\n"`).
- **`filter(None, texts)`** отбрасывает **пустые** строки → разделители не «слипаются»
  вокруг скрытых (`when=False`) или пустых элементов. То есть скрытый `Const` не оставит
  лишнего `\n`.
- `find()` `base.py:122` — рекурсивно обходит `self.texts`.
- Операторы оптимизируют вложенность:
  - `__iadd__` (`+=`) `base.py:98` — мутирует: добавляет в кортеж `self.texts` (in-place).
  - `__add__`/`__radd__` `base.py:104/113` — если у `Multi` нет своего `when`
    (`self.condition is true_condition`) **и** `sep == ""`, «расплющивает» в один `Multi` без
    лишней вложенности; иначе оборачивает.
- Эквивалентность: `a + b` (оба `Text`) ≡ `Multi(a, b, sep="")` — конкатенация **без** разделителя.
  А `Multi(a, b)` по умолчанию склеивает через перевод строки.

Примеры (`docs/widgets/text/multi/example.py`):
```python
Multi(Const("Hello!"), Const("And goodbye!"), sep=" ")        # "Hello! And goodbye!"
Multi(Format("Hello, {name}"), Const("and goodbye {name}!"), sep=", ")
Multi(Multi(Const("01"), Const("02"), Const("2003"), sep="."),
      Multi(Const("04"), Const("05"), Const("06"), sep=":"), sep="T")  # "01.02.2003T04:05:06"
```
> Внимание в примере: `Const("and goodbye {name}!")` — это `Const`, поэтому `{name}` останется
> литеральным текстом, а не подставится. Подстановка только в `Format`.

---

## 5. `Or` — первый непустой текст (через оператор `|`)

`src/aiogram_dialog/widgets/text/base.py:129`

```python
class Or(Text):
    def __init__(self, *texts: TextWidget): ...   # НЕТ параметра when!
    async def _render_text(self, data, manager) -> str:
        for text in self.texts:
            res = await text.render_text(data, manager)
            if res:
                return res
        return ""
```

- Возвращает результат **первого** вложенного текста, чей рендер дал непустую строку.
- Удобно для fallback: `Format("{name}", when="name") | Const("Аноним")`.
  Здесь, если `when` не прошёл или строка пуста — берётся следующий вариант.
- Создаётся только оператором `|` (`Text.__or__`); конструктор без `when=`.
- `__ior__`/`__or__`/`__ror__` `base.py:143/149/155` — расплющивают цепочки `Or` без вложенности.
- Тест `test_base.py:50` подтверждает работу с `when`-условиями в цепочке `|`.

---

## 6. `Case` — выбор текста по селектору

`src/aiogram_dialog/widgets/text/multi.py:16` (файл `multi.py`, не `case.py`!)

```python
class Case(Text):
    def __init__(self, texts: dict[Any, TextWidget],
                 selector: str | Selector["Case"] | MagicFilter,
                 when: WhenCondition = None): ...
    async def _render_text(self, data, manager) -> str:
        selection = self.selector(data, self, manager)
        if selection not in self.texts:
            if self._has_default:
                selection = ...
            elif manager.is_preview():
                selection = next(iter(self.texts))
        return await self.texts[selection].render_text(data, manager)
```

### Параметры
- `texts: dict[Any, TextWidget]` — словарь «значение селектора → текст».
  Ключи могут быть любого hashable-типа (`"red"`, `0/1`, `True/False`).
- `selector` — как получить значение для выбора:
  | Тип `selector` | Обёртка | Поведение |
  |---|---|---|
  | `str` | `new_case_field(s)` (`common/case.py:12`) | `data.get(s)` — значение по ключу из `data` |
  | `MagicFilter` (`F[...]`) | `new_magic_selector(f)` (`common/case.py:21`) | `f.resolve(data)` |
  | `Selector` (callable) | как есть | вызывается `selector(data, self, manager)` |
- `Selector` = `Callable[[dict, T, DialogManager], Hashable]` (`common/case.py:9`).

### Дефолтная ветка `...` (Ellipsis)
- Ключ `...` в `texts` задаёт ветку по умолчанию (`self._has_default = ... in self.texts`,
  `multi.py:25`). Если значение селектора не найдено среди ключей — берётся `texts[...]`.
- Если дефолта нет и значение не найдено:
  - в **preview** — берётся первый ключ (`next(iter(self.texts))`), чтобы не падать;
  - в **проде** — `KeyError` на `self.texts[selection]` (значение не в словаре и дефолта нет).
- `find()` `multi.py:44` — обходит `self.texts.values()`.

### Подводные камни
- `str`-селектор использует `data.get(field)` → отсутствующий ключ даёт `None`;
  если `None` нет среди ключей и нет `...`-дефолта → `KeyError` в проде.
- При `MagicFilter` с булевым результатом ключи должны быть именно `True`/`False`
  (не `1`/`0` — они равны по `==`, но как ключи dict `True==1`, так что осторожно со смешением).
- Тип ключа должен совпадать с типом результата селектора (`"42"` ≠ `42`).

Примеры (`docs/widgets/text/case/example.py`):
```python
Case({"red": Const("Square"), ...: Const("Unknown creature")}, selector="color")
Case({0: Format("{number} is even!"), 1: Const("It is Odd")}, selector=parity_selector)
Case({True: Const("Great job!"), False: Const("Try again..")},
     selector=F["dialog_data"]["user"]["test_result"])
```
Тест `test_case.py`: `Case({0:..., 1:...}, selector=F["number"] % 2)` → magic-filter как селектор.

---

## 7. `Jinja` — рендер через Jinja2 (HTML)

`src/aiogram_dialog/widgets/text/jinja.py:23`

```python
class Jinja(Text):
    def __init__(self, text: str, when: WhenCondition = None): ...
    async def _render_text(self, data, manager) -> str:
        if JINJA_ENV_FIELD in manager.middleware_data:
            env = manager.middleware_data[JINJA_ENV_FIELD]
        else:
            bot = manager.middleware_data.get("bot")
            env = getattr(bot, JINJA_ENV_FIELD, default_env)
        template = env.get_template(self.template_text)
        if env.is_async:
            return await template.render_async(data)
        return template.render(data)
```

- `text` трактуется как **сам шаблон** (не имя файла): `StubLoader` (`jinja.py:44`) возвращает
  переданную строку как исходник шаблона. `env.get_template(self.template_text)` кэширует
  шаблоны по тексту (стандартный LRU-кэш Jinja).
- В шаблон передаётся **весь `data`** (см. §1) как контекст: `{{ title }}`, `{% for x in items %}`,
  `{{ dialog_data['user']['weight'] }}`, фильтры `{{ animal|capitalize }}` и т.д.

### Окружение (Environment) и `setup_jinja`
`JINJA_ENV_FIELD = "DialogsJinjaEnvironment"` (`jinja.py:14`). Источник окружения (приоритет):
1. `manager.middleware_data["DialogsJinjaEnvironment"]` — если положено через middleware/DI;
2. атрибут на `Bot` с тем же именем (для **deprecated** `setup_jinja(bot, ...)`);
3. `default_env` (`jinja.py:83`) — глобальное окружение по умолчанию.

`setup_jinja(dp, *args, filters=None, **kwargs) -> Environment` (`jinja.py:64`):
- создаёт окружение через `_create_env` и регистрирует его:
  - `dp: Dispatcher` → `dp["DialogsJinjaEnvironment"] = env` (рекомендуемый путь; попадает в
    `middleware_data` благодаря workflow-data aiogram);
  - `dp: Bot` → `setattr(bot, ...)` + **`DeprecationWarning`** (`jinja.py:71`): «use `Dispatcher`».
- `filters: Iterable[tuple[str, Filter]] | Mapping[str, Filter] | None` — кастомные фильтры,
  добавляются в `env.filters` (`jinja.py:59`). `Filter = Callable[..., str]`.

`_create_env(*args, filters=None, **kwargs)` (`jinja.py:50`) — дефолты окружения:
| Опция | Значение по умолчанию | Эффект |
|---|---|---|
| `autoescape` | `True` | **HTML-экранирование** значений (защита от инъекций/ломки разметки) |
| `lstrip_blocks` | `True` | срезает пробелы слева до блочного тега |
| `trim_blocks` | `True` | срезает первый перевод строки после блочного тега |
| `loader` | `StubLoader()` | шаблон = переданная строка |

Любой из дефолтов перекрывается через `kwargs` в `setup_jinja(...)`
(например, `setup_jinja(dp, autoescape=False)` или `enable_async=True` → `env.is_async`).

### Подводные камни Jinja
- **Обязательно** выставить `parse_mode="HTML"` (на `Window` или глобально у бота), иначе HTML-теги
  уйдут как текст. См. `docs/.../jinja/example.py:30`.
- `autoescape=True` экранирует **значения данных**, а не статику шаблона. Поэтому теги, которые вы
  пишете руками в шаблоне (`<b>`, `<a href=...>`), не экранируются, а подставляемые `{{ value }}`
  — экранируются (см. `jinja/example.html`: `my brother's` → `my brother&#39;s`).
- Если нужно вставить уже доверенный HTML из данных — используйте `|safe`, понимая риски.
- `default_env`/общее окружение разделяется между всеми `Jinja`-виджетами без `setup_jinja` —
  кастомные фильтры надо регистрировать именно через `setup_jinja`/свой env в middleware.

---

## 8. `List` — динамический список (со скроллингом)

`src/aiogram_dialog/widgets/text/list.py:18`

```python
class List(Text, BaseScroll):
    def __init__(self, field: TextWidget, items: ItemsGetterVariant,
                 sep: str = "\n", when=None, id: str | None = None,
                 page_size: int | None = None, on_page_changed=None): ...
```

- `field: TextWidget` — шаблон **одного элемента**, рендерится для каждого item.
- `items: ItemsGetterVariant` (`common/items.py:7`) = `str | Callable | MagicFilter | Sequence`:
  | Тип | Обёртка (`get_items_getter` `items.py:28`) | Поведение |
  |---|---|---|
  | `str` | `itemgetter(s)` | `data[s]` (**KeyError**, если ключа нет — без `.get`!) |
  | `MagicFilter` | `_get_magic_getter` | `f.resolve(data)`; если результат не `Sequence` → `[]` |
  | `Callable` | как есть | `callable(data) -> Sequence` |
  | прочее (Sequence) | `_get_identity` | статический список, игнорирует `data` |

### Контекст рендера каждого элемента (`list.py:50`)
Для каждого item `field.render_text(...)` получает **новый** словарь (НЕ исходный `data`!):
| Ключ | Значение |
|---|---|
| `item` | сам элемент списка |
| `pos` | 1-based позиция (с учётом смещения страницы) |
| `pos0` | 0-based позиция |
| `current_page` | текущая страница (0-based) |
| `current_page1` | текущая страница (1-based) |
| `pages` | всего страниц |
| `data` | **исходный** `data` целиком (доступ к getter/dialog_data через `{data[...]}`) |

> Поэтому в шаблоне элемента к внешним данным обращаются через `data`, напр.
> `Format("{pos}. {item[0]} — {data[currency]}")`. См. `docs/.../list/example.py`:
> `List(Format("+ {item[0]} - {item[1]}"), items="user_info")`.

### Пагинация / скроллинг
- `List` наследует `BaseScroll` (`common/scroll.py:58`) → это **Actionable**-виджет, у него есть `id`
  и состояние страницы в данных виджета.
- Без `page_size` (`None`): одна «страница», все items, `current_page=0`, `_get_page_count → 1`.
- С `page_size`: items режутся `items[start:start+page_size]`; `current_page` ограничен сверху
  `last_page` (`min(last_page, await self.get_page(manager))`) — защита от выхода за границу.
- `get_page_count(data, manager)` `list.py:67` и `_get_page_count(items)` `list.py:71`:
  `len // page_size + bool(len % page_size)`; для пустого списка → `0`.
- `id` нужен, чтобы хранить номер страницы и подключать `Pager`-виджеты клавиатуры
  (комбинируется с `StubScroll`/`*Pager`, синхронизация — `sync_scroll` `scroll.py:84`).
- `on_page_changed: OnPageChangedVariants` — хендлер, вызываемый при `set_page`
  (`scroll.py:70`), через `ManagedScroll`.
- `sep` по умолчанию `"\n"`; пустые рендеры элементов отбрасываются `filter(None, ...)` (`list.py:65`).

### Подводные камни `List`
- `items="key"` использует `itemgetter` → **`KeyError`**, если ключа нет в `data`
  (в отличие от `Case`/`Progress`, где `.get`). Гарантируйте наличие ключа в getter.
- MagicFilter, чей результат не `Sequence` (например `None` или dict), молча превращается в `[]`.
- `page_size` без `id` технически создаст виджет, но без `id` хранить страницу негде —
  всегда нужен `id` для рабочей пагинации (`BaseScroll.__init__` принимает `id: str | None`).
- Внутри элемента нет прямого доступа к `dialog_data` по верхнему уровню — только через `data`.

---

## 9. `Progress` — текстовый прогресс-бар

`src/aiogram_dialog/widgets/text/progress.py:6`

```python
class Progress(Text):
    def __init__(self, field: str, width: int = 10,
                 filled="🟥", empty="⬜", when=None): ...
    async def _render_text(self, data, manager) -> str:
        if manager.is_preview():
            percent = 15
        else:
            percent = data.get(self.field)
        done = round((self.width * percent) / 100)
        rest = self.width - done
        return self.filled * done + self.empty * rest + f" {percent: 2.0f}%"
```

- `field: str` — ключ в `data`, откуда берётся **процент** (0..100), через `data.get(field)`.
- `width` — общее число «клеток» (по умолчанию 10); `done = round(width*percent/100)`.
- `filled`/`empty` — символы заполненной/пустой части (дефолт: 🟥 / ⬜).
- В конце добавляется `" {percent: 2.0f}%"` — процент с пробелом-заполнением (мин. ширина 2).
- **Preview**: `percent` жёстко = 15 (`progress.py:25`).

### Подводные камни `Progress`
- **`percent` может быть `None`**: если `field` нет в `data`, `data.get(...)` → `None`, и арифметика
  `width*None/100` упадёт `TypeError`. Гарантируйте наличие поля (getter обычно отдаёт `0` по
  умолчанию, см. `bg_manager_example.py`: `dialog_data.get("progress", 0)`).
- `percent` не клампится: значение `>100` даст `done>width` и «переполненный» бар; `<0` — отрицат.
  повторение строк (Python: `"x"*-1 == ""`, но `rest` станет `>width`).
- Прогресс обновляется только при перерисовке окна — обычно из фоновой задачи через
  `manager.bg()`/`BaseDialogManager.update(...)` (`docs/.../progress/bg_manager_example.py`).
- Чтобы при сообщении пользователя бот не слал новое сообщение, а редактировал —
  `MessageInput` + `ShowMode.EDIT` (`docs/.../progress/prevent_new_message.py`).

---

## 10. `ScrollingText` — прокрутка длинного текста по «страницам»

`src/aiogram_dialog/widgets/text/scrolling_text.py:11`

```python
class ScrollingText(Text, BaseScroll):
    def __init__(self, text: TextWidget, id: str, page_size: int = 0,
                 when=None, on_page_changed=None): ...
```

- Оборачивает вложенный `text: TextWidget`, рендерит его в полную строку, затем режет на куски
  по `page_size` **символов** и показывает текущую страницу.
- `_render_text` `scrolling_text.py:38`: `text[page_offset : page_offset+page_size]`,
  `page_offset = current_page * page_size`, `current_page = min(last_page, await get_page(manager))`.
- `id` **обязателен** (хранит номер страницы), наследует `BaseScroll`.
- `get_page_count(data, manager)` `:48` — считает страницы по **длине отрендеренного текста**.
- В `docs/index.rst` НЕ перечислен (нет своей страницы доков), но это публичный класс.

### Подводные камни `ScrollingText`
- `page_size=0` по умолчанию — при делении `len(text)//0` будет **ZeroDivisionError**.
  Всегда задавайте `page_size > 0`.
- Режет по символам, не по словам/строкам — может разрывать слова и HTML-теги
  (опасно при `parse_mode="HTML"`: тег может «разрезаться» между страницами → ошибка Telegram).
- Не учитывает лимит Telegram (4096 символов) сам по себе — но именно для этого и нужен,
  выставляйте `page_size` ≤ безопасного лимита.

---

## Сводная таблица сигнатур

| Виджет | Конструктор | Где берёт данные |
|---|---|---|
| `Const` | `Const(text: str, when=None)` | — |
| `Format` | `Format(text: str, when=None)` | `data` (format_map) |
| `Multi` | `Multi(*texts, sep="\n", when=None)` | вложенные тексты |
| `Or` | `Or(*texts)` (только `\|`) | первый непустой |
| `Case` | `Case(texts: dict, selector, when=None)` | селектор по `data` |
| `Jinja` | `Jinja(text: str, when=None)` | `data` + env |
| `List` | `List(field, items, sep="\n", when=None, id=None, page_size=None, on_page_changed=None)` | `items` из `data` |
| `Progress` | `Progress(field: str, width=10, filled="🟥", empty="⬜", when=None)` | `data[field]` |
| `ScrollingText` | `ScrollingText(text, id, page_size=0, when=None, on_page_changed=None)` | вложенный текст |

`when: WhenCondition = str | MagicFilter | Predicate | None` (`common/when.py:31`):
- `str` → показ, если `bool(data.get(name))` (`new_when_field` `when.py:34`);
- `MagicFilter` (`F[...]`) → `f.resolve(data)` (`new_when_magic` `when.py:43`);
- callable `Predicate(data, widget, manager) -> bool` (`when.py:11`);
- `None` → всегда показывать (`true_condition` `when.py:52`).

---

## Связи с остальной библиотекой

- **`Window`** (`window.py:86`) хранит один `TextWidget` (см. `ensure_text`/первый текст-аргумент) и
  вызывает `self.text.render_text(data, manager)` в `render()` (`window.py:166`), кладёт в `text`
  сообщения вместе с `parse_mode`.
- **`getter`/`load_data`** — поставщик `data` (см. §1). Зона данных/middleware влияет на то, какие
  ключи доступны в `Format`/`Jinja`/`Case`/`List`.
- **`BaseScroll`/`Scroll`** (`common/scroll.py`) — общий механизм пагинации, общий для `List`,
  `ScrollingText` и виджетов-`Pager` клавиатуры; синхронизация через `sync_scroll`.
- **`MagicFilter` (`F`)** из `magic_filter` — общий для `when`, `Case.selector`, `List.items`.
- **Preview-инструмент** (`tools/preview.py:75 FakeManager`, `is_preview()->True`) — единственное
  место, где спец-ветки `is_preview()` в `Format`/`Case`/`Progress` срабатывают; использует
  `Window(preview_data=...)`.
- Медиа/кнопки имеют свои аналоги рендера (`render_media`, `render_kbd`), но текст всегда отдельный
  `TextWidget`.

---

## Готовые рецепты для продакшн-шаблона

```python
from aiogram_dialog.widgets.text import Const, Format, Multi, Case, Jinja, List, Progress
from magic_filter import F

# 1. Заголовок + опциональная строка + динамика, без лишних переводов строк
text = Multi(
    Const("<b>Профиль</b>"),
    Format("Имя: {name}"),
    Format("Бан до: {banned_until}", when="banned_until"),  # строка скрыта, если ключа нет/пусто
    sep="\n",
)

# 2. Безопасный fallback (Or через |) — нет KeyError, если name отсутствует
greeting = Format("Привет, {name}!", when="name") | Const("Привет, гость!")

# 3. Выбор по статусу с дефолтом
status = Case(
    {"ok": Const("✅ Готово"), "fail": Const("❌ Ошибка"), ...: Const("⏳ В процессе")},
    selector="status",
)

# 4. Список с пагинацией (нужен id; доступ к внешним данным через data)
items = List(
    Format("{pos}. {item[title]} — {data[currency]}{item[price]}"),
    items="products", id="products_list", page_size=5,
)

# 5. Jinja: не забыть parse_mode и setup_jinja для кастомных фильтров
from aiogram_dialog.widgets.text import setup_jinja
setup_jinja(dp, filters={"money": lambda v: f"{v:,.2f}"})  # dp: Dispatcher!
card = Jinja("<b>{{ title|e }}</b>\nЦена: {{ price|money }}")  # Window(parse_mode="HTML")
```
