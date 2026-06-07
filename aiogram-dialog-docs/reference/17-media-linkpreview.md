---
zone: 17
title: "Медиа-виджеты и LinkPreview: StaticMedia, DynamicMedia, MediaScroll, LinkPreview"
library: aiogram_dialog
ref: develop @ 08abdf0 (2026-05-02)
aiogram: ">=3.14.0"
tags: [media, StaticMedia, DynamicMedia, MediaScroll, LinkPreview, MediaAttachment, MediaId, MediaIdStorage]
related_zones: [7-message-manager-media-storage]
updated: 2026-06-07
---

# Зона 17. Медиа-виджеты и LinkPreview

Эта зона покрывает виджеты окна, отвечающие за **одно медиа-вложение** (`StaticMedia`, `DynamicMedia`, `MediaScroll`, плюс базовый `Media` и комбинатор `Or`) и за **настройки предпросмотра ссылок** (`LinkPreview`). Сюда же входит сущность `MediaAttachment` / `MediaId` (общая с зоной 7) — здесь она рассматривается с точки зрения того, что возвращают виджеты.

Ключевая модель: виджет окна **рендерит** декларативное описание медиа (`MediaAttachment`), а реальную отправку/редактирование/кеширование `file_id` выполняют `DialogManager._fix_cached_media_id` (подстановка кешированного `file_id`) и `MessageManager` (отправка через Bot API). См. раздел «Связь с остальной библиотекой».

---

## 1. Карта файлов зоны

| Файл | Что внутри |
|------|-----------|
| `src/aiogram_dialog/widgets/media/base.py` | `Media` (базовый класс/протокол `MediaWidget`), `Or` (комбинатор `\|`) |
| `src/aiogram_dialog/widgets/media/static.py` | `StaticMedia` |
| `src/aiogram_dialog/widgets/media/dynamic.py` | `DynamicMedia`, тип `MediaSelector` |
| `src/aiogram_dialog/widgets/media/scroll.py` | `MediaScroll` (есть!) |
| `src/aiogram_dialog/widgets/media/__init__.py` | экспорт: `Media`, `StaticMedia`, `DynamicMedia`, `MediaScroll` |
| `src/aiogram_dialog/widgets/link_preview/base.py` | `LinkPreviewBase`, `LinkPreview` |
| `src/aiogram_dialog/widgets/link_preview/__init__.py` | экспорт: `LinkPreview`, `LinkPreviewBase` |
| `src/aiogram_dialog/api/entities/media.py` | `MediaId`, `MediaAttachment` |
| `src/aiogram_dialog/api/internal/widgets.py` | протоколы `MediaWidget`, `LinkPreviewWidget`, `TextWidget` |
| `src/aiogram_dialog/manager/message_manager.py` | `MessageManager` — реальная отправка медиа (зона 7) |
| `src/aiogram_dialog/context/media_storage.py` | `MediaIdStorage` — кеш `file_id` (зона 7) |

Импорт-пути в продакшене:
```python
from aiogram_dialog.widgets.media import StaticMedia, DynamicMedia, MediaScroll, Media
from aiogram_dialog.widgets.link_preview import LinkPreview
from aiogram_dialog.api.entities import MediaAttachment, MediaId
from aiogram.types import ContentType   # или aiogram.enums.ContentType
```

---

## 2. Базовый класс `Media` и протокол `MediaWidget`

### Протокол `MediaWidget`
`src/aiogram_dialog/api/internal/widgets.py:106`

```python
@runtime_checkable
class MediaWidget(Widget, Protocol):
    @abstractmethod
    async def render_media(self, data: dict, manager: DialogManager) -> MediaAttachment | None: ...
```
Наследует `Widget` (методы `managed(manager)`, `find(widget_id)`).

### Класс `Media`
`src/aiogram_dialog/widgets/media/base.py:9`

```python
class Media(Whenable, BaseWidget, MediaWidget):
    def __init__(self, when: WhenCondition = None): ...

    @add_exception_note
    async def render_media(self, data, manager) -> MediaAttachment | None:
        if not self.is_(data, manager):
            return None
        return await self._render_media(data, manager)

    async def _render_media(self, data, manager) -> MediaAttachment | None:
        return None
```

Наследование:
- `Whenable` (`widgets/common/when.py:56`) — даёт `when`-условие и метод `is_(data, manager)`. `WhenCondition = str | MagicFilter | Predicate | None`. Строка → проверка `bool(data.get(field))`; `MagicFilter` → `f.resolve(data)`; вызываемое → `predicate(data, widget, manager)`.
- `BaseWidget` (`widgets/common/base.py:7`) — `managed(manager)` возвращает сам виджет, `find(widget_id)` → `None`.
- `MediaWidget` — протокол выше.

**Контракт переопределения:** наследники переопределяют `_render_media`, а НЕ `render_media`. `render_media` сам проверяет `when` (возврат `None`, если условие ложно) и навешивает `@add_exception_note` (`utils.py:230`) — добавляет `e.add_note(f"at {self!r}")` на Python ≥ 3.11 для удобной трассировки.

Базовый `Media()` без переопределения всегда рендерит `None` — это «пустой» медиа-виджет, который `ensure_media` ставит в окно по умолчанию, когда медиа не задано (`widgets/utils.py:82`).

### Комбинатор `Or` и оператор `|`
`src/aiogram_dialog/widgets/media/base.py:37`

```python
media = StaticMedia(path="a.png", when=F["a"]) | StaticMedia(url="http://...", when=F["b"]) | StaticMedia(path="c.png")
```

- `Media.__or__` / `__ror__` строят `Or(*widgets)`. `Or._render_media` идёт по виджетам по порядку и возвращает **первый непустой** `render_media` (то есть первый, у которого прошло `when`). Если все вернули `None` → `None`.
- `__or__`/`__ror__`/`__ior__` сплющивают вложенность, поэтому цепочка `a | b | c` — это плоский `Or(a, b, c)`, а не дерево.
- Проверка `when` у каждого подвиджета работает внутри его `render_media`, поэтому `Or` — это «выбор первого подходящего источника медиа». Подтверждено тестом `tests/widgets/media/test_base.py:31` (`test_or_condition`).

> Важно: `|` — это «или» по источникам внутри **одного** медиа-слота окна. В окно по-прежнему можно положить только один медиа-виджет (см. §9).

---

## 3. `MediaAttachment` и `MediaId`

`src/aiogram_dialog/api/entities/media.py`. Экспортируются из `aiogram_dialog.api.entities`.

### `MediaId`
`media.py:7`
```python
@dataclass
class MediaId:
    file_id: str
    file_unique_id: str | None = None
```
Кастомный `__eq__` (`media.py:12`):
- сравнение только с другим `MediaId` (иначе `False`);
- если у любого из двух `file_unique_id is None` → сравнивают по `file_id`;
- иначе сравнивают по `file_unique_id`.

`file_unique_id` важен: Telegram может выдавать **разные** `file_id` для одного и того же файла (зависит от бота/времени), но `file_unique_id` стабилен — именно по нему `MediaIdStorage` и `_message_changed` определяют, «то же ли это медиа».

### `MediaAttachment`
`media.py:20` — это НЕ dataclass, обычный класс с `__init__`.

```python
class MediaAttachment:
    def __init__(
        self,
        type: ContentType,
        url: str | None = None,
        path: str | Path | None = None,
        file_id: MediaId | None = None,
        use_pipe: bool = False,
        **kwargs,
    ):
        if not (url or path or file_id):
            raise ValueError("Neither url nor path not file_id are provided")
        ...
        self.kwargs = kwargs
```

| Поле | Тип | Назначение |
|------|-----|-----------|
| `type` | `ContentType` | тип контента — определяет метод отправки и `InputMedia*` при редактировании |
| `url` | `str \| None` | URL файла (или кастомный URI для своего `get_media_source`) |
| `path` | `str \| Path \| None` | путь в файловой системе → `FSInputFile` |
| `file_id` | `MediaId \| None` | готовый Telegram `file_id` — самый быстрый способ |
| `use_pipe` | `bool` | для `url`: если `True`, файл скачивается через `URLInputFile(url, bot=bot)` (бот проксирует), иначе URL передаётся в Telegram «как есть» |
| `**kwargs` | — | произвольные доппараметры aiogram (попадают в `send_*` и в `InputMedia*`) |

- Хотя бы один из `url`/`path`/`file_id` обязателен — иначе `ValueError` в конструкторе.
- `__eq__` (`media.py:39`) сравнивает по `type`, `url`, `path`, `file_id`, `use_pipe`, `kwargs` (и по `type(other) is type(self)`).

### `ContentType` — что реально поддерживается
`MessageManager.SEND_METHODS` (`message_manager.py:36`) — **отправка** (9 типов):
`ANIMATION, AUDIO, DOCUMENT, PHOTO, VIDEO, VIDEO_NOTE, DICE, STICKER, VOICE`.

`MessageManager.INPUT_MEDIA_TYPES` (`message_manager.py:48`) — **редактирование** через `edit_message_media` (только 5 типов):
`ANIMATION, DOCUMENT, AUDIO, PHOTO, VIDEO`.

> Краевой случай: типы `VIDEO_NOTE`, `STICKER`, `DICE`, `VOICE` можно ОТПРАВИТЬ, но при попытке отредактировать медиа-сообщение этого типа `edit_media` обращается к `INPUT_MEDIA_TYPES[type]` → `KeyError`. На практике аiogram-dialog обходит это: для `VOICE` он принудительно отправляет новое сообщение, а не редактирует (`_can_edit` → `had_voice`/`need_voice`). Для `VIDEO_NOTE`/`STICKER`/`DICE` спец-обработки нет — при попытке отредактировать такое сообщение возможен `KeyError`. Для них используйте `ShowMode.DELETE_AND_SEND` или окна без перерисовки.

---

## 4. `StaticMedia`

`src/aiogram_dialog/widgets/media/static.py:13`

```python
class StaticMedia(Media):
    def __init__(
        self,
        *,                                  # все параметры — только keyword!
        path: TextWidget | str | Path | None = None,
        url: TextWidget | str | None = None,
        type: ContentType = ContentType.PHOTO,
        use_pipe: bool = False,
        media_params: dict | None = None,
        when: WhenCondition = None,
    ):
```

Поведение конструктора:
- Если не задан ни `url`, ни `path` → `ValueError("Neither url nor path are provided")`.
- `path`: если `Path` или `str` → оборачивается в `Const(str(path))`. Можно передать **любой `Text`-виджет** (`Format`, `Multi`, `Case`, и т.п.) для интерполяции.
- `url`: если `str` → оборачивается в `Const`. Тоже принимает `Text`-виджет.
- `type` по умолчанию `ContentType.PHOTO`.
- `media_params` → копится как `self.media_params = media_params or {}` и распаковывается в `MediaAttachment(**self.media_params)` (то есть в `kwargs` вложения — доппараметры aiogram типа `duration`, `width`, `height`, `supports_streaming`, `has_spoiler` и т.д.).

`_render_media` (`static.py:39`):
```python
url  = await self.url.render_text(data, manager)  if self.url  else None
path = await self.path.render_text(data, manager) if self.path else None
return MediaAttachment(type=self.type, url=url, path=path, use_pipe=self.use_pipe, **self.media_params)
```

**Важно: `StaticMedia` не задаёт `file_id` напрямую.** Источник всегда `url` или `path`. `file_id` подставляется автоматически из `MediaIdStorage` на этапе `DialogManager._fix_cached_media_id` по ключу `(path, url, type)` — то есть «static» здесь про неизменность пути/URL, а не про отсутствие кеша.

### Text-подстановки в path/url

Поскольку `path`/`url` — это `Text`-виджеты, в них работает вся механика рендера текста (зоны Text):

```python
from aiogram_dialog.widgets.text import Format
StaticMedia(path=Format("/images/{user_id}.png"), type=ContentType.PHOTO)
StaticMedia(url=Format("https://cdn/{lang}/banner.jpg"))
```
`{user_id}`/`{lang}` берутся из `data` (getter + dialog data). См. тест `MediaScroll` с `StaticMedia(path=Format("/{item}"))` (`test_scroll.py:14`).

### Примеры
Минимальный (`docs/widgets/media/static_media/example.py`):
```python
Window(
    StaticMedia(path="/home/tishka17/python_logo.png", type=ContentType.PHOTO),
)
```
URL vs path (тест `test_media_message.py:24`): `StaticMedia(url="fake_image.png")` и `StaticMedia(path="fake_image.png")` — оба дают `message.photo`.

> Подводный камень относительных путей: «Be careful using relative paths. Mind the working directory.» (`docs/.../static_media/index.rst:11`). `FSInputFile` резолвит путь относительно CWD процесса бота, а не модуля. В продакшене используйте абсолютные пути (`os.path.join(BASE_DIR, ...)` / `pathlib`).

---

## 5. `DynamicMedia`

`src/aiogram_dialog/widgets/media/dynamic.py:19` (портирован из `aiogram_dialog_extras`)

```python
MediaSelector = Callable[[dict], MediaAttachment]

class DynamicMedia(Media):
    def __init__(self, selector: str | MediaSelector, when: WhenCondition = None):
        super().__init__(when=when)
        if isinstance(selector, str):
            self.selector = itemgetter(selector)
        else:
            self.selector = selector

    async def _render_media(self, data, manager) -> MediaAttachment | None:
        media = self.selector(data)   # ВНИМАНИЕ: вызывается синхронно, не await
        return media
```

- `selector` — либо **имя ключа** в `data` (тогда `itemgetter(selector)` достаёт `data[selector]`), либо **синхронная функция** `data -> MediaAttachment | None`.
- Getter окна должен положить в `data` готовый `MediaAttachment` (а не путь/URL): см. `docs/.../dynamic_media/example.py`:
  ```python
  async def get_data(**kwargs):
      image = MediaAttachment(ContentType.PHOTO, file_id=MediaId("AgAC...file_id"))
      return {"photo": image}

  Window(DynamicMedia("photo"), state=..., getter=get_data)
  ```

Подводные камни:
- **`selector` синхронный**: `self.selector(data)` без `await`. Нельзя передать корутину/async-функцию. Всю асинхронную работу (запрос в БД и т.п.) делайте в getter окна, а в `data` кладите уже готовый `MediaAttachment`.
- **`itemgetter`-вариант кидает `KeyError`**, если ключа нет в `data`. Если медиа может отсутствовать — либо всегда кладите ключ (например, `None` + `when`), либо используйте функцию-селектор, либо комбинируйте с `when`. Полноценный паттерн «нет фото → плейсхолдер» в `example/input_media_group.py:52` (getter всегда возвращает `MediaAttachment`).
- Селектор **может вернуть `None`** (тип возврата `MediaAttachment | None`) — медиа просто не будет.

---

## 6. `MediaScroll`

`src/aiogram_dialog/widgets/media/scroll.py:16` — медиа-виджет с пагинацией (карусель). **В зоне присутствует.**

```python
class MediaScroll(Media, BaseScroll):
    def __init__(
        self,
        media: Media,                      # вложенный медиа-виджет (рендерит одну страницу)
        items: ItemsGetterVariant,         # str | Callable | MagicFilter | Sequence
        id: str,                           # обязателен (BaseScroll)
        when: WhenCondition = None,
        on_page_changed: OnPageChangedVariants = None,
    ):
```

Наследует:
- `Media` (render_media/when);
- `BaseScroll` (`widgets/common/scroll.py:58`) — управление текущей страницей: `get_page(manager)`, `set_page(event, page, manager)`, `managed(manager) -> ManagedScroll`, callback `on_page_changed`. Страница хранится в widget-data по `id`.

`_render_media` (`scroll.py:30`):
1. `items = self.items_getter(data)`; `pages = len(items)`.
2. `current_page = min(await self.get_page(manager), pages)` — текущая страница из widget-data.
3. `item = items[current_page]`.
4. Рендерит вложенный `media`, передавая ему **новый контекст** (а не исходный `data`):

| Ключ в data для вложенного media | Значение |
|----------------------------------|----------|
| `current_page` | индекс (0-based) |
| `current_page1` | `current_page + 1` |
| `pages` | всего страниц |
| `data` | исходный `data` окна |
| `item` | текущий элемент |
| `pos` | `current_page + 1` |
| `pos0` | `current_page` |

`get_page_count(data, manager)` → `len(items)`.

Пример (тест `test_scroll.py:10`):
```python
media = MediaScroll(
    items=["0.png", "1.png", "2.png"],
    media=StaticMedia(path=Format("/{item}")),   # {item} из контекста скролла
    id="m",
)
# render → path "/0.png"; после set_page(2) → "/2.png"
```

Управление страницей извне (как у любого скролла): `dialog_manager.find("m")` → `ManagedScroll` с `get_page()/set_page(page)`. Кнопки пагинации (`NumberedPager`, `FirstPage`, `PrevPage`, `NextPage`, `LastPage`, `StubScroll`, `sync_scroll`) синхронизируются по `id` скролла. Сравните с паттерном `DynamicMedia` + `StubScroll` в `example/input_media_group.py` (там скролл и медиа разделены вручную; `MediaScroll` инкапсулирует это в один виджет).

Краевые случаи:
- `current_page = min(get_page, pages)` — если сохранённая страница вышла за пределы (`items` укоротился), берётся `pages`. **Но** `items[pages]` при непустом списке = выход за границу → `IndexError` (валидный индекс — `pages-1`). Безопасно при удалении элементов сбрасывать страницу самостоятельно (как `on_delete` в `input_media_group.py`). При пустом `items` (`pages=0`) → `items[0]` → `IndexError`; оборачивайте `MediaScroll` в `when`, когда элементов может не быть.

---

## 7. `LinkPreview`

`src/aiogram_dialog/widgets/link_preview/base.py`

### Протокол `LinkPreviewWidget`
`api/internal/widgets.py:68`
```python
@runtime_checkable
class LinkPreviewWidget(Widget, Protocol):
    async def render_link_preview(self, data, manager) -> LinkPreviewOptions | None: ...
```

### `LinkPreviewBase` / `LinkPreview`
```python
class LinkPreviewBase(Whenable, BaseWidget, LinkPreviewWidget):
    def __init__(self, when: WhenCondition = None): ...
    async def render_link_preview(...):           # проверяет when
        if not self.is_(data, manager): return None
        return await self._render_link_preview(data, manager)

class LinkPreview(LinkPreviewBase):
    def __init__(
        self,
        url: TextWidget | None = None,            # ПОЗИЦИОННЫЙ первый аргумент
        is_disabled: bool = False,
        prefer_small_media: bool = False,
        prefer_large_media: bool = False,
        show_above_text: bool = False,
        when: WhenCondition = None,
    ): ...
```

`_render_link_preview` (`base.py:50`) собирает aiogram-объект `LinkPreviewOptions(url=..., is_disabled=, prefer_small_media=, prefer_large_media=, show_above_text=)`. `url` рендерится из `Text`-виджета (если задан), иначе `None`.

| Параметр | Назначение |
|----------|-----------|
| `url` (`TextWidget`) | URL для превью. Если `None` — Telegram берёт первый URL из текста сообщения |
| `is_disabled` | `True` — полностью отключить превью ссылок |
| `prefer_small_media` | уменьшить медиа в превью (игнорируется, если изменение размера не поддерживается) |
| `prefer_large_media` | увеличить медиа в превью |
| `show_above_text` | показать превью над текстом |

> Примечание: `url` здесь — `TextWidget | None`, в отличие от `StaticMedia`, который принимает и `str` (оборачивая в `Const`). Для `LinkPreview` строку нужно оборачивать вручную: `LinkPreview(url=Const("http://ya.ru"))` (см. `example/loading.py:80`, `docs/.../link_preview/example.py`).

Куда уходит результат: в `Window.render()` → `NewMessage.link_preview_options` → в `send_message`/`edit_text` (`message_manager.py:409,363`). Важно: `link_preview_options` прокидывается только в `send_text`/`edit_text`. У медиа-сообщений (`send_media`/`edit_caption`/`edit_media`) этого параметра нет — у медиа собственный предпросмотр не настраивается этим виджетом.

Примеры:
```python
# Отключить превью у ссылки в тексте
Window(Const("https://nplus1.ru/..."), LinkPreview(is_disabled=True), state=SG.MAIN)
# Маленькое превью над текстом для явного URL
Window(Const("some text"),
       LinkPreview(url=Const("https://..."), prefer_small_media=True, show_above_text=True),
       state=SG.SECOND)
```

### Связь с устаревшим `disable_web_page_preview`
`window.py:72`. Старый параметр `Window(..., disable_web_page_preview=...)`:
- Нельзя использовать вместе с виджетом `LinkPreview` → `ValueError("Cannot use LinkPreview widget together with disable_web_page_preview")`.
- При использовании — `DeprecationWarning` и внутреннее преобразование в `LinkPreview(is_disabled=True)`.

В продакшене используйте **только** виджет `LinkPreview`.

---

## 8. Как медиа попадает в окно и отправляется (связь с зонами 5/7)

### Сборка виджетов окна
`widgets/utils.py:97` `ensure_widgets` разбирает `*widgets` окна на 5 групп: `(text, keyboard, on_message, media, link_preview)`.

- `ensure_media` (`utils.py:75`): если несколько медиа-виджетов → `ValueError("Only one media widget is supported")`. Если ноль — подставляется пустой `Media()`. **Один медиа-виджет на окно.**
- `ensure_link_preview` (`utils.py:85`): если несколько → `ValueError("Only one link preview widget is supported")`. Если ноль → `None`.
- `WidgetSrc` (`utils.py:17`) допускает `Media` и `LinkPreviewBase` среди элементов окна.

### Рендер
`Window.render()` (`window.py:147`) собирает `NewMessage(... media=await self.render_media(...), link_preview_options=await self.render_link_preview(...))`. `render_media` вызывает `self.media.render_media(data, manager)` (`window.py:91`).

### Подстановка кешированного `file_id`
`DialogManager._fix_cached_media_id` (`manager/manager.py:427`):
```python
if not new_message.media or new_message.media.file_id:
    return
new_message.media.file_id = await self.media_id_storage.get_media_id(
    path=new_message.media.path, url=new_message.media.url, type=new_message.media.type,
)
```
То есть после рендера, **если у вложения ещё нет `file_id`**, менеджер ищет его в `MediaIdStorage` по ключу `(path, url, type)`. Если виджет уже вернул `file_id` (как `DynamicMedia` с `MediaId`) — кеш не трогается.

### Отправка / редактирование
`MessageManager` (зона 7):
- `get_media_source` (`message_manager.py:92`) — **приоритет источника: `file_id` → `url` → `path`**:
  ```python
  if media.file_id: return media.file_id.file_id
  if media.url:     return URLInputFile(url, bot) if media.use_pipe else media.url
  else:             return FSInputFile(media.path)
  ```
- `send_media` (`message_manager.py:412`) — выбирает метод по `SEND_METHODS[media.type]`; неизвестный тип → `ValueError(f"ContentType {type} is not supported")`. Прокидывает `**media.kwargs`.
- `edit_media` (`message_manager.py:366`) — строит `INPUT_MEDIA_TYPES[media.type](...)` (только 5 типов!) и `**media.kwargs`.
- `_message_changed` (`message_manager.py:129`) и `edit_message` (`message_manager.py:321`) сравнивают медиа по `file_id` (через `MediaId.__eq__` / `file_unique_id`). Если `file_id` совпал — правится только подпись (`edit_caption`), иначе `edit_media`.

### Кеширование после отправки
`DialogManager` (`manager/manager.py:407`): после успешной отправки, если у сообщения было медиа — `media_id_storage.save_media_id(path, url, type, MediaId(sent.media_id, sent.media_uniq_id))`.

### Где включается кеш
`setup.py:181`: по умолчанию `MediaIdStorage()` (in-memory `LRUCache(maxsize=10240)`). Кастомный — через `setup_dialogs(dp, media_id_storage=...)`. Кастомный источник медиа — через `setup_dialogs(dp, message_manager=...)`.

---

## 9. `MediaIdStorage` — детали кеша file_id (повтор из зоны 7, важно для медиа)

`context/media_storage.py`:
- Ключ кеша — `(path, url, type)`. Значение — `CachedMediaId(media_id, mtime)`.
- `mtime` сохраняется только для `path` (через `os.path.getmtime`). При `get_media_id`: если файл по `path` изменился (mtime отличается) → возвращается `None` (файл перезагрузится). Подтверждено `tests/widgets/media/test_media_storage.py:40`.
- Если ни `path`, ни `url` нет → кеш не используется (`get`/`save` возвращают/делают `None`).
- **Кеш по URL не инвалидируется** — у URL нет mtime. Если содержимое по тому же URL поменялось, бот продолжит слать старый `file_id`. Для динамичного содержимого по фиксированному URL это подвох (меняйте URL/добавляйте version-параметр, или используйте `DynamicMedia` с явным `file_id=None` и уникальными URL).
- Дефолтный storage — **in-memory**: при рестарте процесса кеш теряется (первая отправка после рестарта снова грузит файл). Для персистентности реализуйте `MediaIdStorageProtocol` (`api/protocols/media.py`) и передайте в `setup_dialogs`.

---

## 10. Кастомные источники медиа (other media sources)

`docs/widgets/media/other_media_sources/index.rst`. Рецепт для нестандартных источников (БД, приватный S3, рантайм-генерация):
1. Придумайте URI-схему (`my://text`, `bot://1234`).
2. Унаследуйтесь от `MessageManager`, переопределите `get_media_source`.
3. Передайте инстанс в `setup_dialogs(dp, message_manager=...)`.

Это сохраняет кеширование `file_id` и работу обычных медиа-виджетов. Рабочий пример — `example/custom_media_url.py`:
```python
class CustomMessageManager(MessageManager):
    async def get_media_source(self, media, bot):
        if media.file_id:                                # кеш сработал — отдаём дефолт
            return await super().get_media_source(media, bot)
        if media.url and media.url.startswith("my://"):  # наш URI
            text = media.url[len("my://"):]
            return BufferedInputFile(draw(text), f"{text}.png")
        return await super().get_media_source(media, bot)

# StaticMedia(url="my://text", type=ContentType.PHOTO) + setup_dialogs(dp, message_manager=CustomMessageManager())
```
Тонкость: первая ветка `if media.file_id` обязательна, иначе после кеширования (когда `_fix_cached_media_id` подставит `file_id`) ваша генерация будет дёргаться повторно вместо использования кеша.

---

## 11. Подводные камни и краевые случаи (сводка для шаблона)

| # | Грабли | Последствие / решение |
|---|--------|----------------------|
| 1 | **Только один медиа-виджет на окно** | Несколько → `ValueError`. Для выбора используйте `\|` (`Or`) или `when`. Несколько фото = медиагруппа — не поддерживается окном (ниже). |
| 2 | **Приоритет источников `file_id` > `url` > `path`** | В `MediaAttachment` поля не взаимоисключающие; `get_media_source` берёт первый по приоритету. Не задавайте лишние поля. |
| 3 | **`type` должен совпадать с реальным файлом** | Telegram отклонит, например, MP4 как `PHOTO`. Метод отправки выбирается по `type`. |
| 4 | **Кеш по URL не инвалидируется** | Содержимое по тому же URL изменилось → шлётся старый `file_id`. Меняйте URL или используйте mtime-кеш через `path`. |
| 5 | **Дефолтный кеш in-memory, теряется при рестарте** | Первая отправка после рестарта снова грузит файл. Нужен персистентный `MediaIdStorageProtocol`. |
| 6 | **Относительные пути в `StaticMedia(path=...)`** | Резолв относительно CWD процесса. Используйте абсолютные пути. |
| 7 | **`DynamicMedia` selector синхронный** | Нельзя async-селектор. Готовьте `MediaAttachment` в getter окна. |
| 8 | **`DynamicMedia("key")` кидает `KeyError`, если ключа нет** | Всегда кладите ключ в getter (или плейсхолдер), либо функцию-селектор, либо `when`. |
| 9 | **Редактирование медиа ограничено 5 типами** | `edit_message_media` поддерживает только `ANIMATION/DOCUMENT/AUDIO/PHOTO/VIDEO`. `VIDEO_NOTE/STICKER/DICE` при редактировании → `KeyError`. `VOICE` обходится принудительной переотправкой. |
| 10 | **Медиа нельзя «отредактировать как текст»** | Если у старого было медиа, а у нового нет (или наоборот) — `_can_edit` запрещает edit, идёт `delete + send` (сообщение «моргнёт», новый `message_id`). Аналогично reply-клавиатура. |
| 11 | **Медиагруппы (альбомы) окном не поддерживаются** | Окно шлёт ровно одно сообщение с одним вложением. Для приёма альбома есть `MessageInput`, но окно их не редактирует как группу. Для просмотра нескольких фото — `DynamicMedia`/`MediaScroll` с пагинацией (`example/input_media_group.py`). |
| 12 | **`LinkPreview.url` принимает только `TextWidget`** | Строку оборачивайте в `Const(...)`. Не путать со `StaticMedia`, где `str` оборачивается автоматически. |
| 13 | **`disable_web_page_preview` устарел** | Несовместим с виджетом `LinkPreview` (→ `ValueError`), кидает `DeprecationWarning`. Используйте `LinkPreview(is_disabled=True)`. |
| 14 | **`LinkPreview` влияет только на текстовые сообщения** | `link_preview_options` уходит лишь в `send_text`/`edit_text`. Для медиа-сообщений превью этим виджетом не управляется. |
| 15 | **`MediaScroll` и пустой/укороченный `items`** | `pages=0` → `items[0]` → `IndexError`; уменьшение `items` без сброса страницы → выход за границу. Сбрасывайте страницу при удалении элементов; оборачивайте в `when`, если список может быть пуст. |
| 16 | **`StaticMedia` не отдаёт `file_id` напрямую** | Для отправки готового `file_id` нужен `DynamicMedia` + `MediaAttachment(file_id=MediaId(...))`. |

---

## 12. Готовые паттерны для продакшн-шаблона

**Статичный баннер с интерполяцией пути:**
```python
from aiogram_dialog.widgets.media import StaticMedia
from aiogram_dialog.widgets.text import Format
from aiogram.types import ContentType

StaticMedia(path=Format("{assets}/banner_{lang}.png"), type=ContentType.PHOTO)
# getter: {"assets": str(ASSETS_DIR), "lang": user_lang}
```

**Динамичное фото с fallback-плейсхолдером:**
```python
async def getter(dialog_manager, **kw):
    file_id = ...  # из БД
    if file_id:
        media = MediaAttachment(ContentType.PHOTO, file_id=MediaId(file_id))
    else:
        media = MediaAttachment(ContentType.PHOTO, path=str(PLACEHOLDER))
    return {"media": media}

Window(DynamicMedia("media"), getter=getter, state=...)
```

**Выбор источника по условию (`Or`):**
```python
media = (
    StaticMedia(path=Format("{dir}/{id}.png"), when=F["has_local"]) |
    StaticMedia(url=Format("https://cdn/{id}.png"))
)
```

**Карусель изображений:**
```python
MediaScroll(
    media=StaticMedia(path=Format("{dir}/{item}")),
    items="images",          # data["images"] -> Sequence
    id="gallery",
    on_page_changed=...,
)
# + NumberedPager(scroll="gallery") в клавиатуре
```

**Превью ссылок:**
```python
LinkPreview(url=Const("https://example.com"), prefer_large_media=True, show_above_text=True)
# либо отключить: LinkPreview(is_disabled=True)
```

**Кастомный источник + персистентный кеш:**
```python
setup_dialogs(
    dp,
    message_manager=CustomMessageManager(),   # override get_media_source
    media_id_storage=RedisMediaIdStorage(),   # реализует MediaIdStorageProtocol
)
```

---

## 13. Тестирование медиа (для шаблона)

`tests/widgets/media/`:
- `test_base.py` — `Or` и `when`-комбинатор (рендер без бота, через `mock_manager`).
- `test_media_message.py` — e2e через `BotClient` + `MockMessageManager`; проверка `message_manager.one_message().photo` для `url`/`path`.
- `test_scroll.py` — `MediaScroll` + `set_page`/`managed`.
- `test_media_storage.py` — инвалидация кеша по mtime файла.

Инструменты: `aiogram_dialog.test_tools.BotClient`, `MockMessageManager` (`src/aiogram_dialog/test_tools/mock_message_manager.py`). Для unit-рендера достаточно `await widget.render_media({...}, mock_manager)` и сравнения `MediaAttachment.__eq__`.

---

## 14. Сводка ссылок на код

| Сущность | Ссылка |
|----------|--------|
| `Media`, `Or` | `widgets/media/base.py:9`, `:37` |
| `StaticMedia` | `widgets/media/static.py:13` |
| `DynamicMedia`, `MediaSelector` | `widgets/media/dynamic.py:19`, `:16` |
| `MediaScroll` | `widgets/media/scroll.py:16` |
| `LinkPreview`, `LinkPreviewBase` | `widgets/link_preview/base.py:26`, `:9` |
| `MediaId`, `MediaAttachment` | `api/entities/media.py:7`, `:20` |
| Протоколы `MediaWidget`/`LinkPreviewWidget` | `api/internal/widgets.py:106`, `:68` |
| `ensure_media`/`ensure_link_preview`/`ensure_widgets` | `widgets/utils.py:75`, `:85`, `:97` |
| `Window.render`/`render_media`/`render_link_preview` | `window.py:147`, `:91`, `:106` |
| `_fix_cached_media_id` / `save_media_id` | `manager/manager.py:427`, `:407` |
| `MessageManager.get_media_source`/`send_media`/`edit_media` | `message_manager.py:92`, `:412`, `:366` |
| `SEND_METHODS` / `INPUT_MEDIA_TYPES` | `message_manager.py:36`, `:48` |
| `MediaIdStorage` | `context/media_storage.py:16` |
| `MediaIdStorageProtocol` | `api/protocols/media.py:9` |
| `setup_dialogs(media_id_storage=, message_manager=)` | `setup.py:221`, `:173` |
