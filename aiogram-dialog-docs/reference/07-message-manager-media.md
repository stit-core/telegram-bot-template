---
zone: "07"
title: "MessageManager: отправка/редактирование/удаление сообщений, NewMessage, кеш media file_id"
source_repo: aiogram_dialog
source_ref: "develop @ 08abdf0 (2026-05-02)"
aiogram_min: ">=3.14.0"
status: reference
key_files:
  - src/aiogram_dialog/manager/message_manager.py
  - src/aiogram_dialog/api/protocols/message_manager.py
  - src/aiogram_dialog/api/protocols/media.py
  - src/aiogram_dialog/api/entities/new_message.py
  - src/aiogram_dialog/api/entities/media.py
  - src/aiogram_dialog/context/media_storage.py
related:
  - src/aiogram_dialog/manager/manager.py        # show()/show_message() orchestration
  - src/aiogram_dialog/window.py                 # сборка NewMessage в render()
  - src/aiogram_dialog/setup.py                  # подмена через setup_dialogs
  - src/aiogram_dialog/test_tools/mock_message_manager.py
tags: [message-manager, media, file_id, show_mode, new_message, old_message, edit, delete]
---

# Зона 07 — MessageManager, NewMessage/OldMessage, кеш media file_id

## TL;DR

`MessageManager` — единственная точка, через которую aiogram-dialog общается с Bot API при
показе окна диалога. Он принимает **что нужно показать** (`NewMessage`) и **что сейчас на
экране** (`OldMessage | None`) и решает: отправить новое сообщение, отредактировать
существующее или удалить-и-отправить. Решение принимается по `ShowMode` (приоритет) и по
диффу `NewMessage` vs `OldMessage` (текст, разметка, медиа, protect_content, link preview).
Вся работа с медиа проходит через `get_media_source()` (точка кастомизации источников) и
`MediaIdStorage` (LRU-кеш `file_id`, чтобы не перезаливать один и тот же файл). Подменяется
целиком через `setup_dialogs(..., message_manager=..., media_id_storage=...)`.

Где вызывается из ядра:
- `DialogManager.show()` → `message_manager.show_message(bot, new_message, old_message)`
  (`manager.py:398`), затем сохраняет результат и кеширует `file_id` (`manager.py:406-416`).
- `DialogManager._remove_kbd()` → `message_manager.remove_kbd(...)` (`manager.py:181`).
- `DialogManager.answer_callback()` → `message_manager.answer_callback(...)` (`manager.py:224`).

---

## 1. Протокол `MessageManagerProtocol`

`src/aiogram_dialog/api/protocols/message_manager.py`

Это `typing.Protocol` с тремя обязательными методами. Кастомный менеджер ОБЯЗАН реализовать
все три (хотя на практике наследуются от `MessageManager` и переопределяют точечно).

| Метод | Сигнатура | Назначение / возврат |
|---|---|---|
| `show_message` | `async (self, bot: Bot, new_message: NewMessage, old_message: OldMessage \| None) -> OldMessage` | Главный метод. Решает send/edit/delete и возвращает «снимок» того, что реально оказалось на экране (`OldMessage`), который ядро сохранит в `Stack`. При `NO_UPDATE` / «message is not modified» бросает `MessageNotModified` (`:27`). |
| `remove_kbd` | `async (self, bot: Bot, show_mode: ShowMode, old_message: OldMessage \| None) -> Message \| None` | Убрать клавиатуру у предыдущего сообщения (при закрытии диалога/reset). Возвращает отправленное вспомогательное сообщение или `None` (`:18`). |
| `answer_callback` | `async (self, bot: Bot, callback_query: CallbackQuery) -> None` | Ответить на callback (убрать «часики»). Глушит ошибку «query is too old / invalid» (`:34`). |

Исключение `MessageNotModified(DialogsError)` объявлено здесь же (`message_manager.py:12`).
Ядро ловит его в `show()` и НЕ сохраняет новые id (`manager.py:401-404`) — это нормальный
поток, не ошибка.

> Важно: протокол узкий (3 метода), но дефолтная реализация `MessageManager` имеет ~20
> внутренних методов (`send_text`, `edit_media`, `get_media_source`, `_message_changed`,
> `_can_edit`, …). При наследовании можно переопределить любой из них — это и есть основной
> способ кастомизации (ретраи, троттлинг, кастомные источники медиа).

---

## 2. Сущности данных

### 2.1 `NewMessage` — «что хотим показать»

`src/aiogram_dialog/api/entities/new_message.py:41`. `@dataclass`. Собирается в
`Window.render()` (`window.py:162`).

| Поле | Тип | Назначение |
|---|---|---|
| `chat` | `Chat` | обязательное; куда слать |
| `thread_id` | `int \| None` | топик форума (`message_thread_id`) |
| `business_connection_id` | `str \| None` | business-аккаунт |
| `text` | `str \| None` | текст или caption (если есть медиа) |
| `reply_markup` | `MarkupVariant \| None` | `InlineKeyboardMarkup` / `ReplyKeyboardMarkup` / `ReplyKeyboardRemove` / `ForceReply` |
| `parse_mode` | `str \| None` | режим парсинга |
| `protect_content` | `bool \| None` | запрет пересылки/сохранения |
| `show_mode` | `ShowMode` = `AUTO` | проставляется ядром в `show()` (`manager.py:390-392`) ДО вызова менеджера |
| `media` | `MediaAttachment \| None` | медиавложение |
| `link_preview_options` | `LinkPreviewOptions \| None` | управление превью ссылок |

> Нет отдельного `disable_web_page_preview` — управление превью идёт через
> `link_preview_options` (aiogram 3.x). В вопросе оно упомянуто как историческое имя.

`MarkupVariant = ForceReply | InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove`
(`new_message.py:16`).

### 2.2 `OldMessage` — «что сейчас на экране» (снимок)

`src/aiogram_dialog/api/entities/new_message.py:28`. `@dataclass`. Это НЕ aiogram `Message` —
это лёгкий слепок, который ядро хранит в `Stack` между апдейтами (см. §5).

| Поле | Тип | Назначение |
|---|---|---|
| `chat` | `Chat` | где сообщение |
| `message_id` | `int` | id предыдущего сообщения диалога |
| `media_id` | `str \| None` | `file_id` текущего медиа (если было) |
| `media_uniq_id` | `str \| None` | `file_unique_id` текущего медиа |
| `text` | `str \| UnknownText \| None` | текст/caption; `UnknownText.UNKNOWN` — когда текст недоступен (восстановлено из Stack) |
| `has_protected_content` | `bool \| None` | защищён ли контент |
| `has_reply_keyboard` | `bool` | была ли reply-клавиатура |
| `business_connection_id` | `str \| None` | business |
| `content_type` | `ContentType \| None` | тип контента (нужно для проверки voice) |

`UnknownText(Enum)` (`new_message.py:24`) — sentinel. Когда `OldMessage` восстанавливается из
`Stack` (а не из живого `Message`), реального текста у нас нет → `text=UnknownText.UNKNOWN`.
Это влияет на дифф (см. подводный камень про текст).

### 2.3 `MediaAttachment`

`src/aiogram_dialog/api/entities/media.py:20`. Обычный класс (не dataclass).

```python
MediaAttachment(
    type: ContentType,            # PHOTO/VIDEO/DOCUMENT/AUDIO/ANIMATION/VOICE/...
    url: str | None = None,       # URL или кастомный URI (см. get_media_source)
    path: str | Path | None = None,  # путь в ФС
    file_id: MediaId | None = None,  # уже загруженный в Telegram файл
    use_pipe: bool = False,       # для url: True → стримить через URLInputFile, False → отдать URL Телеграму
    **kwargs,                     # доп. параметры метода send_*/InputMedia* (duration, width, spoiler, ...)
)
```

- Конструктор требует, чтобы был задан хотя бы один из `url`/`path`/`file_id`, иначе
  `ValueError("Neither url nor path not file_id are provided")` (`media.py:30`).
- `kwargs` пробрасываются в `send_*` (`message_manager.py:432`) и в `InputMedia*`
  (`message_manager.py:379`). Сюда кладут `spoiler`, `duration`, `width`/`height`, `thumbnail`
  и т.п.
- `__eq__` сравнивает ВСЕ поля включая `kwargs` и `use_pipe` (`media.py:39`).
- В виджетах формируется `StaticMedia` (`widgets/media/static.py`) и `DynamicMedia`. Параметр
  `media_params` виджета → это `**kwargs` у `MediaAttachment`.

### 2.4 `MediaId`

`src/aiogram_dialog/api/entities/media.py:7`. `@dataclass`.

```python
MediaId(file_id: str, file_unique_id: str | None = None)
```

Кастомный `__eq__` (`media.py:12`) — **ключевая деталь**:
- если у одного из объектов `file_unique_id is None` → сравнение по `file_id`;
- иначе сравнение ТОЛЬКО по `file_unique_id` (а не по `file_id`!).

Зачем: Telegram выдаёт **разные `file_id`** для одного и того же файла в разных чатах/типах,
но `file_unique_id` стабилен. Поэтому дифф медиа корректно работает по `file_unique_id`, когда
он известен.

---

## 3. `MessageManager` — реализация и алгоритм решения

`src/aiogram_dialog/manager/message_manager.py:78`

### 3.1 Таблицы методов

- `SEND_METHODS` (`:36`) — `ContentType → имя bot.send_*`. Поддержаны: ANIMATION, AUDIO,
  DOCUMENT, PHOTO, VIDEO, VIDEO_NOTE, DICE, STICKER, VOICE.
- `INPUT_MEDIA_TYPES` (`:48`) — `ContentType → InputMedia*` для **edit**. Поддержаны ТОЛЬКО:
  ANIMATION, DOCUMENT, AUDIO, PHOTO, VIDEO. → VIDEO_NOTE/STICKER/VOICE/DICE **нельзя
  отредактировать как медиа**, только послать заново.

### 3.2 `show_message()` — диспетчер (`:168`)

Порядок ветвлений (читать строго сверху вниз):

1. `show_mode is NO_UPDATE` → `raise MessageNotModified` (`:172`). Ничего не делаем.
2. Есть `old_message` И `show_mode is DELETE_AND_SEND` → удалить старое + послать новое
   (`:175`). Порядок оптимизирован «чтобы не моргало»: если новое с reply-клавиатурой —
   сначала send, потом delete; иначе сначала delete, потом send (`:181-186`).
3. Нет `old_message` ИЛИ `show_mode is SEND` → убрать клавиатуру у старого (`_remove_kbd`) и
   послать новое (`:188`).
4. `not _message_changed(...)` → вернуть `old_message` как есть (ничего не поменялось)
   (`:200`). **Сообщение в Bot API не трогается вообще.**
5. `not _can_edit(...)` → удалить старое + послать новое (`:205`).
6. Иначе → `edit_message_safe(...)` (`:211`).

Возврат: `_combine(new_message, message_result)` (`:61`) — строит `OldMessage` из
aiogram-`Message`, вытаскивая `media_id`/`media_uniq_id` через `utils.get_media_id()`
(`message_manager.py:62`).

### 3.3 `_message_changed()` — дифф (`:129`)

Возвращает `True` (есть изменения, надо обновлять), если выполнено ЛЮБОЕ:
- `new.text != old.text`;
- `new.reply_markup or old.has_reply_keyboard` — **клавиатуры сравнить нельзя**, поэтому при
  наличии любой считаем «изменилось» (консервативно);
- `new.link_preview_options` задан — не знаем, изменилось ли превью → считаем «изменилось»;
- `bool(new.protect_content) != bool(old.has_protected_content)`;
- `had_media(old) != need_media(new)` — появилось/исчезло медиа;
- если медиа нужно и `new.media.file_id != MediaId(old.media_id, old.media_uniq_id)` —
  изменился файл (по правилам `MediaId.__eq__`).

### 3.4 `_can_edit()` — можно ли редактировать (`:155`)

`False` (нельзя редактировать, надо delete+send), если:
- было медиа, а теперь нет (`had_media and not need_media`) — медиа из сообщения не убрать
  редактированием;
- было ИЛИ нужно `voice` (`had_voice or need_voice`) — voice не редактируется;
- была ИЛИ нужна reply-клавиатура (`had_reply_keyboard or need_reply_keyboard`) — reply-кб
  нельзя добавить/убрать редактированием inline-сообщения.

### 3.5 `edit_message()` — выбор способа правки (`:321`)

1. Если `protect_content` различается → нельзя отредактировать → delete + send (`:324`).
2. Если есть медиа:
   - тот же файл (`new.media.file_id == old.media_id`) → `edit_caption` (правим только подпись)
     (`:331`);
   - иначе → `edit_media` (`InputMedia*` + `edit_message_media`) (`:335`).
3. Нет медиа → `edit_text` (`:337`).

> Тонкость `edit_caption` vs `edit_media`: сравнение здесь `new.media.file_id == old.media_id`,
> где `old.media_id` — это `str` (`file_id`), а слева `MediaId`. Работает за счёт
> `MediaId.__eq__`, который при сравнении с не-`MediaId` возвращает `False`… на самом деле
> справа `str`, поэтому `MediaId.__eq__` вернёт `False` → пойдёт `edit_media`. То есть путь
> «тот же файл → edit_caption» срабатывает фактически только когда `new.media.file_id`
> равен строке (редкий путь). В обычном потоке caption-only обновление достигается тем, что
> `_message_changed` вернёт `True` по тексту, а файл совпадает по `file_unique_id`, и
> `edit_media` перезальёт. Учитывать при отладке «мигающего» медиа.

### 3.6 Send-методы

- `send_message()` (`:389`) → `send_media` если есть медиа, иначе `send_text`.
- `send_text()` (`:395`): `bot.send_message(...)` со всеми полями + `link_preview_options`.
- `send_media()` (`:412`): берёт метод из `SEND_METHODS`, если нет — `ValueError(... not
  supported)`. Передаёт `caption=new.text`, `**new.media.kwargs`.

### 3.7 `get_media_source()` — ТОЧКА КАСТОМИЗАЦИИ (`:92`)

```python
async def get_media_source(self, media: MediaAttachment, bot: Bot) -> InputFile | str:
    if media.file_id:                 # уже в Telegram → отдаём строку file_id
        return media.file_id.file_id
    if media.url:
        if media.use_pipe:            # стримим через бота
            return URLInputFile(media.url, bot=bot)
        return media.url              # отдаём URL Телеграму (он сам скачает)
    else:
        return FSInputFile(media.path)  # файл из ФС
```

Переопределяя этот метод, реализуют кастомные источники (БД, S3, генерация на лету) — см.
`example/custom_media_url.py` и `docs/widgets/media/other_media_sources`.

### 3.8 Удаление и снятие клавиатуры

- `remove_kbd()` (`:217`): public API для ядра. `NO_UPDATE` → `None`; `DELETE_AND_SEND` (+есть
  старое) → `remove_message_safe`; иначе `_remove_kbd`.
- `_remove_kbd()` (`:229`): если была reply-кб и новая не нужна → `remove_reply_kbd`; если была
  reply-кб и нужна → `None`; иначе → `remove_inline_kbd`.
- `remove_inline_kbd()` (`:242`): `bot.edit_message_reply_markup(...)`; глушит 4 типа ошибок:
  `message is not modified`, `message can't be edited`, `message to edit not found`,
  `MESSAGE_ID_INVALID` (`:254-262`).
- `remove_reply_kbd()` (`:266`): шлёт служебное `"..."` с `ReplyKeyboardRemove()` (reply-кб
  иначе не убрать) (`:272`).
- `remove_message_safe()` (`:282`): если `business_connection_id` — НЕ удаляет (Bot API не
  даёт удалять в business), только снимает клавиатуру (`:288`). Иначе `bot.delete_message`;
  глушит `message to delete not found`; при `message can't be deleted` → фолбэк на снятие
  клавиатуры (`:296-300`).

### 3.9 Edit-safe и обработка «not modified»

`edit_message_safe()` (`:305`):
- `message is not modified` → `raise MessageNotModified` (наверх, ядро не сохранит) (`:311`).
- `message can't be edited` / `message to edit not found` → фолбэк на `send_message` (`:313`).
- прочее → `raise`.

### 3.10 `answer_callback()` (`:79`)

`bot.answer_callback_query(...)`; ловит `TelegramAPIError`, и если сообщение про «query is too
old … or query id is invalid» — логирует warning и проглатывает; иначе пробрасывает
(`:86-90`). Константа `_INVALID_QUERY_ID_MSG` (`:56`).

---

## 4. `MediaIdStorage` — кеш file_id

`src/aiogram_dialog/context/media_storage.py:16` (реализует `MediaIdStorageProtocol`,
`api/protocols/media.py:9`).

Зачем: один и тот же файл (path/url) не перезаливать в Telegram повторно — после первой
отправки сохраняем выданный `file_id` и в следующий раз подставляем его в `MediaAttachment`.

### Протокол `MediaIdStorageProtocol`

| Метод | Сигнатура | Возврат |
|---|---|---|
| `get_media_id` | `async (self, path, url, type: ContentType) -> MediaId \| None` | кешированный `MediaId` или `None` |
| `save_media_id` | `async (self, path, url, type, media_id: MediaId) -> None` | — |

### Реализация

- Кеш: `cachetools.LRUCache(maxsize=10240)` по умолчанию (`:18`). Ключ — кортеж
  `(path, url, type)`. Значение — `CachedMediaId(media_id, mtime)` (`:11`).
- `get_media_id` (`:20`): если нет ни path, ни url → `None`. Если в кеше есть и записан `mtime`
  (т.е. был path), сверяет текущий `mtime` файла; **если файл изменился — возвращает `None`**
  (заставит перезалить) (`:35-38`). Для url `mtime is None` — кеш бессрочный.
- `_get_file_mtime` (`:41`): `None`, если path пуст или файла нет; иначе `os.path.getmtime`.
- `save_media_id` (`:48`): пишет в кеш с текущим `mtime` файла.

### Как ядро это использует (`manager.py`)

- ПЕРЕД показом: `_fix_cached_media_id(new_message)` (`manager.py:427`). Если у медиа НЕ задан
  `file_id`, подставляет кешированный: `new_message.media.file_id = await
  media_id_storage.get_media_id(path, url, type)` (`:430`).
- ПОСЛЕ показа: если было медиа, `save_media_id(path, url, type, MediaId(sent.media_id,
  sent.media_uniq_id))` (`manager.py:408-416`).

> Кеш — in-memory и пер-процесс. При нескольких воркерах/рестарте каждый прогревается заново
> (это безопасно — просто лишний первый аплоад). Для DELETE_AND_SEND кеш по-прежнему экономит
> аплоад, т.к. `file_id` сохраняется.

---

## 5. Связь с `Stack` и жизненным циклом (ядро)

`OldMessage` живёт между апдейтами не целиком, а разложенным по полям `Stack`
(`api/entities/stack.py:42-51`): `last_message_id`, `last_reply_keyboard`, `last_media_id`,
`last_media_unique_id`, `last_income_media_group_id`, `content_type`, `has_protected_content`.

- `_save_last_message(OldMessage)` (`manager.py:501`) — раскладывает снимок в Stack.
- `_get_last_message()` (`manager.py:475`) — собирает `OldMessage` обратно. Если событие —
  `CallbackQuery` и есть живой `message`, берёт реальные данные (включая `text`); иначе
  восстанавливает из Stack с `text=UnknownText.UNKNOWN` (`:492`).
- `_calc_show_mode()` (`manager.py:510`) — превращает `AUTO` в конкретный режим:
  - не приватный чат → `EDIT`;
  - была reply-кб → `DELETE_AND_SEND`;
  - не дефолтный стек → `EDIT`;
  - входящее `Message` без media_group → `SEND`; с media_group == прошлой → `EDIT`; иначе
    `SEND`; всё прочее → `EDIT`.

`ShowMode` устанавливается на `NewMessage` в `show()` ДО `show_message` (`manager.py:390-392`),
поэтому менеджер всегда получает уже разрешённый режим (никогда `AUTO` на практике, но в
`show_message` ветка для `AUTO` отсутствует — она схлопывается в «edit», т.к. не совпала ни с
NO_UPDATE/DELETE_AND_SEND/SEND).

`_ensure_stack_compatible` (`manager.py:370`) запрещает `ReplyKeyboardMarkup` в не-дефолтном
стеке (`InvalidKeyboardType`).

---

## 6. Как подменить MessageManager / MediaIdStorage

`src/aiogram_dialog/setup.py:221`

```python
setup_dialogs(
    router,
    message_manager=MyMessageManager(),      # default: MessageManager()
    media_id_storage=MyMediaIdStorage(),     # default: MediaIdStorage()
    ...
)
```

Если не передать — создаются дефолты (`setup.py:181-184`). Передаются в
`DefaultManagerFactory`, который кладёт их в каждый `DialogManager`
(`manager_factory.py:33-34`, `manager.py:84-85`).

> Нельзя передавать одновременно `dialog_manager_factory` и `message_manager`/
> `media_id_storage`: если задан кастомный factory, `message_manager`/`media_id_storage`
> игнорируются (`setup.py:179-180` — ранний `return`).

### Пример: кастомный источник медиа (custom URI)

`example/custom_media_url.py:58` — генерация PNG «на лету» по URI `my://...`:

```python
class CustomMessageManager(MessageManager):
    async def get_media_source(self, media, bot):
        if media.file_id:
            return await super().get_media_source(media, bot)
        if media.url and media.url.startswith("my://"):
            text = media.url[len("my://"):]
            return BufferedInputFile(draw(text), f"{text}.png")
        return await super().get_media_source(media, bot)
```

Кеш `file_id` при этом продолжает работать: первый показ генерит и заливает картинку, дальше
ядро подставляет `file_id` (через `_fix_cached_media_id`) и `get_media_source` уже вернёт
`file_id`, минуя генерацию.

### Скелет ретраев/троттлинга

```python
class ResilientMessageManager(MessageManager):
    async def show_message(self, bot, new_message, old_message):
        for attempt in range(3):
            try:
                return await super().show_message(bot, new_message, old_message)
            except TelegramRetryAfter as e:        # flood control
                await asyncio.sleep(e.retry_after)
            # MessageNotModified пробрасываем дальше — это НЕ ошибка
        return await super().show_message(bot, new_message, old_message)
```

> Не глушите `MessageNotModified` в обёртке — ядро на нём строит логику «не сохранять id».
> Глушите/ретраите только сетевые/flood-ошибки (`TelegramRetryAfter`, `TelegramNetworkError`).

---

## 7. Тестирование: `MockMessageManager`

`src/aiogram_dialog/test_tools/mock_message_manager.py:57` (экспортируется из
`aiogram_dialog.test_tools`). Реализует протокол, не ходит в сеть, копит `sent_messages`.

Полезное API: `one_message()`, `first_message()`, `last_message()`, `assert_one_message()`,
`reset_history()`, `assert_answered(callback_id)`, `answered_callbacks`. Медиа подделывается
через `MEDIA_CLASSES` (`:38`), `file_id`/`file_unique_id` генерируются `uuid4`, если не заданы.

Пример (`tests/widgets/media/test_media_message.py`): отправляют `/url` и `/path`, проверяют
`message_manager.one_message().photo`.

Тест кеша `tests/widgets/media/test_media_storage.py`: сохранили `file_id`, прочитали — есть;
изменили файл (другой `mtime`) — `get_media_id` вернул `None` (инвалидация по mtime).

---

## 8. Подводные камни и краевые случаи

| # | Ситуация | Поведение / совет |
|---|---|---|
| 1 | «message is not modified» | На edit → `MessageNotModified`, ядро НЕ перезаписывает id (`message_manager.py:311`, `manager.py:401`). Не оборачивайте это как ошибку. |
| 2 | Удаление недоступного/старого сообщения | `remove_message_safe` глушит «to delete not found», на «can't be deleted» снимает клавиатуру (`:296`). Telegram не даёт удалять сообщения старше 48 ч → для них DELETE_AND_SEND превратится в send без удаления (останется хвост). |
| 3 | Business-аккаунт | `delete_message` недоступен → `remove_message_safe` только снимает клавиатуру (`:288`). Старые сообщения не подчищаются. |
| 4 | edit media vs text | Появление/исчезновение медиа или voice → редактировать НЕЛЬЗЯ, идёт delete+send (`_can_edit`, `:155`). Reply-клавиатура (в т.ч. её снятие) тоже всегда delete+send. |
| 5 | Неподдержанный тип на edit | `INPUT_MEDIA_TYPES` не содержит VIDEO_NOTE/STICKER/VOICE/DICE — их нельзя `edit_media`. VOICE отдельно блокируется в `_can_edit`. Прочие при попытке edit упадут `KeyError` (`:374`) — но в норме сюда не доходят, т.к. меняется тип медиа → `_message_changed`/`_can_edit` уводят в send. |
| 6 | Неподдержанный тип на send | `send_media` → `ValueError(... not supported)` если типа нет в `SEND_METHODS` (`:419`). |
| 7 | Сравнение медиа | Идёт по `file_unique_id`, когда он есть (`MediaId.__eq__`, `media.py:12`). Если кешируете/подставляете `MediaId` без `file_unique_id`, сравнение упадёт на `file_id`, а он у Telegram нестабилен между чатами → лишние перезаливы или ложное «не изменилось». Всегда сохраняйте оба id. |
| 8 | `OldMessage.text == UnknownText.UNKNOWN` | Когда восстановлено из Stack (не из живого callback-сообщения), реальный текст неизвестен → `new.text != UnknownText.UNKNOWN` почти всегда `True` → дифф решит «изменилось». Это by design (лучше лишний edit, чем пропустить). |
| 9 | `link_preview_options` всегда триггерит дифф | Если задан `link_preview_options` (даже идентичный) → `_message_changed` вернёт `True` (`:137`), будет лишний edit. Не задавайте превью без необходимости в окнах, которые часто перерисовываются. |
| 10 | Reply-клавиатуры | Любое сообщение с reply-кб → дифф всегда «изменилось» и `_can_edit==False` → всегда DELETE_AND_SEND/send (мигание). Reply-кб запрещены в не-дефолтном стеке (`InvalidKeyboardType`). |
| 11 | `media_id` кеш и mtime | Для `path` кеш инвалидируется при изменении mtime файла. Если файл генерится с одинаковым именем, но меняется содержимое БЕЗ изменения mtime — отдастся устаревший `file_id`. Для `url` кеш бессрочный (mtime=None) — меняйте URI при смене контента. |
| 12 | `parse_mode` | Передаётся как есть в send/edit. В окне дефолт — `UNSET_PARSE_MODE` (`window.py:49`), т.е. берётся глобальный `Bot.default.parse_mode`. |
| 13 | DELETE_AND_SEND порядок | При reply-кб сначала send, потом delete (`:181`) — иначе на момент удаления у пользователя пропадёт клавиатура. Если переопределяете `show_message`, сохраняйте этот порядок. |
| 14 | Кеш — in-memory | `MediaIdStorage` не персистентный и не общий между процессами. Для шаблона с несколькими воркерами это ОК (каждый прогреется), но если нужна общая экономия аплоадов — реализуйте `MediaIdStorageProtocol` поверх Redis/БД. |

---

## 9. Карта связей с библиотекой

- `Window.render()` (`window.py:162`) → строит `NewMessage`. Медиа берётся из
  `render_media` (виджеты `StaticMedia`/`DynamicMedia`, `widgets/media/`), которые создают
  `MediaAttachment` (с `media_params` → `**kwargs`).
- `DialogManager.show()` (`manager.py:380`) — оркестратор: проставляет `show_mode`,
  `_fix_cached_media_id`, зовёт `show_message`, сохраняет результат в Stack, кеширует file_id.
- `setup_dialogs` / `DefaultManagerFactory` / `manager_factory.py` — внедрение зависимостей.
- `utils.get_media_id(message)` (`utils.py:178`) — извлекает `MediaId` из aiogram `Message`
  (приоритет: audio → animation → document → photo[-1] → video → voice); для
  `InaccessibleMessage` → `None`. Используется в `_combine` и `_get_message_from_callback`.
- `MockMessageManager` / `BotClient` (`test_tools`) — тестовый стенд без сети.
