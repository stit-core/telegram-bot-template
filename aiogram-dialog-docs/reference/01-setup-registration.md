# Зона №01 — Setup, регистрация диалогов, DialogRegistry, middleware-цепочка

> Референс по тому, как `aiogram_dialog` встраивается в `aiogram`: точка входа `setup_dialogs`, регистрация `Dialog` в `Router`/`Dispatcher`, `DialogRegistry`, полная цепочка middleware (manager / intent / context / bg-factory), служебный observer `aiogd_update` и фильтрация событий по `StatesGroup`.

---

## Фронтматтер

**Зона:** Setup, регистрация диалогов, DialogRegistry, middleware-цепочка.

**Изученные файлы (источник истины — код, не память):**

- `src/aiogram_dialog/setup.py` — `setup_dialogs`, `DialogRegistry`, `collect_dialogs`, `_register_middleware`, `_prepare_*`.
- `src/aiogram_dialog/dialog.py` — класс `Dialog` (регистрация хендлеров, фильтр, валидация окон/StatesGroup).
- `src/aiogram_dialog/manager/manager_factory.py` — `DefaultManagerFactory`.
- `src/aiogram_dialog/manager/manager_middleware.py` — `ManagerMiddleware`, `BgFactoryMiddleware`, ключи `MANAGER_KEY` / `BG_FACTORY_KEY`.
- `src/aiogram_dialog/api/protocols/registry.py` — `DialogRegistryProtocol`.
- `src/aiogram_dialog/context/intent_middleware.py` — `IntentMiddlewareFactory`, `IntentErrorMiddleware`, `context_saver_middleware`, `context_unlocker_middleware`.
- `src/aiogram_dialog/context/intent_filter.py` — `IntentFilter`.
- `docs/quickstart/*` (index.rst, bot.py, sg.py, window.py, dialog.py, register.py, start.py, setup_dialogs.py, start_bot.py, summary.py, install.sh).
- `docs/overview/index.rst`.

**Сопутствующие файлы, сверенные по ходу:** `src/aiogram_dialog/__init__.py`, `manager/bg_manager.py`, `manager/update_handler.py`, `api/internal/manager.py` (`DialogManagerFactory`), `api/internal/middleware.py` (служебные ключи), `api/entities/update_event.py` (`DIALOG_EVENT_NAME`, `DialogUpdate`), `api/entities/stack.py` (`DEFAULT_STACK_ID`, `GROUP_STACK_ID`), `context/access_validator.py`, `api/protocols/stack_access.py`, `api/protocols/manager.py`, `api/protocols/dialog.py`, `about.py`, тесты `tests/test_create.py`, `tests/test_dialog_state_validation.py`. Версия: ветка develop, коммит 08abdf0, aiogram>=3.14.0.

---

## 1. Минимальный запуск бота (что обязательно)

Из `docs/quickstart/summary.py` — полный рабочий минимум:

```python
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.filters.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from aiogram_dialog import (
    Dialog, DialogManager, setup_dialogs, StartMode, Window,
)
from aiogram_dialog.widgets.kbd import Button
from aiogram_dialog.widgets.text import Const


class MySG(StatesGroup):           # 1. StatesGroup
    main = State()


main_window = Window(              # 2. хотя бы одно Window с state=
    Const("Hello, unknown person"),
    Button(Const("Useless button"), id="nothing"),
    state=MySG.main,
)
dialog = Dialog(main_window)       # 3. Dialog из окон

storage = MemoryStorage()
bot = Bot(token='BOT TOKEN HERE')
dp = Dispatcher(storage=storage)   # 4. ОБЯЗАТЕЛЬНО storage (используется FSMContext)
dp.include_router(dialog)          # 5. зарегистрировать диалог в роутере/диспетчере
setup_dialogs(dp)                  # 6. поднять middleware и core-handler


@dp.message(Command("start"))
async def start(message: Message, dialog_manager: DialogManager):
    await dialog_manager.start(MySG.main, mode=StartMode.RESET_STACK)


if __name__ == '__main__':
    dp.run_polling(bot, skip_updates=True)
```

**Шесть обязательных шагов:**

| # | Шаг | Без него |
|---|-----|----------|
| 1 | Объявить `StatesGroup` (наследник `aiogram.fsm.state.StatesGroup`) | нечем идентифицировать диалог |
| 2 | Создать ≥1 `Window` с `state=` | `Dialog([])` бросит `ValueError("Dialog must have at least one window")` (`dialog.py:48-51`) |
| 3 | Собрать `Dialog(*windows)` | — |
| 4 | `Dispatcher(storage=...)` с реальным storage | контекст диалога негде хранить (внутри используется `FSMContext`/`fsm_storage`) |
| 5 | `dp.include_router(dialog)` (или в под-роутер) | диалог не попадёт в `DialogRegistry`, при старте — `UnregisteredDialogError` |
| 6 | `setup_dialogs(dp)` | не навешаны middleware, нет хендлера `aiogd_update`, `dialog_manager` не инжектится |

> **Порядок 5 и 6.** В `summary.py` сначала `include_router`, потом `setup_dialogs`. На практике сам реестр ленивый (`_ensure_loaded`/`refresh`), плюс на `router.startup` вешается `_startup_callback`, который вызовет `registry.refresh()` при `emit_startup`. То есть диалоги, добавленные **после** `setup_dialogs`, но **до** старта поллинга, тоже подхватятся. Однако делать `setup_dialogs` ровно один раз и на корневом роутере — единственный поддержанный путь.

`docs/quickstart/bot.py:1-6` отдельно подчёркивает: storage обязателен, т.к. «aiogram_dialog uses FSMContext internally to store its state».

---

## 2. `setup_dialogs` — точка входа

Объявление: `src/aiogram_dialog/setup.py:221-253`.

```python
def setup_dialogs(
        router: Router,
        *,
        dialog_manager_factory: DialogManagerFactory | None = None,
        message_manager: MessageManagerProtocol | None = None,
        media_id_storage: MediaIdStorageProtocol | None = None,
        stack_access_validator: StackAccessValidator | None = None,
        events_isolation: BaseEventIsolation | None = None,
        getter: DataGetter | None = None,
) -> BgManagerFactory:
```

### Параметры

| Параметр | Тип | Дефолт | Назначение |
|----------|-----|--------|------------|
| `router` | `aiogram.Router` (обычно `Dispatcher`) | — (позиционный, единственный обязательный) | Корневой роутер, на который вешаются observer `aiogd_update`, дефолтные диалоги и вся цепочка middleware. |
| `dialog_manager_factory` | `DialogManagerFactory \| None` | `None` | Фабрика `DialogManager` на каждое событие. Если `None` — собирается `DefaultManagerFactory` из `message_manager` + `media_id_storage` + `getter`. Если задан явно, то `message_manager` / `media_id_storage` / `getter` **игнорируются** (см. подводные камни). |
| `message_manager` | `MessageManagerProtocol \| None` | `None` → `MessageManager()` | Объект, реально отправляющий/редактирующий/удаляющий сообщения в Telegram. Точка подмены для тестов и кастомной доставки. |
| `media_id_storage` | `MediaIdStorageProtocol \| None` | `None` → `MediaIdStorage()` | Кэш `file_id` уже загруженных медиа (чтобы не перезаливать). По умолчанию — in-memory. |
| `stack_access_validator` | `StackAccessValidator \| None` | `None` → `DefaultAccessValidator()` | Проверка прав пользователя на чужой stack/context (групповые диалоги, `AccessSettings`). |
| `events_isolation` | `BaseEventIsolation \| None` | `None` → `SimpleEventIsolation()` | Изоляция параллельной обработки апдейтов одного пользователя/чата (lock per stack). Прокидывается в `StorageProxy`. |
| `getter` | `DataGetter \| None` | `None` | Глобальный геттер данных, добавляемый ко всем диалогам через фабрику (попадает в `DefaultManagerFactory.getter`). |

**Возвращает:** `BgManagerFactory` (конкретно `BgManagerFactoryImpl`, `setup.py:245`). Его держат, чтобы из кода **вне** хендлера (фоновые задачи, webhook других сервисов) получить `BaseDialogManager` через `.bg(bot, user_id, chat_id, ...)`. Внутри хендлеров та же фабрика доступна в middleware-data под ключом `dialog_bg_factory` (`BG_FACTORY_KEY`).

### Что делает по шагам (`setup.py:231-253`)

1. `_setup_event_observer(router)` (`setup.py:39-42`) — добавляет в `router.observers` наблюдатель `aiogd_update` (`TelegramEventObserver`). Это «псевдо-апдейт» библиотеки для фоновых start/switch/update/done.
2. `_register_event_handler(router, handle_update)` (`setup.py:45-47`) — регистрирует core-handler `handle_update` на этот observer с фильтром `any_state`. `handle_update` (`manager/update_handler.py:16`) транслирует `DialogUpdateEvent` в вызовы `dialog_manager.start/switch_to/show/done/update`.
3. `_include_default_dialogs(router)` (`setup.py:217-218`) — **включает встроенный `about_dialog()`** через `router.include_router`. Это добавляет StatesGroup `AiogramDialogStates.ABOUT` (`about.py`). Побочный эффект: при `setup_dialogs` появляется лишний диалог «About aiogram-dialog».
4. `_prepare_dialog_manager_factory(...)` — собирает фабрику (см. таблицу выше).
5. `_prepare_stack_access_validator` / `_prepare_events_isolation` — дефолты.
6. `bg_manager_factory = BgManagerFactoryImpl(router)`.
7. `_register_middleware(...)` — навешивает всю цепочку (раздел 5).
8. `return bg_manager_factory`.

> **Историческая заметка (версии).** В задаче упомянута сигнатура `setup_dialogs(dp, *favourite_dialogs, registry=..., message_manager=..., media_id_storage=...)`. В изучаемом коммите такого API **нет**: нет ни `*favourite_dialogs`, ни параметра `registry`. `docs/migration.rst:31` подтверждает: `setup_dialogs` заменил `registry.setup_dp()`, и `DialogRegistry` стал внутренним — снаружи его не передают и обычно не создают. Все параметры теперь keyword-only (после `*`), кроме `router`.

---

## 3. Регистрация диалогов: `Dialog` как `Router`

Ключевой факт: **`Dialog` сам является `Router`** — `class Dialog(Router, DialogProtocol)` (`dialog.py:36`). Поэтому регистрация диалога — это обычный `include_router`:

```python
dp.include_router(dialog)            # docs/quickstart/register.py
# либо в под-роутер:
some_router.include_router(dialog)
dp.include_router(some_router)
```

### Конструктор `Dialog.__init__` (`dialog.py:37-77`)

```python
Dialog(
    *windows: WindowProtocol,
    on_start: OnDialogEvent | None = None,
    on_close: OnDialogEvent | None = None,
    on_process_result: OnResultEvent | None = None,
    launch_mode: LaunchMode = LaunchMode.STANDARD,
    getter: GetterVariant = None,
    preview_data: GetterVariant = None,
    name: str | None = None,
)
```

| Параметр | Назначение / поведение |
|----------|------------------------|
| `*windows` | Окна диалога. Должно быть ≥1 (`ValueError` иначе). Первое окно задаёт `StatesGroup` диалога. |
| `on_start` | Колбэк `(start_data, manager)` после `process_start`. |
| `on_close` | Колбэк `(result, manager)` при закрытии. |
| `on_process_result` | Колбэк `(start_data, result, manager)` при возврате результата из вложенного диалога. |
| `launch_mode` | `LaunchMode` (`STANDARD`/`SINGLE_TOP`/`ROOT`/`EXCLUSIVE`) — поведение в стеке. |
| `getter` / `preview_data` | Геттеры данных (основной и для preview), оборачиваются в `PreviewAwareGetter`. |
| `name` | Имя роутера. Дефолт — `windows[0].get_state().group.__name__` (`dialog.py:53`), т.е. имя StatesGroup. |

**Валидации в конструкторе (краевые случаи):**

- `dialog.py:48-51` — пустой список окон → `ValueError("Dialog must have at least one window")`.
- `dialog.py:56-60` — окно с другой `StatesGroup` → `ValueError("All windows must be attached to same StatesGroup")`.
- `dialog.py:62-63` — два окна с одинаковым `State` → `ValueError("Multiple windows with state {state}")`.

Подтверждено тестами `tests/test_dialog_state_validation.py:34-50`.

**Что конструктор делает с роутингом** (побочные эффекты):

- `super().__init__(name=...)` — инициализирует `Router`.
- `_setup_filter()` (`dialog.py:180-185`) — на **каждый** observer диалога вешает `IntentFilter(self.states_group())`. Это отсекает чужие апдейты: окна обрабатывают событие, только если текущий контекст принадлежит этой StatesGroup.
- `_register_handlers()` (`dialog.py:187-190`) — регистрирует:
  - `self.callback_query.register(self._callback_handler)`
  - `self.message.register(self._message_handler)`
  - `self.business_message.register(self._message_handler)`

**`Dialog.include_router` запрещён** (`dialog.py:213-214`): `raise TypeError("Dialog cannot include routers")`. Диалог — лист в дереве роутеров; вложить в него под-роутеры нельзя. Вкладывать диалоги друг в друга тоже нельзя — для «вложенных» диалогов используется отдельный диалог + его старт через `Start`/`manager.start`, а не include.

### Прочие публичные методы `Dialog` (реализуют `DialogProtocol`)

| Метод (`dialog.py`) | Назначение |
|---------------------|------------|
| `launch_mode` (property, :79) | Режим запуска. |
| `states()` → `list[State]` (:83) | Список состояний по порядку окон. |
| `states_group()` → `type[StatesGroup]` (:192) | Класс StatesGroup диалога — **ключ в `DialogRegistry`**. |
| `states_group_name()` → `str` (:195) | `self._states_group.__full_group_name__` (aiogram). |
| `process_start(manager, start_data, state=None)` (:86) | `switch_to(state or первое)` + `on_start`. |
| `process_result(start_data, result, manager)` (:198) | `on_process_result` + `window.process_result`, если контекст не сменился. |
| `process_close(result, manager)` (:216) | `on_close`. |
| `render(manager)` → `NewMessage` (:122) | Рендер текущего окна. |
| `load_data(manager)` → `dict` (:115) | `manager.load_data()` + результат геттера. |
| `find(widget_id)` (:221) | Поиск виджета по id во всех окнах. |

---

## 4. `DialogRegistry` и `DialogRegistryProtocol`

### Протокол (`api/protocols/registry.py:9-16`)

```python
class DialogRegistryProtocol(Protocol):
    @abstractmethod
    def find_dialog(self, state: State | str) -> DialogProtocol: ...
    @abstractmethod
    def states_groups(self) -> dict[str, type[StatesGroup]]: ...
```

Минимальный публичный контракт реестра: «по состоянию найди диалог» и «отдай карту имя→StatesGroup».

### Реализация `DialogRegistry` (`setup.py:50-91`)

```python
class DialogRegistry(DialogRegistryProtocol):
    def __init__(self, router: Router):
        self.router = router
        self._loaded = False
        self._dialogs = {}          # {type[StatesGroup]: DialogProtocol}
        self._states_groups = {}    # {full_group_name: type[StatesGroup]}
```

| Метод | Поведение |
|-------|-----------|
| `find_dialog(state)` (:61) | `_ensure_loaded()`, затем `self._dialogs[state.group]`. На промах → `UnregisteredDialogError("No dialog found for ...")`. |
| `states_groups()` (:71) | `_ensure_loaded()`, возвращает `{full_group_name: StatesGroup}`. Используется `StorageProxy` для (де)сериализации `State` из строки. |
| `refresh()` (:75) | Полное пере-сканирование дерева роутеров через `collect_dialogs(self.router)`. Заполняет `_dialogs` и `_states_groups`, ставит `_loaded = True`. |
| `_ensure_loaded()` (:57) | Ленивая загрузка: если `_loaded == False`, зовёт `refresh()`. |

**Важная деталь `refresh` (`setup.py:75-91`):** при попытке зарегистрировать **две** разные `Dialog` с одной и той же `StatesGroup` бросается

```
ValueError("StatesGroup '<name>' is used in multiple dialogs: '<d1>' and '<d2>'")
```

Это происходит **не в момент** `Dialog(...)` и **не в** `include_router`, а при `refresh()` — практически на `emit_startup` (через `_startup_callback`) или при первом обращении к реестру. Подтверждено `tests/test_dialog_state_validation.py:20-31`: ошибка всплывает на `await dp.emit_startup()`.

> **Краевой случай `refresh` не идемпотентен полностью:** `_dialogs` накапливается (нет `self._dialogs.clear()` в начале `refresh`). Повторный `refresh` после добавления нового диалога с уже занятой StatesGroup даст коллизию даже на «том же» диалоге, если объект другой. На практике reset stack/повторные `setup_dialogs` не делают — реестр один на роутер.

### `collect_dialogs` (`setup.py:210-214`)

```python
def collect_dialogs(router: Router) -> Iterable[DialogProtocol]:
    if isinstance(router, DialogProtocol):
        yield router
    for sub_router in router.sub_routers:
        yield from collect_dialogs(sub_router)
```

Рекурсивно обходит `router.sub_routers`, отбирая узлы, проходящие `isinstance(..., DialogProtocol)` (`DialogProtocol` — `@runtime_checkable`, `api/protocols/dialog.py:18`). Так диалог, вложенный в любой под-роутер на любой глубине, попадёт в реестр.

### Где `DialogRegistry` создаётся и живёт

Реестр создаётся **внутри** `_register_middleware` (`setup.py:110`), один экземпляр на роутер, и передаётся в три middleware: `ManagerMiddleware`, `IntentMiddlewareFactory`, `IntentErrorMiddleware`. Снаружи его не инжектят. `_startup_callback(registry)` (`setup.py:94-100`) регистрируется в `router.startup` и при старте вызывает `registry.refresh()` — «delayed configuration».

---

## 5. Цепочка middleware (полный порядок)

Всё навешивается в `_register_middleware` (`setup.py:103-170`). aiogram различает **outer_middleware** (до фильтров/хендлеров, на «сырое» событие) и **(inner) middleware** (после прохождения фильтров, ближе к хендлеру). Порядок вызова: outer выполняются в порядке регистрации снаружи внутрь; inner — тоже в порядке регистрации, но уже внутри отфильтрованного потока; на «возврате» (finally/после `await handler`) — в обратном порядке.

### 5.1. Создаваемые объекты (`setup.py:110-129`)

```python
registry = DialogRegistry(router)
manager_middleware = ManagerMiddleware(dialog_manager_factory, router, registry)
intent_middleware = IntentMiddlewareFactory(registry, stack_access_validator, events_isolation)
router.startup.register(_startup_callback(registry))
update_handler = router.observers[DIALOG_EVENT_NAME]   # observer "aiogd_update"
router.errors.middleware(IntentErrorMiddleware(registry, events_isolation, stack_access_validator))
```

### 5.2. На какие observers что вешается

Целевые observers (по всем строкам метода):
`message`, `business_message`, `callback_query`, `update_handler` (= `aiogd_update`), `my_chat_member`, `chat_join_request`, плюс `errors`.

**(A) inner `manager_middleware`** — `setup.py:131-137`
на `message`, `business_message`, `callback_query`, `aiogd_update`, `my_chat_member`, `chat_join_request`, `errors`.

**(B) outer `intent_middleware.*`** — `setup.py:139-152`, по типу события:
- `message` / `business_message` → `process_message`
- `callback_query` → `process_callback_query`
- `aiogd_update` → `process_aiogd_update`
- `my_chat_member` → `process_my_chat_member`
- `chat_join_request` → `process_chat_join_request`

**(C) outer `context_unlocker_middleware`** — `setup.py:154-159` на те же 6 observers.

**(D) inner `context_saver_middleware`** — `setup.py:161-166` на те же 6 observers.

**(E) outer `BgFactoryMiddleware`** — `setup.py:168-170`: вешается на **все** `router.observers.values()` (включая прочие типы апдейтов). Кладёт в data ключ `dialog_bg_factory`.

### 5.3. Фактический порядок выполнения для одного callback_query

Outer регистрируются в порядке: intent → context_unlocker → bg_factory (bg_factory регистрируется последним в цикле по всем observers, поэтому он самый «внешний» из добавленных в этом блоке — но т.к. он лишь кладёт ключ и сразу зовёт handler, порядок относительно него некритичен). Логически на входе:

1. **outer `intent_middleware.process_callback_query`** (`intent_middleware.py:392`):
   - если в data нет `event_chat` — сразу к handler (это не пользовательский апдейт);
   - строит `EVENT_CONTEXT_KEY`, вынимает `intent_id` из callback-data (`remove_intent_id`);
   - грузит контекст по intent (`_load_context_by_intent`) либо дефолтный stack (`_load_default_context`, `DEFAULT_STACK_ID`);
   - проверяет `access_validator.is_allowed`; если запрещено — ставит `FORBIDDEN_STACK_KEY`, разлочивает proxy и НЕ кладёт `STORAGE_KEY`;
   - в случае успеха кладёт в data: `STORAGE_KEY` (proxy), `STACK_KEY`, `CONTEXT_KEY`, `CALLBACK_DATA_KEY`;
   - после handler: если результат `UNHANDLED` и стоял `FORBIDDEN_STACK_KEY` → `event.answer()` (гасит «часики»).
2. **outer `context_unlocker_middleware`** (`intent_middleware.py:446`): оборачивает в try/finally, гарантирует `proxy.unlock()` по выходу.
3. **inner `manager_middleware`** (`manager_middleware.py:37`): если `STORAGE_KEY in data` (`_is_event_supported`) — создаёт `DialogManager` фабрикой и кладёт под `dialog_manager`. В finally — `manager.close_manager()`.
4. **inner `context_saver_middleware`** (`intent_middleware.py:437`): после handler достаёт `STORAGE_KEY`; если есть — `save_context(CONTEXT_KEY)` + `save_stack(STACK_KEY)`.
5. **Фильтры окон** (`IntentFilter`) и хендлеры `Dialog._callback_handler` / `_message_handler`.

> Ключевой инвариант: **`dialog_manager` создаётся только если `STORAGE_KEY` есть в data** (`manager_middleware.py:35`). А `STORAGE_KEY` кладёт именно intent-middleware и только при успешной загрузке контекста и разрешённом доступе. Поэтому на «чужих» / запрещённых / несвязанных апдейтах `dialog_manager` в хендлер не инжектится.

### 5.4. `aiogd_update` (фоновые события)

Псевдо-апдейт `DialogUpdate(aiogd_update=...)` (`api/entities/update_event.py:62-74`, `event_type == "aiogd_update"`) проходит ту же цепочку через observer `update_handler`. `process_aiogd_update` (`intent_middleware.py:367`) грузит контекст по `intent_id` или `stack_id`, дальше `handle_update` транслирует событие в методы менеджера. Так работают `BgManager.start/switch_to/update/done/fg` (`manager/bg_manager.py`).

### 5.5. `IntentErrorMiddleware` (на `errors`)

`intent_middleware.py:456-563`. Перехватывает ошибки `aiogram` для поддержанных типов апдейтов (`SUPPORTED_ERROR_EVENTS`), пытается восстановить «сломанный» стек:
- `_is_error_supported` (:468): пропускает `InvalidStackIdError`, требует `event_chat` и `event_from_user`, проверяет `event.update.event_type`.
- При `UnknownIntent`/`OutdatedIntent` — `_fix_broken_stack` (вычищает контексты до пустого стека).
- В finally — unlock + save context/stack.

Это причина, почему «протухшие» кнопки старого сообщения не валят бота, а тихо ресетят стек.

---

## 6. `ManagerMiddleware` и `BgFactoryMiddleware`

`src/aiogram_dialog/manager/manager_middleware.py`.

Константы: `MANAGER_KEY = "dialog_manager"` (:16), `BG_FACTORY_KEY = "dialog_bg_factory"` (:17).

### `ManagerMiddleware(BaseMiddleware)` (:20)

```python
ManagerMiddleware(
    dialog_manager_factory: DialogManagerFactory,
    registry: DialogRegistryProtocol,
    router: Router,
)
```

- `_is_event_supported(event, data)` (:32) → `STORAGE_KEY in data`.
- `__call__` (:37): если поддержано — `data["dialog_manager"] = factory(event, data, registry, router)`; затем `await handler`; в `finally` — `manager.close_manager()` (освобождение ресурсов, см. `DialogManager.close_manager`, `api/protocols/manager.py:208`).

### `BgFactoryMiddleware(BaseMiddleware)` (:62)

```python
BgFactoryMiddleware(bg_manager_factory: BgManagerFactory)
```

- `__call__` (:70): кладёт `data["dialog_bg_factory"] = bg_manager_factory` и зовёт handler. Так `dialog_bg_factory` доступен в любом хендлере (в т.ч. не-диалоговом) для фоновых стартов чужих диалогов.

---

## 7. `DefaultManagerFactory` (`manager/manager_factory.py`)

```python
class DefaultManagerFactory(DialogManagerFactory):
    def __init__(self, message_manager, media_id_storage, getter): ...
    def __call__(self, event, data, registry, router) -> DialogManager:
        return ManagerImpl(event=event, data=data,
                           message_manager=self.message_manager,
                           media_id_storage=self.media_id_storage,
                           registry=registry, router=router,
                           getter=self.getter)
```

- Реализует протокол `DialogManagerFactory` (`api/internal/manager.py:13`): `__call__(event: ChatEvent, data: dict, registry: DialogRegistryProtocol, router: Router) -> DialogManager`.
- Создаёт `ManagerImpl` (полнофункциональный менеджер) на каждое событие.
- Подменив `dialog_manager_factory` в `setup_dialogs`, можно полностью переопределить тип менеджера.

---

## 8. `IntentFilter` (`context/intent_filter.py`)

```python
class IntentFilter(Filter):
    def __init__(self, aiogd_intent_state_group: type[StatesGroup] | None): ...
    async def __call__(self, obj, **kwargs) -> bool:
        if self.aiogd_intent_state_group is None:
            return True
        context = kwargs.get(CONTEXT_KEY)   # "aiogd_context"
        if not context:
            return False
        return context.state.group == self.aiogd_intent_state_group
```

- Вешается `Dialog._setup_filter` на каждый observer диалога.
- Пропускает событие к хендлерам окна **только если** загруженный контекст принадлежит StatesGroup этого диалога. Нет контекста (`CONTEXT_KEY` пуст) → `False` → диалог не обрабатывает. Это и есть «better states routing» из overview.

---

## 9. Связи зоны с остальной библиотекой

- **aiogram FSM.** Контекст хранится через `FSMContext`/`fsm_storage`; `StorageProxy` берёт `data["fsm_storage"]` и `events_isolation`. Без `Dispatcher(storage=...)` зона не работает.
- **Служебные ключи middleware-data** (источник истины — `api/internal/middleware.py`): `aiogd_storage_proxy` (`STORAGE_KEY`), `aiogd_stack` (`STACK_KEY`), `aiogd_context` (`CONTEXT_KEY`), `aiogd_original_callback_data` (`CALLBACK_DATA_KEY`), `aiogd_event_simulated` (`EVENT_SIMULATED`); плюс `dialog_manager`, `dialog_bg_factory`, `aiogd_event_context` (`EVENT_CONTEXT_KEY`), `aiogd_stack_forbidden` (`FORBIDDEN_STACK_KEY`). Также читаются стандартные aiogram-ключи: `event_chat`, `event_from_user`, `event_router`, `fsm_storage`, `bot`.
- **Менеджеры.** `ManagerImpl` (foreground), `BgManager`/`BgManagerFactoryImpl` (background). `setup_dialogs` возвращает `BgManagerFactory`.
- **Сущности апдейтов.** `DialogUpdate`/`DialogUpdateEvent` (`event_type == "aiogd_update"`), `DialogAction`, `DialogStart/Switch/Fg Event` — каркас фоновых операций; `handle_update` — их единый обработчик.
- **Стек/контекст.** `DEFAULT_STACK_ID == ""`, `GROUP_STACK_ID == "<->"` (`api/entities/stack.py`). Дефолтный стек — пустая строка.
- **Доступ.** `StackAccessValidator`/`DefaultAccessValidator` + `AccessSettings` — для групповых диалогов (приватный чат всегда разрешён).
- **Публичный API** (`__init__.py`): наружу экспортируются `setup_dialogs`, `Dialog`, `Window`, `DialogManager`, `BgManagerFactory`, `LaunchMode`, `ShowMode`, `StartMode`, `DEFAULT_STACK_ID`, `GROUP_STACK_ID`, `AccessSettings` и др. **`DialogRegistry` НЕ экспортируется** — он внутренний.

---

## 10. Подводные камни / краевые случаи / типичные ошибки (для шаблона)

1. **`setup_dialogs` — последним и один раз, на корневом роутере.** Все диалоги должны быть `include_router`-нуты в дерево этого же роутера (на любой глубине под-роутеров). Диалог в дереве другого роутера, не переданного в `setup_dialogs`, → `UnregisteredDialogError` при старте.
2. **Параметры `setup_dialogs` keyword-only.** Кроме `router`. `setup_dialogs(dp, my_dialog)` (как в старом API с `*favourite_dialogs`) — `TypeError`. Регистрируйте диалоги через `include_router`, а не позиционно.
3. **`dialog_manager_factory` перекрывает `message_manager`/`media_id_storage`/`getter`.** Если передаёте свою фабрику — эти три параметра игнорируются (`_prepare_dialog_manager_factory`, `setup.py:179-180`). Прокидывайте их внутрь своей фабрики сами.
4. **Коллизия StatesGroup всплывает поздно — на `emit_startup`/первом обращении к реестру, а не при `Dialog(...)`/`include_router`.** В шаблоне стоит гонять `await dp.emit_startup()` (или старт поллинга) в smoke-тесте, чтобы поймать `ValueError "... used in multiple dialogs"` на CI, а не в проде. Одна `StatesGroup` = ровно один `Dialog`.
5. **Встроенный `about_dialog` подключается автоматически** (`_include_default_dialogs`). Это лишний диалог/StatesGroup `AiogramDialogStates.ABOUT` + кнопка «About». Безвреден, но учтите при аудите зарегистрированных диалогов и при кастомных reset-сценариях.
6. **`Dialog.include_router` → `TypeError`.** Нельзя вкладывать роутеры/диалоги в `Dialog`. «Вложенные диалоги» делаются через `Start`/`manager.start`, а не через include.
7. **`dialog_manager` инжектится не всегда.** Только когда intent-middleware успешно загрузил контекст и доступ разрешён (`STORAGE_KEY in data`). В не-диалоговых хендлерах (например первый `/start`) `dialog_manager` присутствует, т.к. грузится дефолтный стек, но не полагайтесь на наличие активного контекста — проверяйте `manager.has_context()`. Для запрещённого стека (`FORBIDDEN_STACK_KEY`) менеджера и контекста не будет.
8. **storage обязателен и должен переживать рестарты для прод-ботов.** `MemoryStorage` из quickstart теряет все стеки/контексты при перезапуске — в продакшене берите Redis/иной persistent storage; иначе кнопки старых сообщений станут «протухшими» (что, впрочем, корректно отрабатывает `IntentErrorMiddleware`).
9. **`reset_stack` / `StartMode.RESET_STACK` при `/start`.** quickstart явно советует `mode=StartMode.RESET_STACK`, иначе при повторном `/start` диалоги штабелируются в стеке (`start.py`).
10. **`events_isolation` по умолчанию `SimpleEventIsolation` (in-memory, per-process).** При нескольких воркерах/инстансах нужна распределённая изоляция, иначе возможны гонки параллельной обработки апдейтов одного пользователя.
