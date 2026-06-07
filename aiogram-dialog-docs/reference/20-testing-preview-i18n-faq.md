---
title: "Зона 20 — Инструменты тестирования, preview, i18n, FAQ, миграция, архитектура mega"
zone: 20
source_repo: /tmp/aiogram_dialog
source_rev: "develop, 08abdf0, 2026-05-02"
aiogram_min: ">=3.14.0"
scope:
  - src/aiogram_dialog/test_tools/*  (BotClient, MockMessageManager, keyboard, memory_storage)
  - src/aiogram_dialog/tools/*  (preview, web_preview, transitions, about)
  - docs/helper_tools/index.rst, docs/faq.rst, docs/migration.rst
  - example/i18n/*, example/mega/*, example/{wizard,subdialog,multistack,launch_modes}.py
status: reference
lang: ru
---

# Зона 20. Тестирование, preview, i18n, FAQ, миграция, архитектура mega-примера

Эта зона покрывает инфраструктуру вокруг диалогов: как писать unit-тесты без реального
Telegram (`test_tools`), как визуализировать диалоги (`tools` — preview/transitions),
встроенный диалог «About», интеграцию i18n, частые вопросы (FAQ), breaking changes
между версиями и каноничную архитектуру многодиалогового бота (`example/mega`).

---

## 1. Инструменты тестирования — `aiogram_dialog.test_tools`

Публичный экспорт пакета — только два имени (`test_tools/__init__.py:1`):

```python
from aiogram_dialog.test_tools import BotClient, MockMessageManager
```

Остальное (`InlineButton*Locator`, `JsonMemoryStorage`) импортируется по полному пути:

```python
from aiogram_dialog.test_tools.keyboard import (
    InlineButtonTextLocator, InlineButtonPositionLocator, InlineButtonDataLocator,
)
from aiogram_dialog.test_tools.memory_storage import JsonMemoryStorage
```

Идея тестов: вместо реального бота поднимается обычный `Dispatcher`, в `setup_dialogs`
подсовывается `MockMessageManager` (перехватывает «отправленные» сообщения, не ходит в
Telegram), а события (сообщения/нажатия) скармливаются через `BotClient`, который вызывает
`dp.feed_update(...)` — то есть прогоняется весь реальный пайплайн middleware/фильтров/диалогов.

### 1.1. `BotClient` — тестовый клиент

Файл `src/aiogram_dialog/test_tools/bot_client.py`.

```python
class BotClient:
    def __init__(
        self,
        dp: Dispatcher,
        user_id: int = 1,
        chat_id: int = 1,
        chat_type: str = "private",
        bot: Bot | None = None,
    ): ...
```
`bot_client.py:60`. Создаёт фиктивных `Chat(id=chat_id, type=chat_type)` и
`User(id=user_id, is_bot=False, first_name=f"User_{user_id}")`. Если `bot` не передан —
подставляется `FakeBot()`. Хранит автоинкрементные `last_update_id`/`last_message_id` (оба с 1).

| Метод | Сигнатура | Что делает | Возврат |
|---|---|---|---|
| `send` | `async send(text: str, reply_to: Message \| None = None)` | Формирует `Message` (новый `message_id`, фикс. дата `1234567890`, `from_user`/`chat` клиента, `reply_to_message=reply_to`) и подаёт `Update(message=...)` в `dp.feed_update`. | Результат `feed_update` (`bot_client.py:99`) |
| `click` | `async click(message: Message, locator: InlineButtonLocator) -> str` | Находит кнопку через `locator.find_button(message)`; если нет — `ValueError`. Формирует `CallbackQuery` (`id=uuid4()`, `data=button.callback_data`) и подаёт `Update(callback_query=...)`. | `callback.id` (str) — id для `assert_answered` (`bot_client.py:118`) |
| `request_chat_join` | `async request_chat_join()` | Подаёт `Update(chat_join_request=ChatJoinRequest(...))`. | результат `feed_update` (`bot_client.py:135`) |
| `my_chat_member_update` | `async my_chat_member_update(old_chat_member, new_chat_member)` | Подаёт `Update(my_chat_member=ChatMemberUpdated(...))`. Тип `ChatMember` — union всех `ChatMemberOwner/Administrator/Member/Restricted/Left/Banned` (`bot_client.py:51`). | результат `feed_update` (`bot_client.py:146`) |

Внутренние: `_new_update_id`, `_new_message_id`, `_new_message`, `_new_callback`.
В `_new_callback` есть проверка `if not button.callback_data: raise ValueError` — то есть
кликать можно только по кнопкам с callback_data (не по `Url`/`WebApp`/реплай-кнопкам).

**Ввод текста** делается тем же `send("любой текст")` — он попадёт в `MessageInput`/`TextInput`
активного окна. Отдельного метода для нажатия reply-кнопок нет; reply-кнопки aiogram-dialog
кодирует callback в невидимые символы внутри текста (см. `split_reply_callback`,
`utils.py:76`), так что в тесте можно `client.send(<текст_reply_кнопки>)`.

#### `FakeBot` (`bot_client.py:27`)

Подкласс `Bot`, который **не вызывает** `super().__init__()` — это намеренно «битый» бот-заглушка.
`id == 1`. `__call__`: на `AnswerCallbackQuery` возвращает `True`, на всё остальное —
`RuntimeError("Fake bot should not be used to call telegram")`. Реальные отправки сообщений
перехватываются раньше — на уровне `MockMessageManager`, поэтому до `FakeBot.__call__` они
не доходят. `__hash__`/`__eq__` переопределены, чтобы экземпляр можно было класть в словари aiogram.

### 1.2. `MockMessageManager` — перехват отправленных сообщений

Файл `src/aiogram_dialog/test_tools/mock_message_manager.py`. Реализует
`MessageManagerProtocol` (`api/protocols/message_manager.py:16`): три async-метода
`remove_kbd`, `show_message`, `answer_callback`. Передаётся в `setup_dialogs(dp, message_manager=...)`.

Состояние:
- `sent_messages: list[Message]` — все «отправленные»/«отредактированные» сообщения по порядку;
- `answered_callbacks: set[str]` — id отвеченных callback'ов;
- `last_message_id: int`.

| Метод/хелпер | Назначение |
|---|---|
| `reset_history()` | Очистить `sent_messages` и `answered_callbacks`. Вызывать между шагами теста (`mock_message_manager.py:63`). |
| `assert_one_message()` | `assert len(sent_messages) == 1`. |
| `last_message()` / `first_message()` | `sent_messages[-1]` / `sent_messages[0]`. |
| `one_message() -> Message` | Проверяет, что ровно одно сообщение, и возвращает его. **Главный хелпер** проверки «что показано». |
| `assert_answered(callback_id)` | `assert callback_id in answered_callbacks`. |

Поведение реализаций протокола:
- `show_message(bot, new_message, old_message)` (`:109`): если `new_message.show_mode is ShowMode.NO_UPDATE` — бросает `MessageNotModified` (имитация «нечего обновлять»). Иначе инкрементит `last_message_id`, строит `aiogram.types.Message`. Для медиа берёт `MEDIA_CLASSES[media.type]` (audio/document/photo/video — фабрики фейковых объектов с `file_id`/`file_unique_id`, для photo это `[PhotoSize(...)]`), текст кладёт в `caption`; без медиа — в `text`. Возвращает `OldMessage` (с `media_id`, `media_uniq_id`, `has_reply_keyboard`, `business_connection_id=None`).
- `remove_kbd(bot, show_mode, old_message)` (`:80`): при `show_mode in (DELETE_AND_SEND, NO_UPDATE)` или отсутствии `old_message` → `None`. Иначе добавляет в историю сообщение с `reply_markup=None` (имитация снятия клавиатуры).
- `answer_callback(bot, callback_query)` (`:101`): кладёт `callback_query.id` в `answered_callbacks`.

`file_id(media)`/`file_unique_id(media)` (`:24`,`:31`) — берут id из `media.file_id` либо
генерируют `uuid4()`. `reply_markup` копируется через `deepcopy` (важно: проверки в тесте
не «портят» исходную разметку).

### 1.3. Локаторы кнопок — `test_tools/keyboard.py`

Протокол `InlineButtonLocator.find_button(message) -> InlineKeyboardButton | None` (`keyboard.py:7`).
Все локаторы ищут только по `message.reply_markup.inline_keyboard` (для reply-клавиатуры не
подходят) и возвращают `None`, если `reply_markup` отсутствует.

| Локатор | Конструктор | Поиск |
|---|---|---|
| `InlineButtonTextLocator(regex)` | regex по тексту | `regex.fullmatch(button.text)` — **fullmatch**, не search! `InlineButtonTextLocator("Next")` совпадёт только с кнопкой ровно `Next`. (`keyboard.py:14`) |
| `InlineButtonPositionLocator(row, column)` | индексы | `inline_keyboard[row][column]`, `IndexError → None` (`keyboard.py:33`) |
| `InlineButtonDataLocator(regex)` | regex по callback_data | `regex.fullmatch(button.callback_data)`, кнопки без callback_data пропускаются (`keyboard.py:53`) |

**Подводный камень:** `fullmatch` означает, что для текста с эмодзи/пробелами нужно учитывать
весь текст: `InlineButtonTextLocator("Next")` не найдёт кнопку `"➡️ Next"` — используйте
`".*Next.*"` или `InlineButtonDataLocator`.

### 1.4. `JsonMemoryStorage` — `test_tools/memory_storage.py`

`BaseStorage` aiogram, хранящий данные в памяти, но **сериализующий их в JSON-строку**
(`json.dumps`/`json.loads`). Это важно: ловит ошибки несериализуемых значений в
`dialog_data` уже в тестах (реальные Redis/Mongo-сторэджи тоже требуют JSON-совместимости).

```python
@dataclass
class MemoryStorageRecord:
    data: str = "{}"
    state: str | None = None

class JsonMemoryStorage(BaseStorage):
    storage: dict[StorageKey, MemoryStorageRecord]  # defaultdict
```
`memory_storage.py:18`. `set_state` принимает `State|str|None` (для `State` берёт `.state`).
В отличие от штатного `MemoryStorage`, данные хранятся как строка — поэтому при `get_data`
возвращается новый объект (нет случайного шаринга мутабельного dict между обращениями).

### 1.5. Канонический шаблон unit-теста диалога

(см. `tests/test_transitions.py`, `tests/test_click.py`)

```python
import pytest
from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram_dialog import setup_dialogs
from aiogram_dialog.test_tools import BotClient, MockMessageManager
from aiogram_dialog.test_tools.keyboard import InlineButtonTextLocator
from aiogram_dialog.test_tools.memory_storage import JsonMemoryStorage

@pytest.fixture
def message_manager():
    return MockMessageManager()

@pytest.fixture
def dp(message_manager):
    dp = Dispatcher(storage=JsonMemoryStorage())
    dp.message.register(start, CommandStart())
    dp.include_router(my_dialog)
    setup_dialogs(dp, message_manager=message_manager)   # ключевая строка
    return dp

@pytest.fixture
def client(dp):
    return BotClient(dp)

@pytest.mark.asyncio
async def test_flow(dp, message_manager, client):
    await client.send("/start")
    msg = message_manager.one_message()
    assert msg.text == "First"

    message_manager.reset_history()
    cb_id = await client.click(msg, InlineButtonTextLocator("Next"))
    message_manager.assert_answered(cb_id)
    assert message_manager.one_message().text == "Second"
```

Зависимости (middleware-data) внедряются прямо в конструктор `Dispatcher(usecase=..., user_getter=...)`
и доступны в getter'ах/хендлерах как kwargs (`tests/test_click.py:67`).
`setup_dialogs` возвращает `BgManagerFactory` — его можно использовать для тестов background-обновлений.

### 1.6. `setup_dialogs` — релевантные параметры для тестов

`src/aiogram_dialog/setup.py:221`:
```python
def setup_dialogs(
    router, *,
    dialog_manager_factory=None,
    message_manager: MessageManagerProtocol | None = None,   # <- MockMessageManager в тестах
    media_id_storage=None,
    stack_access_validator=None,
    events_isolation: BaseEventIsolation | None = None,
    getter: DataGetter | None = None,
) -> BgManagerFactory
```
- Если `message_manager is None` → берётся реальный `MessageManager()` (`setup.py:184`).
- Если `events_isolation is None` → берётся **`SimpleEventIsolation()`** (`setup.py:201`,`:207`).
  Это значит, что concurrency-блокировка событий по чату гарантируется по умолчанию
  даже в тестах (см. `tests/test_isolation.py` — два одновременных `/start` обрабатываются
  строго по одному).
- `setup_dialogs` дополнительно включает **встроенный диалог About** через
  `_include_default_dialogs → about_dialog()` (`setup.py:217`). То есть после `setup_dialogs`
  в роутере появляется лишний диалог со state-group `AiogramDialogStates.ABOUT`.

**Подводные камни тестов:**
- Нужен `storage` у `Dispatcher` (FSM). `JsonMemoryStorage` или `MemoryStorage` — обязательно,
  иначе диалоги негде хранить контекст.
- `SimpleEventIsolation` подключается автоматически; явно передавать не нужно. Но если вы
  ставите собственную фабрику `dialog_manager_factory`, проверьте, что isolation/manager
  согласованы.
- `one_message()` падает, если показано 0 или >1 сообщения — между логическими шагами
  делайте `reset_history()`.
- При отправке пользователем своего сообщения диалог по умолчанию **перерисовывает окно
  новым сообщением** (см. FAQ ниже) — в тесте это проявится как новое `sent_messages`.

---

## 2. Preview и диаграммы переходов — `aiogram_dialog.tools`

Экстра-зависимости (`pyproject.toml:38`):
```toml
[project.optional-dependencies]
tools = ["diagrams", "aiohttp"]
```
Установка: `pip install aiogram_dialog[tools]`. Плюс системный **graphviz** для диаграмм
переходов (`docs/helper_tools/index.rst:9`). `jinja2` входит в основные зависимости.

Публичный экспорт (`tools/__init__.py`): `render_preview`, `render_transitions`.

### 2.1. Диаграмма переходов — `render_transitions`

`src/aiogram_dialog/tools/transitions.py:94`:
```python
def render_transitions(
    router: Router,           # Dispatcher / Router / Dialog
    title: str = "Aiogram Dialog",
    filename: str = "aiogram_dialog",
    format: str = "png",
)
```
Строит PNG-граф состояний. Через `collect_dialogs(router)` собирает все диалоги, на каждое
окно создаёт узел (`Custom` с иконкой `calculator.png`), затем рисует рёбра по
**анализируемым кнопкам-переходам**: `Start` (зелёное ребро), `SwitchTo`/`Next` (синее),
`Back` (серое), `Cancel` (серое пунктирное к точкам старта той же группы). `Group`
рекурсивно разворачивается (`walk_keyboard`, `transitions.py:46`).

**Ограничение:** инструмент не анализирует код callback'ов. Переходы, сделанные вручную
(`await manager.next()` в обработчике `MessageInput`/`Button.on_click`), на графе **не видны**.
Лечится подсказкой `preview_add_transitions` у `Window`:
```python
Window(..., MessageInput(on_input),
       preview_add_transitions=[Next()])  # подсказка только для рендера
```
(`docs/helper_tools/render_hints.py`; чтение этого атрибута — `transitions.py:81`).

### 2.2. HTML-preview окон — `render_preview`

`src/aiogram_dialog/tools/preview.py:484`:
```python
async def render_preview(router: Router, file: str, simulate_events: bool = False)
async def render_preview_content(router: Router, simulate_events: bool = False) -> str
```
Генерирует HTML-файл с «макетами» всех окон (как они будут выглядеть в Telegram), открывается
в браузере. Под капотом — `FakeManager` (полная заглушка `DialogManager`, `preview.py:75`),
который проходит по всем `group.__states__` каждого диалога, вызывает `manager.show_raw()` →
`dialog.render(manager)` и собирает `RenderDialog/RenderWindow/RenderButton` (dataclasses,
`preview.py:51-73`). Рендер в Jinja-шаблон `tools/templates/message.html` (узлы-окна с
кликабельными `<a href="#state">` для навигации, inline/reply-клавиатуры, отметки
`⌨️ TextInput` / `📎 MessageInput`).

Данные для рендера задаются параметром окна **`preview_data`** (статический dict или async-getter):
```python
Window(Format("Hello, {name}"), Cancel(),
       state=RenderSG.first,
       preview_data={"name": "Tishka17"})   # docs/helper_tools/preview_summary.py
```
`FakeManager.load_data()` возвращает `{}`, поэтому без `preview_data` в `Format`/`Jinja`
будут отсутствовать ключи. About-диалог использует `preview_data=metadata_getter` (`about.py:46`).

`simulate_events=True` (используется web-preview): `FakeManager` реально «прокликивает»
кнопки (`dialog._callback_handler`) и «вводит» текст/фото (`dialog._message_handler`), чтобы
определить целевые состояния переходов и нарисовать ссылки между окнами (`preview.py:276`,`:301`).
Исключения при симуляции глушатся (`logger.debug`), смена состояния детектируется сравнением
`manager.current_context().state`.

`FakeManager.is_preview() -> True` — внутри виджетов можно ветвиться на режим preview.

### 2.3. Web-preview (сервер) — `web_preview.py` и CLI

Консольная команда (entry point `pyproject.toml:50`):
```toml
[project.scripts]
aiogram-dialog-preview = "aiogram_dialog.tools.web_preview:main"
```
Запуск (`docs/helper_tools/web_preview.sh`):
```bash
aiogram-dialog-preview path/to/dir/package.module:object_or_callable
# пример:
aiogram-dialog-preview example/subdialog:dialog_router
```
`main()` (`web_preview.py:100`): разбирает аргумент `dir:module:object`, добавляет каталог в
`sys.path`, поднимает `aiohttp`-сервер на **порту 9876**:
- `GET /` → HTML-preview (`simulate_events=True`),
- `GET /transitions` → PNG-диаграмма.

`Renderer._get_router()` (`web_preview.py:26`) умеет принять как объект `Router/Dialog`, так и
функцию/корутину, возвращающую роутер. Рендер выполняется в **отдельном процессе**
(`ProcessPoolExecutor(max_workers=1)`) — чтобы перезагружать модуль и не держать состояние
между запросами. URL и логи печатаются в консоль (`INTRO`, `web_preview.py:82`).

**Подводные камни preview:**
- `render_preview`/`web_preview` требуют `aiogram_dialog[tools]` (`aiohttp`), `render_transitions`
  дополнительно — `diagrams` + системный graphviz.
- `render_transitions` принимает позиционно `Dispatcher/Router/Dialog`; в старых версиях ждал
  `Registry` (см. migration). В `example/subdialog.py:158` обе функции вызываются в `main()`
  **до** `setup_dialogs`.
- Без `preview_data` тексты с подстановкой ключей не отрендерятся корректно.
- В сниппете доки `render_preview.py` опечатка (`await render_transitions(dp, "preview.html")`),
  правильно — `render_preview` (как в `preview_summary.py`).

---

## 3. Встроенный диалог «About» — `about.py`

`src/aiogram_dialog/about.py`. Готовый диалог с информацией о библиотеке (имя, версия, автор,
ссылки) — данные тянутся из `importlib.metadata.metadata("aiogram-dialog")` в `metadata_getter`.

```python
class AiogramDialogStates(StatesGroup):
    ABOUT = State()

def about_dialog() -> Dialog: ...               # about.py:26
def about_aiogram_dialog_button(text=DEFAULT_ABOUT_BTN_TEXT) -> Keyboard:  # about.py:55
    return Start(text=text, state=AiogramDialogStates.ABOUT, id="__aiogd_about__")
```

- `about_dialog()` **автоматически** включается в роутер при `setup_dialogs`
  (`_include_default_dialogs`, `setup.py:217`). Отдельно регистрировать не нужно.
- `about_aiogram_dialog_button()` — готовая `Start`-кнопка для главного меню (mega-пример
  кладёт её в главное окно: `example/mega/bot_dialogs/main.py:56`). id зарезервирован
  `"__aiogd_about__"` — не переопределяйте.
- Окно использует `LinkPreview(is_disabled=True)`, `parse_mode="html"`, `preview_data=metadata_getter`.

В тестах учитывайте, что после `setup_dialogs` появляется лишний диалог-группа `ABOUT`
(влияет на `collect_dialogs`/`render_transitions`).

---

## 4. i18n-интеграция — `example/i18n`

Стандартный `Format`/`Jinja` не локализует текст. Подход примера: **кастомный текст-виджет
`I18NFormat`**, который рендерит **ключ перевода**, а функция форматирования берётся из
middleware-data по локали пользователя.

### 4.1. `I18NFormat` — `example/i18n/i18n_format.py`

```python
I18N_FORMAT_KEY = "aiogd_i18n_format"

class I18NFormat(Text):
    def __init__(self, text: str, when: WhenCondition = None):
        super().__init__(when)
        self.text = text
    async def _render_text(self, data: dict, manager: DialogManager) -> str:
        format_text = manager.middleware_data.get(I18N_FORMAT_KEY, default_format_text)
        return format_text(self.text, data)
```
- `self.text` — это **ключ** (`"Hello-user"`), не итоговая строка.
- Функция форматирования достаётся из `middleware_data[I18N_FORMAT_KEY]`; если её нет —
  фолбэк `default_format_text` = `text.format_map(data)` (просто подстановка по ключам data).
- Наследует `Text` и переопределяет `_render_text` — то есть это полноценный текст-виджет,
  кладётся в любое место `Window` вместо `Format`/`Const`.

### 4.2. Middleware локали — `example/i18n/i18n_middleware.py`

```python
class I18nMiddleware(BaseMiddleware):
    def __init__(self, l10ns: dict[str, FluentLocalization], default_lang: str): ...
    async def __call__(self, handler, event, data):
        lang = event.from_user.language_code if event.from_user else self.default_lang
        if lang not in self.l10ns:
            lang = self.default_lang
        data[I18N_FORMAT_KEY] = self.l10ns[lang].format_value   # ключевая строка
        return await handler(event, data)
```
Кладёт в `data[I18N_FORMAT_KEY]` функцию `format_value` нужной локали (`fluent.runtime`).
`format_value(key, kwargs)` совместима по сигнатуре с тем, что зовёт `I18NFormat._render_text`.

### 4.3. Сборка — `example/i18n/bot.py`

```python
dialog = Dialog(Window(
    I18NFormat("Hello-user"),
    Row(Button(I18NFormat("Demo-button"), id="demo"),
        Cancel(text=I18NFormat("Cancel"))),
    getter=get_data, state=DialogSG.greeting,
))

i18n_middleware = make_i18n_middleware()  # FluentResourceLoader + FluentLocalization
dp.message.middleware(i18n_middleware)
dp.callback_query.middleware(i18n_middleware)   # ОБА типа событий!
dp.include_router(dialog)
setup_dialogs(dp)
```
Переводы — `.ftl` (Fluent): `translations/en/main.ftl` (`Hello-user = Hello and welcome, { $name }!`).
Зависимость: `fluent.runtime` (не входит в библиотеку, ставить отдельно).

**Подводные камни i18n:**
- Middleware нужно вешать на `dp.message` **и** `dp.callback_query` — иначе при нажатии кнопки
  локаль не подставится и сработает фолбэк.
- `I18N_FORMAT_KEY` импортируйте из одного модуля и там, и там (общая константа).
- Текст рендерится **на каждый показ** (кеша перевода в самом виджете нет) — локаль всегда
  актуальна. Если вы добавите свой кеш текста — сломаете переключение языка.
- `I18NFormat` хранит ключ; подстановки `{ $name }` приходят из getter'а через `data`.
- Для не-Fluent движков (gettext/`aiogram.utils.i18n`) достаточно положить в `I18N_FORMAT_KEY`
  любую функцию `(key, data) -> str`.
- Локаль из `event.from_user.language_code` — при background-обновлениях `from_user` может
  содержать только `id` (см. FAQ/`load=True`), тогда подставится `default_lang`.

---

## 5. Архитектура mega-примера — `example/mega`

Эталон многодиалогового бота. Что брать в продакшн-шаблон.

Структура:
```
mega/
  bot.py                  # сборка Dispatcher, error-handler, корневой router
  bot_dialogs/
    __init__.py           # пустой
    states.py             # ВСЕ StatesGroup в одном месте
    common.py             # переиспользуемые виджеты (MAIN_MENU_BUTTON)
    main.py               # главное меню (LaunchMode.ROOT) + about-кнопка
    layouts.py, scrolls.py, select.py, calendar.py, counter.py,
    mutltiwidget.py, switch.py, reply_buttons.py, link_preview.py
  media/*.png
```

Ключевые принципы:

1. **`states.py` — единый каталог состояний** (`example/mega/bot_dialogs/states.py`). Все
   `StatesGroup` (`Main`, `Layouts`, `Scrolls`, `Selects`, `Calendar`, ...) собраны в одном
   модуле. Это разрывает циклические импорты между диалогами (каждый импортирует `from . import states`).

2. **Один файл — один диалог.** Каждый модуль экспортирует свой `*_dialog = Dialog(...)`.

3. **`common.py` — общие виджеты.** Например `MAIN_MENU_BUTTON = Start(text=Const("☰ Main menu"),
   id="__main__", state=states.Main.MAIN, style=Style(style="primary"))` — переиспользуется во
   всех под-диалогах для возврата в корень.

4. **`main.py` — корневой диалог** с `launch_mode=LaunchMode.ROOT` (`main.py:59`). Содержит
   `Start`-кнопки во все разделы и `about_aiogram_dialog_button()`.

5. **Регистрация — отдельный `Router` для диалогов** (`bot.py:63`):
   ```python
   dialog_router = Router()
   dialog_router.include_routers(layouts_dialog, scroll_dialog, main_dialog, ...)
   ...
   def setup_dp():
       dp = Dispatcher(storage=MemoryStorage())
       dp.message.register(start, F.text == "/start")
       dp.business_message.register(start, F.text == "/start")    # бизнес-аккаунты
       dp.errors.register(on_unknown_intent, ExceptionTypeFilter(UnknownIntent))
       dp.include_router(dialog_router)
       setup_dialogs(dp)                                          # последним
       return dp
   ```

6. **Обработка `UnknownIntent`** (`bot.py:37`) — обязателен для продакшна. После рестарта
   процесса/потери контекста старые callback'и приходят с неизвестным intent; хендлер
   отвечает на callback, удаляет старое сообщение и `start(Main.MAIN, mode=RESET_STACK, show_mode=SEND)`.

7. **`/start` всегда `StartMode.RESET_STACK` + `ShowMode.SEND`** — чистый рестарт со свежим сообщением.

8. **Layout-паттерн** (`layouts.py`): общие виджеты `SELECT`/`BUTTON` объявляются как
   модульные константы и **переиспользуются** в нескольких окнах внутри `Row`/`Column`/`Group(width=2)`.
   Одну и ту же кнопку-виджет можно класть в несколько окон.

Порядок сборки критичен: `setup_dialogs(dp)` — **после** `include_router(dialog_router)`,
так как навешивает middleware на уже собранное дерево роутеров.

---

## 6. Паттерны из топ-уровневых примеров

### 6.1. `wizard.py` — пошаговый мастер с возвратом к preview

- `TextInput(id=..., on_success=next_or_end)` — ввод полей; общий callback `next_or_end`
  ветвится: если `dialog_data[FINISHED_KEY]` → `switch_to(preview)`, иначе `next()`.
  То есть после первого прохода «Изменить поле» возвращает сразу к итоговому окну.
- `CANCEL_EDIT = SwitchTo(..., when=F["dialog_data"][FINISHED_KEY], ...)` — кнопка видна
  только после завершения (через `when` с magic-filter по `dialog_data`).
- Итоговое окно с `getter=result_getter`, который собирает значения через
  `manager.find("title").get_value()`, `manager.find("pink").is_checked()` и **выставляет**
  `dialog_data[FINISHED_KEY] = True` прямо в getter'е.

### 6.2. `subdialog.py` — передача данных между диалогами

- Запуск под-диалога: `Start(..., state=NameSG.input)`; внутри финал — `manager.done({"name": ...})`.
- Приём результата в родителе: `Dialog(..., on_process_result=process_result)`, где
  `process_result(start_data, result, manager)`.
- В примере же вызываются `render_transitions(dp)` и `await render_preview(dp, "preview.html")`
  до `setup_dialogs` — генерация артефактов при старте.
- `preview_add_transitions=[Next()]/[Cancel()]` и `preview_data={...}` — подсказки рендеру.

### 6.3. `multistack.py` — несколько стеков в одном чате

- `Start(..., mode=StartMode.NEW_STACK)` / `dialog_manager.start(..., mode=StartMode.NEW_STACK)` —
  создаёт **параллельный стек** диалогов в том же чате.
- Важный комментарий из примера (`multistack.py:87`): *inputs работают только в default-стеке
  или через reply на сообщение с кнопками*. То есть `MessageInput`/`TextInput` в неосновном
  стеке без reply не сработают.
- Getter отдаёт `current_stack()`/`current_context()` для отладки.

### 6.4. `launch_modes.py` — `LaunchMode`

| LaunchMode | Поведение |
|---|---|
| `ROOT` | Корневой; при старте можно не чистить стек — он становится основанием. |
| `EXCLUSIVE` | Баннер/блокирующий — поверх всего. |
| `SINGLE_TOP` | Если диалог уже на вершине и стартует свою копию — заменяет себя ею (нет дублей в стеке). |
| `STANDARD` | (по умолчанию) обычное добавление в стек. |

---

## 7. FAQ — сжатая выжимка (`docs/faq.rst`)

| Вопрос | Ответ |
|---|---|
| Получить значение stateful-виджета (`Checkbox`, `Multiselect`) | Глобальная ссылка: `widget.get_checked(manager)`; или по id: `manager.dialog().find("id").get_checked()`. |
| Что такое `widget_data`? | Внутреннее хранилище виджетов; **не трогать напрямую**, использовать методы виджета. |
| Дефолт для `Multiselect`/`Radio` | Выставлять в `on_start` диалога. |
| `Select` в несколько строк / пагинация | Обернуть в `Group`/`Column`/`ScrollingGroup`. |
| Кнопки из БД + пагинация | `Select` + `ScrollingGroup`, items грузить в window-getter. |
| Фото по `file_id` | Кастомный виджет по образцу `StaticMedia`. |
| Запрос локации/контакта | Reply-клавиатура + `MessageInput` для ответа. |
| Список URL-кнопок как Select | `ListGroup` + `Url`. |
| Не слать новое сообщение, когда пишет пользователь | По умолчанию шлёт новое (чтобы диалог не «уплыл»). Отключить: в `MessageInput`-хендлере `manager.show_mode = ShowMode.EDIT`. |
| Доступ к middleware-data | getter → kwargs; хендлер → `manager.middleware_data`; рендер (`Format`) → как `middleware_data`. |
| Текущий пользователь | `manager.event.from_user`. **Внимание:** при bg-обновлениях может быть только `id` → `BgManager(..., load=True)`. |
| Передача данных между диалогами | Вход: `start(..., data=...)` → `manager.start_data`. Выход: `done(result=...)` → `on_process_result`. |
| `when` в pager-виджетах (`ListGroup`, `NextPage`...) | У пейджеров своя data; нужен magic-filter `F["data"]["key"]`. |

> Замечание: в `faq.rst` доступ к middleware-data описан как `dialog_manager.data`, но в коде
> актуально `dialog_manager.middleware_data` (переименование, см. migration 2.0b10 ниже).

---

## 8. Миграция — breaking changes (`docs/migration.rst`)

| Переход | Ключевые изменения |
|---|---|
| **2.0b21 → 2.0b22** | Переименование managed-обёрток: `ManagedTextInputAdapter→ManagedTextInput`, `ManagedCalendarAdapter→ManagedCalendar`, `...CounterAdapter→ManagedCounter`, `...CheckboxAdapter→ManagedCheckbox`, `...MultiSelectAdapter→ManagedMultiselect`, `...RadioAdapter→ManagedRadio`, `...ListGroupAdapter→ManagedListGroup`. |
| **2.0b18 → 2.0b21** | `on_error` в `TextInput` теперь получает 4-м параметром экземпляр `ValueError`; `on_error`/`on_success` получают `ManagedTextInput` вместо `TextInput` 2-м параметром. |
| **2.0b10 → 2.0b18** | Удалён класс `Registry`. **Каждый `Dialog` теперь `Router`** → `dp.include_router(dialog)`. `setup_dialogs` заменяет `registry.setup_dp()`. `render_preview`/`render_transitions`/`aiogram-dialog-preview` ждут `Dispatcher`/`Router`/`Dialog` вместо `Registry`. |
| **2.0b10 → 2.0b17** | `Registry` создаётся без dispatcher, потом `setup_dp`; `register_start_handler` требует router/dispatcher. |
| **1.x → 2.0b10** | Импорт `Dialog`/`LaunchMode`/`DialogManager` из корня пакета. `Whenable`→`widgets.common`. Find-by-id отдаёт managed-виджет (методам не нужны `DialogManager`/`ChatEvent`). `ManagedDialog`→`DialogProtocol`. У `Dialog` больше нет `.next/.back/.switch_to` (они в `DialogManager`). `data` в `Context` → `start_data`; `dialog_data`/`start_data` добавлены в `DialogManager`, `data`→`middleware_data`. |
| **0.11 → 1.0** | `reset_stack=true` → `mode=StartMode.RESET_STACK`. Диалог больше не меняет текущий aiogram-state. `context`/`current_intent()` → `current_context()` (`dialog_data`/`widget_data`/`start_data`/`state`). При закрытии под-диалога родитель восстанавливается в прежнем состоянии. Сигнатура `on_process_result` принимает start_data. Удалён `Group.keep_rows` (использовать `width=None`). |

---

## 9. Связи с остальной библиотекой

- `test_tools.MockMessageManager` реализует `api/protocols/message_manager.py::MessageManagerProtocol`
  (тот же протокол, что и боевой `manager/message_manager.py::MessageManager`).
- `BotClient` гоняет реальный пайплайн aiogram → проходят все middleware, навешанные
  `setup_dialogs` (bg-factory, isolation, dialog-manager-factory).
- `tools/preview.py::FakeManager` — полная заглушка `DialogManager` (`api/protocols/manager.py`),
  пригодна как референс при кастомных тестах рендера.
- `about.py` использует `widgets.kbd.Start`, `widgets.text.Jinja`, `widgets.link_preview.LinkPreview`
  и автоматически подключается в `setup.py`.
- `I18NFormat` — подкласс `widgets.text.Text` (та же иерархия, что `Const`/`Format`/`Multi`).
- `collect_dialogs` (`setup.py:210`) — общий рекурсивный обход роутеров, используется и в
  preview, и в transitions.

---

## 10. Чек-лист для продакшн-шаблона

- [ ] `states.py` — единый модуль со всеми `StatesGroup` (разрыв циклов импорта).
- [ ] Один файл = один диалог; общие виджеты — в `common.py`.
- [ ] Корневой диалог `LaunchMode.ROOT`; `/start` → `RESET_STACK` + `ShowMode.SEND`.
- [ ] Обязательный error-handler на `UnknownIntent` (рестарт в главное меню).
- [ ] Регистрация: `Router` для диалогов → `include_router` → `setup_dialogs` **последним**.
- [ ] Тесты: `BotClient` + `MockMessageManager` + `JsonMemoryStorage`, `setup_dialogs(dp, message_manager=...)`.
- [ ] Локаторы кнопок учитывают `fullmatch` (regex по полному тексту/эмодзи).
- [ ] i18n: `I18NFormat` + middleware на `message` И `callback_query`; без кеша текста.
- [ ] preview/transitions требуют `aiogram_dialog[tools]` (+ graphviz для диаграмм); `preview_data` у окон.
- [ ] Учесть встроенный About-диалог (появляется после `setup_dialogs`).
