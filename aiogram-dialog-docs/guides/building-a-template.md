---
title: "Как строить продакшн-шаблон бота на aiogram_dialog"
description: "Практическое руководство: структура проекта, выбор хранилища и изоляции, бутстрап приложения, обработка ошибок, DI, i18n, тестирование — собранное из выводов всех 20 глав reference и трёх guide-документов."
source_repo: "aiogram_dialog (develop @ 08abdf0, 2026-05-02)"
aiogram_min: ">=3.14.0"
status: guide
lang: ru
---

# Как строить продакшн-шаблон бота на aiogram_dialog

Это итоговое руководство. Оно не пересказывает API (за ним — `reference/`), а отвечает на
вопрос: **как из библиотеки собрать надёжный, тестируемый, готовый к продакшну шаблон**.
Все рекомендации опираются на разбор исходников (см.
[architecture.md](architecture.md) и [gotchas-and-production-checklist.md](gotchas-and-production-checklist.md))
и на эталонный `example/mega` (см. [reference/20 §5](../reference/20-testing-preview-i18n-faq.md)).

> TL;DR — пять решений, которые задают весь скелет:
> 1. **Persistent storage** (Redis), не `MemoryStorage`. В `dialog_data` — только JSON-примитивы.
> 2. **`/start` → `StartMode.RESET_STACK`**, корневой диалог — `LaunchMode.ROOT`.
> 3. **Error-handler на `UnknownIntent` и `UnknownState`** обязателен.
> 4. **`setup_dialogs(dp)` — строго последним**, после всех `include_router`.
> 5. **Все getter — `async def getter(**kwargs)`** с дефолтами; данные в окно только через них.

---

## 1. Структура проекта

`aiogram_dialog` не навязывает раскладку, но `example/mega` задаёт проверенный каркас.
Рекомендуемая структура шаблона:

```
telegram-bot-template/
├── pyproject.toml
├── .env.example
├── src/
│   └── bot/
│       ├── __init__.py
│       ├── __main__.py            # точка входа: python -m bot
│       ├── config.py              # настройки (pydantic-settings)
│       ├── app.py                 # сборка Dispatcher/Bot, setup_dialogs, запуск
│       ├── logging.py             # настройка логирования
│       │
│       ├── dialogs/               # ВСЕ диалоги
│       │   ├── __init__.py        # сбор dialog_router (include_routers всех диалогов)
│       │   ├── states.py          # ВСЕ StatesGroup в одном месте (разрыв циклов импорта)
│       │   ├── common.py          # переиспользуемые виджеты (кнопка "В меню" и т.п.)
│       │   ├── main_menu/         # один пакет = один диалог
│       │   │   ├── __init__.py    # экспортирует dialog
│       │   │   ├── dialog.py      # Dialog(Window(...), ...)
│       │   │   ├── handlers.py    # on_click / on_success / on_process_result
│       │   │   └── getters.py     # async def getter(**kwargs)
│       │   └── ...                # profile/, settings/, ...
│       │
│       ├── middlewares/           # auth, i18n, throttling, DB-session
│       ├── services/              # бизнес-логика, репозитории (НЕ знают про aiogram)
│       ├── infrastructure/        # storage factory, db engine, redis
│       └── locales/               # .ftl / .po переводы
└── tests/
    ├── conftest.py                # фикстуры dp/client/message_manager
    └── dialogs/                   # тесты потоков на BotClient
```

Принципы (из [reference/20 §5](../reference/20-testing-preview-i18n-faq.md)):

- **`states.py` — единый каталог состояний.** Все `StatesGroup` в одном модуле. Диалоги
  импортируют `from bot.dialogs import states`, а не друг друга — это разрывает циклические
  импорты (диалог A стартует диалог B и наоборот).
- **Один диалог — один пакет/модуль.** Внутри разносите декларацию (`dialog.py`), обработчики
  (`handlers.py`) и getter'ы (`getters.py`): декларация окна должна читаться как разметка.
- **`common.py` — общие виджеты.** Например, кнопка возврата в корень переиспользуется во всех
  под-диалогах. Один и тот же объект-виджет можно класть в несколько окон — они неизменяемы.
- **Сервисный слой не знает про aiogram_dialog.** Диалоги вызывают `services`, прокинутые через
  middleware-data; бизнес-логика тестируется отдельно.

---

## 2. Зависимости

`pyproject.toml` (фрагмент):

```toml
[project]
requires-python = ">=3.11"          # 3.11+ ради exception notes (add_exception_note)
dependencies = [
    "aiogram>=3.14.0",              # жёсткое требование aiogram_dialog
    "aiogram-dialog>=2.3.1",        # проверьте актуальную версию на PyPI
    "redis>=5.0",                   # persistent FSM storage для прода
    "pydantic-settings>=2.0",       # конфиг из env
    "fluent.runtime",               # i18n (если нужен Fluent)
]

[project.optional-dependencies]
dev = [
    "pytest", "pytest-asyncio",
    "aiogram-dialog[tools]",        # diagrams + aiohttp для preview/transitions
]
```

> `aiogram_dialog[tools]` (preview/диаграммы) и системный `graphviz` нужны **только в dev**.
> Никогда не импортируйте `aiogram_dialog.tools.transitions` в рантайме бота — модуль тянет
> `diagrams` на уровне импорта и уронит прод, где этих зависимостей нет
> ([reference/05](../reference/05-transitions-states.md), [reference/20 §2](../reference/20-testing-preview-i18n-faq.md)).

---

## 3. Хранилище и изоляция — фундамент надёжности

Это решение №1. `aiogram_dialog` хранит весь стек диалогов и контексты в **aiogram FSM
storage** (ключи `aiogd:stack:*` / `aiogd:context:*`, см.
[architecture.md §3](architecture.md)). Из этого следуют два жёстких требования.

### 3.1. Persistent storage + JSON-сериализуемость

```python
# infrastructure/storage.py
from redis.asyncio import Redis
from aiogram.fsm.storage.redis import RedisStorage

def make_storage(cfg) -> RedisStorage:
    return RedisStorage(
        Redis(host=cfg.redis_host, port=cfg.redis_port, db=cfg.redis_db),
    )
```

- **`MemoryStorage` — только для тестов/локалки.** Он теряет все диалоги при рестарте и
  **маскирует** ошибки сериализации (держит python-объекты в RAM). Переезд на Redis вскроет их
  уже в проде ([reference/04 §8](../reference/04-context-intent-storage-stack.md)).
- **В `dialog_data` / `widget_data` / `start_data` / `result` кладите только**
  `dict | list | int | str | float | None`. Никаких `datetime` (используйте ISO-строки),
  `Decimal`, `set`, pydantic-моделей, ORM-объектов — они упадут с `TypeError` **при сохранении**,
  то есть уже после ответа пользователю.
- В тестах берите `JsonMemoryStorage` (`aiogram_dialog.test_tools.memory_storage`) — он
  сериализует данные в JSON и ловит несериализуемые значения сразу
  ([reference/20 §1.4](../reference/20-testing-preview-i18n-faq.md)).

### 3.2. Распределённая изоляция событий (multi-worker)

`setup_dialogs` по умолчанию ставит `SimpleEventIsolation()` — **in-memory лок по чату**. Он
сериализует параллельные апдейты одного стека внутри одного процесса, но **не синхронизирует
несколько воркеров/реплик**. Если запускаете больше одного процесса (несколько подов, webhook за
балансировщиком) — берите распределённую изоляцию:

```python
from aiogram.fsm.storage.redis import RedisEventIsolation

storage = make_storage(cfg)
isolation = RedisEventIsolation(redis=storage.redis)   # общий Redis
...
setup_dialogs(dp, events_isolation=isolation)
```

Без этого — гонки за один стек и потерянные записи в storage
([gotchas §3](gotchas-and-production-checklist.md), [reference/04 §16](../reference/04-context-intent-storage-stack.md)).

---

## 4. Бутстрап приложения

Ключевой момент — **порядок сборки**. `setup_dialogs` навешивает middleware на уже собранное
дерево роутеров, поэтому идёт **последним**.

```python
# bot/app.py
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.redis import RedisEventIsolation
from aiogram_dialog import setup_dialogs, StartMode, ShowMode

from bot.config import load_config
from bot.infrastructure.storage import make_storage
from bot.dialogs import dialog_router, states
from bot.dialogs.errors import on_unknown_intent, on_unknown_state
from bot.middlewares import register_middlewares


async def start(message, dialog_manager):
    # /start ВСЕГДА сбрасывает стек и шлёт свежее сообщение
    await dialog_manager.start(
        states.MainMenu.MENU,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,
    )


def build_dispatcher(cfg) -> Dispatcher:
    storage = make_storage(cfg)
    dp = Dispatcher(
        storage=storage,
        # DI: всё, что положите в Dispatcher(...), доступно в getter/handler как kwargs
        config=cfg,
    )

    # 1) пользовательские хендлеры/команды
    dp.message.register(start, CommandStart())

    # 2) error-handlers ДО include_router (порядок регистрации errors не критичен,
    #    но держим рядом для читаемости)
    from aiogram.filters import ExceptionTypeFilter
    from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
    dp.errors.register(on_unknown_intent, ExceptionTypeFilter(UnknownIntent))
    dp.errors.register(on_unknown_state, ExceptionTypeFilter(UnknownState))

    # 3) прикладные middleware (auth, i18n, db-session, throttling)
    register_middlewares(dp, cfg)

    # 4) диалоги
    dp.include_router(dialog_router)

    # 5) aiogram_dialog — ПОСЛЕДНИМ
    isolation = RedisEventIsolation(redis=storage.redis)
    bg_factory = setup_dialogs(dp, events_isolation=isolation)
    dp["bg_factory"] = bg_factory      # пригодится для фоновых обновлений

    return dp


async def run():
    cfg = load_config()
    bot = Bot(
        cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(cfg)
    await dp.start_polling(bot)
```

Несколько неочевидных моментов (все — из разбора исходников):

- **`parse_mode` по умолчанию у окон = `UNSET_PARSE_MODE`, не `None`.** Окно наследует
  `Bot(default=...)`. Если глобально включили `HTML` — он применится ко всем окнам молча; чтобы
  отключить форматирование конкретного окна, передавайте `Window(..., parse_mode=None)`
  ([reference/03](../reference/03-window-dialog.md)).
- **Корневой роутер обязан быть `Dispatcher`** — иначе фоновые обновления (`BgManager`) бросят
  `TypeError("Root router must be Dispatcher.")` ([reference/06](../reference/06-bgmanager-updates.md)).
- **Встроенный диалог About** добавляется в роутер автоматически внутри `setup_dialogs`
  (state-group `AiogramDialogStates.ABOUT`). Учитывайте его в `collect_dialogs`/preview
  ([reference/20 §3](../reference/20-testing-preview-i18n-faq.md)).
- **Smoke-тест старта на CI:** коллизия «одна `StatesGroup` в нескольких `Dialog`» и
  незарегистрированные диалоги всплывают только на `emit_startup`/первом апдейте. Добавьте тест,
  который собирает `dp` и зовёт `await dp.emit_startup()` — поймаете на CI, а не в проде
  ([reference/01](../reference/01-setup-registration.md)).

---

## 5. Обработка ошибок состояния — без неё прод сломается на первом деплое

После рестарта процесса или деплоя со сменой `StatesGroup`/`State` у пользователей остаются
«живые» сообщения со старыми кнопками. Клик по ним порождает `UnknownIntent` / `UnknownState`.
Без обработчика библиотечный `IntentErrorMiddleware` **молча** сбросит стек — пользователь
потеряет диалог без обратной связи.

```python
# bot/dialogs/errors.py
import logging
from aiogram.types import ErrorEvent
from aiogram_dialog import BgManagerFactory, StartMode, ShowMode
from bot.dialogs import states

logger = logging.getLogger(__name__)


async def on_unknown_intent(event: ErrorEvent, bg_factory: BgManagerFactory, bot):
    """Старый callback после рестарта/смены состояний → рестарт в главное меню."""
    logger.warning("Unknown intent: %s", event.exception)
    callback = event.update.callback_query
    if callback:
        await callback.answer("Сессия устарела, открываю меню заново")
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:        # noqa: BLE001 — сообщение могло протухнуть (>48ч)
                pass
        chat_id = callback.message.chat.id if callback.message else callback.from_user.id
        bg = bg_factory.bg(bot=bot, user_id=callback.from_user.id, chat_id=chat_id)
        await bg.start(states.MainMenu.MENU, mode=StartMode.RESET_STACK)


async def on_unknown_state(event: ErrorEvent, bg_factory: BgManagerFactory, bot):
    """Контекст указывает на удалённый/переименованный State."""
    logger.warning("Unknown state: %s", event.exception)
    # та же стратегия: сброс в корень
    await on_unknown_intent(event, bg_factory, bot)
```

> `bg_factory` доступен в любом хендлере как `dialog_bg_factory` в middleware-data, либо берите
> возвращённое из `setup_dialogs` значение (мы положили его в `dp["bg_factory"]`). Для error-
> хендлера менеджера в контексте уже нет, поэтому действуем через фоновый `BgManager`.

**План миграций состояний.** Удаление/переименование `StatesGroup`/`State` ломает все открытые
контексты. Стратегии: (а) не удаляйте состояния сразу, помечайте deprecated; (б) при крупных
изменениях — версионируйте имена групп; (в) всегда имейте оба error-handler'а как сеть
безопасности ([reference/04 §16](../reference/04-context-intent-storage-stack.md),
[gotchas §2, §14](gotchas-and-production-checklist.md)).

---

## 6. Диалоги: конвенции

### 6.1. Окно читается как разметка

```python
# bot/dialogs/main_menu/dialog.py
from aiogram_dialog import Dialog, Window, LaunchMode
from aiogram_dialog.widgets.text import Format, Const
from aiogram_dialog.widgets.kbd import Start, Group
from aiogram_dialog.about import about_aiogram_dialog_button

from bot.dialogs import states
from .getters import menu_getter
from .handlers import on_process_result

main_menu_dialog = Dialog(
    Window(
        Format("👋 Привет, {username}!\nВыбери раздел:"),
        Group(
            Start(Const("👤 Профиль"), id="profile", state=states.Profile.VIEW),
            Start(Const("⚙️ Настройки"), id="settings", state=states.Settings.MAIN),
            width=2,
        ),
        about_aiogram_dialog_button(),     # готовая кнопка About
        state=states.MainMenu.MENU,
        getter=menu_getter,
    ),
    launch_mode=LaunchMode.ROOT,           # корневой диалог
    on_process_result=on_process_result,   # приём результатов от под-диалогов
)
```

- **Корневой диалог — `LaunchMode.ROOT`.** Он становится основанием стека; повторный заход не
  плодит дубли ([reference/05 §4](../reference/05-transitions-states.md)).
- **`id` у `Start`/`SwitchTo` обязателен**, короткий и ASCII: валидируется `^[a-zA-Z0-9_.]+$`,
  попадает в `callback_data` вместе с `intent_id`, а лимит Telegram — 64 байта и библиотекой
  **не проверяется**. Кириллица/пробелы/`:` → `InvalidWidgetIdError` при импорте
  ([reference/09](../reference/09-kbd-buttons-groups.md), [gotchas §4](gotchas-and-production-checklist.md)).

### 6.2. Getter — всегда `**kwargs` и дефолты

```python
# bot/dialogs/main_menu/getters.py
async def menu_getter(dialog_manager, event_from_user, **kwargs) -> dict:
    # данные в окно идут ТОЛЬКО отсюда; в обработчиках их нет
    return {
        "username": event_from_user.full_name or "друг",
    }
```

- **Обязательно `**kwargs`.** Все getter'ы вызываются с `**middleware_data`; новый ключ в
  middleware без `**kwargs` уронит getter с `TypeError`
  ([architecture.md §4](architecture.md), [reference/19 §9](../reference/19-common-custom-data.md)).
- **Возвращайте все ключи, которые есть в `Format`/`List`/`DynamicMedia`.** Отсутствующий ключ —
  это `KeyError` при показе окна, роняющий весь рендер. Давайте дефолты или ставьте `when=`
  ([reference/08](../reference/08-text-widgets.md)).
- **Не называйте поля `event`/`dialog_data`/`start_data`/`middleware_data`** — getter имеет
  высший приоритет и затрёт системные ключи ([architecture.md §4](architecture.md)).
- Данные в обработчиках берите из `manager.dialog_data` / `manager.start_data` /
  `manager.middleware_data`, а не из getter.

### 6.3. Чтение состояния stateful-виджетов

```python
async def result_getter(dialog_manager, **kwargs) -> dict:
    name = dialog_manager.find("name").get_value()         # TextInput
    agreed = dialog_manager.find("agree").is_checked()      # Checkbox
    tags = dialog_manager.find("tags").get_checked()        # Multiselect -> list
    return {"name": name, "agreed": agreed, "tags": tags}
```

- `manager.find(id)` возвращает `Managed`-обёртку **или `None`**, если id нет — проверяйте.
- Метод чтения зависит от виджета (`get_value`/`is_checked`/`get_checked`/`get_value` у Counter,
  `get_scope`/`get_offset` у Calendar). Полная таблица —
  [widgets-quick-reference.md](widgets-quick-reference.md).
- Дефолтные значения `Radio`/`Multiselect` ставьте в `on_start` диалога, а не параметром виджета
  ([reference/11](../reference/11-kbd-select.md), [reference/20 §7 FAQ](../reference/20-testing-preview-i18n-faq.md)).

---

## 7. Внедрение зависимостей (DI)

`aiogram_dialog` использует механизм middleware-data aiogram. Всё, что положено в
`Dispatcher(...)` или прикладной middleware, доступно:

- в **getter** — как именованный kwarg (`async def getter(user_service, **kwargs)`);
- в **handler** (`on_click`/`on_success`) — как `manager.middleware_data["user_service"]`;
- в **тексте** (`Format`) — через ключ `middleware_data` собранного `data`.

```python
# middlewares/services.py
class ServicesMiddleware(BaseMiddleware):
    def __init__(self, pool): self.pool = pool
    async def __call__(self, handler, event, data):
        async with self.pool.session() as session:
            data["user_service"] = UserService(session)
            return await handler(event, data)
```

> Чтобы DI работал и при **фоновых** обновлениях (`BgManager`), навесьте такие middleware и на
> `dispatcher.observers[DIALOG_EVENT_NAME]` — обычные observers фоновое событие `aiogd_update` не
> видят ([architecture.md §6](architecture.md), [reference/06](../reference/06-bgmanager-updates.md)).

---

## 8. Интернационализация (i18n)

`Format`/`Const` не локализуются. Рабочий паттерн из `example/i18n` — кастомный текст-виджет,
который рендерит **ключ перевода**, а функцию перевода берёт из middleware-data по локали:

```python
# widgets/i18n.py
from aiogram_dialog.widgets.text import Text
I18N_FORMAT_KEY = "aiogd_i18n_format"

class I18NFormat(Text):
    def __init__(self, key: str, when=None):
        super().__init__(when)
        self.key = key
    async def _render_text(self, data, manager):
        fmt = manager.middleware_data.get(I18N_FORMAT_KEY, lambda k, d: k.format_map(d))
        return fmt(self.key, data)
```

```python
# в окне:
Window(I18NFormat("greeting"), Button(I18NFormat("demo-btn"), id="demo"), ...)

# middleware кладёт функцию перевода нужной локали:
data[I18N_FORMAT_KEY] = l10ns[lang].format_value
```

- **Вешайте i18n-middleware на `message` И `callback_query`** (и на `DIALOG_EVENT_NAME` для фона) —
  иначе при нажатии кнопки локаль не подставится.
- **Не кешируйте перевод в виджете** — текст рендерится на каждый показ, и это правильно: смена
  языка работает мгновенно ([reference/20 §4](../reference/20-testing-preview-i18n-faq.md)).

---

## 9. Тестирование

`aiogram_dialog` поставляет полноценный тестовый харнесс — без реального Telegram, через
`dp.feed_update` прогоняется весь пайплайн middleware/фильтров/диалогов.

```python
# tests/conftest.py
import pytest
from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram_dialog import setup_dialogs
from aiogram_dialog.test_tools import BotClient, MockMessageManager
from aiogram_dialog.test_tools.memory_storage import JsonMemoryStorage

from bot.dialogs import dialog_router
from bot.app import start

@pytest.fixture
def message_manager():
    return MockMessageManager()

@pytest.fixture
def dp(message_manager):
    dp = Dispatcher(storage=JsonMemoryStorage())   # ловит несериализуемые данные
    dp.message.register(start, CommandStart())
    dp.include_router(dialog_router)
    setup_dialogs(dp, message_manager=message_manager)
    return dp

@pytest.fixture
def client(dp):
    return BotClient(dp)
```

```python
# tests/dialogs/test_main_menu.py
import pytest
from aiogram_dialog.test_tools.keyboard import InlineButtonTextLocator

@pytest.mark.asyncio
async def test_open_profile(dp, client, message_manager):
    await client.send("/start")
    msg = message_manager.one_message()
    assert "Выбери раздел" in msg.text

    message_manager.reset_history()
    # ВНИМАНИЕ: локатор использует fullmatch — нужен полный текст с эмодзи или regex
    cb_id = await client.click(msg, InlineButtonTextLocator(r".*Профиль.*"))
    message_manager.assert_answered(cb_id)
```

- **Локаторы используют `fullmatch`**: `InlineButtonTextLocator("Профиль")` не найдёт кнопку
  `"👤 Профиль"` — используйте `r".*Профиль.*"` или `InlineButtonDataLocator` по `id`.
- Между логическими шагами вызывайте `message_manager.reset_history()` — `one_message()` падает
  при 0 или >1 сообщении.
- Текстовый ввод — это `client.send("текст")`; он попадёт в `TextInput`/`MessageInput` активного
  окна ([reference/20 §1](../reference/20-testing-preview-i18n-faq.md)).

---

## 10. Рендеринг и UX-нюансы

Понимание `ShowMode`/`MessageManager` экономит часы отладки «почему сообщение моргает»
([architecture.md §7](architecture.md), [reference/07](../reference/07-message-manager-media.md)).

- **`/start` шлите с `ShowMode.SEND`** — чистое новое сообщение, старое меню остаётся в истории.
- **На нажатие кнопки** библиотека по умолчанию **редактирует** (`AUTO`→`EDIT`), на **сообщение
  пользователя** — **шлёт новое** (`AUTO`→`SEND`). Чтобы при вводе текста редактировать на месте,
  в `MessageInput`-хендлере поставьте `manager.show_mode = ShowMode.EDIT`.
- **`EDIT` — намерение, не гарантия.** Если старого сообщения нет / появилось-исчезло медиа / есть
  reply-клавиатура / Telegram отказал — фактически уйдёт новое сообщение.
- **Reply-клавиатура → каждый показ delete+send** (чат «прыгает») и **запрещена вне дефолтного
  стека** (`InvalidKeyboardType`). Не вызывайте `callback.answer()` в `on_click` виджетов,
  способных оказаться в reply-окне — там это упадёт ([reference/18](../reference/18-markup-style.md)).
- **Одно медиа и один `markup_factory` на окно.** Смена «текст ↔ медиа» = delete+send.
- **Медиа: сохраняйте и `file_id`, и `file_unique_id`.** Дефолтный `MediaIdStorage` — in-memory
  и пер-процесс; для общей экономии аплоадов между воркерами реализуйте
  `MediaIdStorageProtocol` поверх Redis/БД ([reference/17](../reference/17-media-linkpreview.md)).

---

## 11. Наблюдаемость и эксплуатация

- **Логируйте `UnknownIntent`/`UnknownState`** — всплеск означает деплой со сломанной миграцией
  состояний.
- **Throttling/flood-control** на частые `bg.update()` (прогресс-бары): Telegram лимитирует
  частоту edit. Кастомный `MessageManager` — штатная точка для ретраев `TelegramRetryAfter` и
  троттлинга; но **не глушите `MessageNotModified`** — на нём держится логика «не сохранять id»
  ([reference/07](../reference/07-message-manager-media.md)).
- **Метрики стека:** лимит — 100 диалогов на стек (`DialogStackOverflow`). Если ловите его —
  где-то `start` без `RESET_STACK` в цикле возврата в меню.
- **`bg.fg()` держит лок на стек** на время `async with` — тело должно быть коротким, тяжёлую
  работу выносите наружу ([reference/06](../reference/06-bgmanager-updates.md)).

---

## 12. Финальный чек-лист перед продом

Полный список (54 пункта) — в
[gotchas-and-production-checklist.md, Часть B](gotchas-and-production-checklist.md). Минимум:

- [ ] **Storage** — Redis (persistent), не `MemoryStorage`.
- [ ] **В `dialog_data` только JSON-примитивы**; `datetime` → ISO-строки.
- [ ] **`events_isolation`** — `RedisEventIsolation` при ≥2 воркерах.
- [ ] **`/start` → `StartMode.RESET_STACK` + `ShowMode.SEND`**; корневой диалог `LaunchMode.ROOT`.
- [ ] **Error-handlers** на `UnknownIntent` и `UnknownState`.
- [ ] **`setup_dialogs(dp)` — последним**, после всех `include_router`.
- [ ] **Smoke-тест** `await dp.emit_startup()` на CI.
- [ ] **Все getter** — `async def getter(**kwargs)` с дефолтами и без зарезервированных ключей.
- [ ] **`id` виджетов** — короткие, ASCII, уникальные в окне.
- [ ] **Тесты потоков** на `BotClient` + `MockMessageManager` + `JsonMemoryStorage`.
- [ ] **i18n-middleware** на `message`, `callback_query` и `DIALOG_EVENT_NAME`.
- [ ] **Tools/preview** — только в dev-зависимостях, не импортировать в рантайме.
- [ ] **Учтён About-диалог**, добавляемый `setup_dialogs`.

---

## Куда смотреть дальше

- Общая картина и жизненный цикл апдейта — [architecture.md](architecture.md).
- Все подводные камни и расширенный чек-лист — [gotchas-and-production-checklist.md](gotchas-and-production-checklist.md).
- Быстрый выбор виджета — [widgets-quick-reference.md](widgets-quick-reference.md).
- Детали по каждой подсистеме — соответствующая глава в [`reference/`](../reference/).
