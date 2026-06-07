---
title: "Зона 04 — Context, Intent, Stack, Storage, доступ к данным и персистентность"
zone: "04"
source_repo: "aiogram_dialog (develop, 08abdf0, 2026-05-02)"
aiogram_min: ">=3.14.0"
status: "reference"
updated: "2026-06-07"
files:
  - src/aiogram_dialog/context/storage.py
  - src/aiogram_dialog/context/intent_middleware.py
  - src/aiogram_dialog/context/intent_filter.py
  - src/aiogram_dialog/context/access_validator.py
  - src/aiogram_dialog/api/entities/context.py
  - src/aiogram_dialog/api/entities/stack.py
  - src/aiogram_dialog/api/entities/access.py
  - src/aiogram_dialog/api/entities/__init__.py
  - src/aiogram_dialog/utils.py
tests:
  - tests/test_isolation.py
  - tests/test_dialog_state_validation.py
  - tests/test_group.py
---

# Зона 04 — Context, Intent, Stack, Storage, доступ к данным и персистентность

Эта заметка описывает «низ» aiogram_dialog: как библиотека хранит состояние диалогов в
aiogram FSM storage, что такое `Context`/`Stack`/`intent_id`, как работают мультистеки,
ограничение доступа (`AccessSettings`), жизненный цикл контекста и сериализация данных.

Все ссылки на код даны как `src/aiogram_dialog/.../file.py:LINE`.

---

## 1. Обзор и модель данных

Каждое взаимодействие пользователя с диалогом проходит через цепочку middleware (см. §7),
которая по событию вычисляет «адрес» (chat/user/thread/business) и подгружает из FSM storage:

- **Stack** — список открытых диалогов (стек интентов) в одном «канале»;
- **Context** — данные конкретного открытого диалога (верхний из стека или адресованный по `intent_id`);
- **StorageProxy** — обёртка над `BaseStorage` aiogram, которая умеет читать/писать `Stack` и `Context`, и блокировать ключ через `BaseEventIsolation`.

Поверх FSM storage строится логическая модель:

```
StorageKey(destiny="aiogd:stack:<stack_id>")   -> Stack { intents: [intent_id, ...], last_message_id, ... }
StorageKey(destiny="aiogd:context:<intent_id>") -> Context { state, start_data, dialog_data, widget_data, access_settings }
```

`intent_id` — это идентификатор **открытого экземпляра диалога** (одной «задачи» в стеке).
`stack_id` — идентификатор **стека** (последовательности задач).

---

## 2. `Context` — данные одного открытого диалога

Файл: `src/aiogram_dialog/api/entities/context.py:11`.

```python
Data = dict | list | int | str | float | None       # context.py:7
DataDict = dict[str, Data]                            # context.py:8

@dataclass(unsafe_hash=True)
class Context:
    _intent_id: str = field(compare=True)             # context.py:13
    _stack_id: str = field(compare=True)              # context.py:14
    state: State = field(compare=False)               # context.py:15
    start_data: Data = field(compare=False)           # context.py:16
    dialog_data: DataDict = field(compare=False, default_factory=dict)   # :17
    widget_data: DataDict = field(compare=False, default_factory=dict)   # :18
    access_settings: AccessSettings | None = field(compare=False, default=None)  # :19

    @property
    def id(self) -> str: return self._intent_id       # context.py:24
    @property
    def stack_id(self) -> str: return self._stack_id  # context.py:28
```

| Поле | Тип | Назначение |
|---|---|---|
| `_intent_id` | `str` | Уникальный id экземпляра диалога. Прокидывается в callback_data кнопок, по нему адресуется событие. Доступ — `context.id`. |
| `_stack_id` | `str` | id стека, к которому принадлежит контекст. Доступ — `context.stack_id`. |
| `state` | `aiogram.fsm.state.State` | Текущее состояние (окно) диалога. Определяет, какой `Dialog`/`Window` рисуется. |
| `start_data` | `Data` | Аргумент, переданный в `dm.start(state, data=...)`. Read-only вход диалога. Доступен как `manager.start_data`. |
| `dialog_data` | `DataDict` | Изменяемое хранилище данных диалога. Доступ — `manager.dialog_data`. Живёт до закрытия диалога. |
| `widget_data` | `DataDict` | Хранилище состояний stateful-виджетов (Counter, Checkbox, Select, ScrollingGroup и т.п.), ключ — `widget_id`. |
| `access_settings` | `AccessSettings | None` | Ограничение доступа для этого конкретного интента (см. §6). |

Важно про сравнение/хэш: `unsafe_hash=True`, и в хэш/`__eq__` входят **только** `_intent_id` и `_stack_id`
(`compare=True`), остальные поля `compare=False`. То есть два `Context` считаются равными, если совпадают
intent+stack, независимо от содержимого данных. Это используется в проверках вида `context.id == new_context.id`
(`manager/manager.py:216`, `:312`).

`Context` напрямую конструируется только в двух местах:
- `Stack.push()` — при старте диалога (`stack.py:63`);
- `StorageProxy.load_context()` — при загрузке из storage (`storage.py:63`).

---

## 3. `Stack` — стек открытых диалогов

Файл: `src/aiogram_dialog/api/entities/stack.py:38`.

```python
DEFAULT_STACK_ID = ""        # stack.py:13
GROUP_STACK_ID = "<->"       # stack.py:14
_STACK_LIMIT = 100           # stack.py:15

@dataclass(unsafe_hash=True)
class Stack:
    _id: str = field(compare=True, default_factory=new_id)            # stack.py:40
    intents: list[str] = field(compare=False, default_factory=list)   # stack.py:41
    last_message_id: int | None = ...                                 # stack.py:42
    last_reply_keyboard: bool = False                                 # stack.py:43
    last_media_id: str | None = None                                  # stack.py:44
    last_media_unique_id: str | None = None                           # stack.py:45
    last_income_media_group_id: str | None = None                     # stack.py:46
    content_type: ContentType | None = None                           # stack.py:49
    access_settings: AccessSettings | None = None                     # stack.py:50
    has_protected_content: bool | None = None                         # stack.py:51
```

| Поле | Назначение |
|---|---|
| `_id` | id стека. Доступ — `stack.id`. По умолчанию случайный (`new_id()`). |
| `intents` | Список intent_id «снизу вверх». **Последний** элемент — активный (верхний) диалог. |
| `last_message_id` и `last_*` | Метаданные последнего отрисованного сообщения окна (для редактирования/удаления, кэша media, выбора ShowMode). Принадлежат стеку, а не контексту, т.к. одно сообщение на стек. |
| `access_settings` | Дефолтные ограничения доступа для стека (используются, когда стек пуст и контекста нет). |

### Методы (`stack.py`)

| Сигнатура | Строка | Что делает |
|---|---|---|
| `push(state, data) -> Context` | `stack.py:57` | Проверяет лимит `_STACK_LIMIT` (100) → иначе `DialogStackOverflow`. Создаёт `Context` с новым `intent_id`, добавляет id в `intents`, возвращает контекст. |
| `pop() -> str` | `stack.py:72` | Снимает и возвращает последний intent_id. |
| `last_intent_id() -> str` | `stack.py:75` | Возвращает `intents[-1]`. **На пустом стеке кинет IndexError** — всегда проверяйте `empty()`. |
| `empty() -> bool` | `stack.py:78` | `not self.intents`. |
| `default() -> bool` | `stack.py:81` | `id == DEFAULT_STACK_ID`. |
| `id` (property) | `stack.py:53` | Геттер `_id`. |

### Генерация id (`stack.py:19-35`)

`new_id()` = `id_to_str(new_int_id())`. `new_int_id()` берёт `int(time.time()) % 1e8` плюс случайный
старший разряд (`random.randint(0,99)*1e8`). `id_to_str` кодирует в base-62 (`0-9A-Za-z`). Итог — короткая
строка, безопасная для callback_data. Коллизии теоретически возможны, но крайне маловероятны (время + рандом).

`intent_id` также генерируется через `new_id()` внутри `push()` (`stack.py:64`).

---

## 4. `intent_id` — зачем нужен

`intent_id` уникально адресует **открытый экземпляр** диалога. Зачем:

1. **Адресация callback'ов.** Все inline-кнопки окна получают префикс `intent_id` в callback_data:
   `intent_callback_data()` (`utils.py:200`) формирует `intent_id \x1D <payload>`; `add_intent_id()`
   проставляет это всем кнопкам (`utils.py:211`). Разделитель — `CB_SEP = "\x1D"` (`utils.py:28`).
   При обработке `remove_intent_id()` (`utils.py:220`) отделяет intent_id и возвращает чистый payload.
2. **Защита от устаревших кнопок (outdated).** Когда приходит callback, middleware грузит контекст по
   `intent_id` и проверяет, что он совпадает с `stack.last_intent_id()` — иначе `OutdatedIntent`
   (`intent_middleware.py:172` `_check_outdated`). Это значит: клик по старой кнопке (диалог уже
   закрыт/перекрыт) не обрабатывается активным окном.
3. **Reply-кнопки.** Для reply-клавиатур intent_id извлекается из inline-кнопки сообщения, на которое
   сделан reply (`_intent_id_from_reply`, `intent_middleware.py:281`).

Если в callback_data **нет** `CB_SEP`, `remove_intent_id` вернёт `(None, callback_data)` — это
«бесконтекстный» callback, и грузится дефолтный контекст текущего стека (`intent_middleware.py:405-417`).

---

## 5. `StorageProxy` — чтение/запись в FSM storage

Файл: `src/aiogram_dialog/context/storage.py:21`.

### Конструктор (`storage.py:22-41`)

```python
StorageProxy(
    storage: BaseStorage,
    events_isolation: BaseEventIsolation,
    user_id: int | None,
    chat_id: int,
    thread_id: int | None,
    business_connection_id: str | None,
    bot: Bot,
    state_groups: dict[str, type[StatesGroup]],
)
```

Создаётся фабрикой `IntentMiddlewareFactory.storage_proxy()` (`intent_middleware.py:158`) из
`EventContext` + `data["fsm_storage"]`. `state_groups` берётся из registry (`registry.states_groups()`)
и нужен для валидации/восстановления `State` (см. `_state`).

### Ключи storage

`_context_key(intent_id)` (`storage.py:130`) и `_stack_key(stack_id)` (`storage.py:151`) строят
`StorageKey`. **Особенность:** в обоих ключах `user_id=self.chat_id` (а не `user_id`!), а реальная
идентификация пользователя/стека закодирована в `destiny`:

- контекст: `destiny=f"aiogd:context:{intent_id}"`;
- стек: `destiny=f"aiogd:stack:{stack_id}"` (где stack_id уже «исправлен», см. ниже).

Подставлять `user_id=chat_id` намеренно: один и тот же контекст/стек в групповом чате должен быть
общим для всех участников и не привязываться к конкретному `user_id` на уровне FSM-ключа. Разделение
по пользователям делается логически — через `stack_id` и `access_settings`.

### `_fixed_stack_id` — приватный vs не-приватный (`storage.py:140-149`)

```python
def _fixed_stack_id(self, stack_id):
    if stack_id != DEFAULT_STACK_ID:
        return stack_id
    if self.user_id in (None, self.chat_id) and self.business_connection_id is None:
        return stack_id          # личный чат -> ""
    return f"<{self.user_id}>"    # группа/бизнес -> персональный стек по user_id
```

Ключевая логика мультистека: **дефолтный стек (`""`) в личном чате остаётся `""`**, а в группе/бизнес-чате
автоматически превращается в персональный `"<user_id>"`. Значит, в группе каждый пользователь по дефолту
работает в своём изолированном стеке — события без явного intent/stack попадают в его личный стек,
а не в общий. Это и есть «default stack в группе персональный» из доки (`docs/group_business.rst:14`).

### `load_context(intent_id) -> Context` (`storage.py:51`)

1. `storage.get_data(_context_key)`.
2. Если данных нет — `UnknownIntent` (контекст удалён/не существует).
3. Парсит `access_settings` (`_parse_access_settings`, `storage.py:172`).
4. Восстанавливает `State` из строки (`_state`, см. ниже).
5. `return Context(**data)`.

### `load_stack(stack_id=DEFAULT_STACK_ID) -> Stack` (`storage.py:71`)

1. `fixed = _fixed_stack_id(stack_id)`.
2. **Берёт lock на stack-ключ** через `self.lock(key)` (`storage.py:43`) — это критическая секция,
   обеспечивающая, что параллельные апдейты одного стека сериализуются (см. §9, изоляция).
3. `get_data`. Удаляет `access_settings` из сырых данных (совместимость с 2.2a5, `storage.py:76`).
4. `access_settings` пересчитывается через `_default_access_settings` (а не читается из storage!).
5. Пустые данные → новый `Stack(_id=fixed, access_settings=...)`; иначе `Stack(**data)`.

`_default_access_settings(stack_id)` (`storage.py:65`): для **дефолтного стека в личном** —
`AccessSettings(user_ids=[self.user_id])` (диалог доступен только этому пользователю);
иначе `AccessSettings(user_ids=[])` (без ограничения по user_ids).

### `save_context(context)` (`storage.py:82`)

```python
data = copy(vars(context))                  # storage.py:85  — shallow copy
data["state"] = data["state"].state         # State -> "Group:state" строка
data["access_settings"] = self._dump_access_settings(...)
await storage.set_data(_context_key(context.id), data)
```

Сериализует `State` в строку, `AccessSettings` в dict. **`copy(vars(...))` — поверхностная копия**:
вложенные `dialog_data`/`widget_data` не копируются, в storage кладутся как есть (для JSON-storage это
безопасно, т.к. дамп сделает свою сериализацию; см. §8).

### `save_stack(stack)` (`storage.py:107`)

- Если `stack.empty() and not stack.last_message_id` → записывает `{}` (фактически очистка ключа).
- Иначе сохраняет явный набор полей (`_id`, `intents`, `last_message_id`, `last_reply_keyboard`,
  `last_media_id`, `last_media_unique_id`, `last_income_media_group_id`).
  **Внимание:** `content_type`, `access_settings`, `has_protected_content` в `save_stack` **НЕ
  сохраняются** (`storage.py:116-124`) — они эфемерны/пересчитываются. `access_settings` стека всегда
  пересчитывается при загрузке (`_default_access_settings`).

### `remove_context` / `remove_stack` (`storage.py:95`, `:101`)

Оба просто пишут `{}` в соответствующий ключ (не удаляют сам ключ из storage). Для большинства backend'ов
это означает, что ключ остаётся, но пустой → `load_context` на него кинет `UnknownIntent`, `load_stack`
вернёт новый пустой `Stack`.

### `_state(state: str) -> State` (`storage.py:162`) — валидация состояния

```python
group, *_ = state.partition(":")
try:
    for real_state in self.state_groups[group].__all_states__:
        if real_state.state == state:
            return real_state
except KeyError:
    raise UnknownState(f"Unknown state group {group}")
raise UnknownState(f"Unknown state {state}")
```

Восстанавливает объект `State` по строке. Если группа состояний неизвестна (диалог удалён из кода,
переименована группа) → `UnknownState`. Если группа есть, но конкретного состояния нет (state удалён) →
тоже `UnknownState`. Это типичный сценарий после деплоя с изменением `StatesGroup` — старые контексты в
storage становятся «битыми» и попадают в восстановление стека (см. §7, `IntentErrorMiddleware`).

### `lock` / `unlock` (`storage.py:43-49`)

`lock(key)` входит в `events_isolation.lock(key)` через общий `AsyncExitStack`. `unlock()` закрывает
весь стек локов (`aclose`). Блокировка берётся в `load_stack`, а снимается middleware'ом-анлокером (см. §7).

---

## 6. `AccessSettings` и валидация доступа

### `AccessSettings` (`src/aiogram_dialog/api/entities/access.py:5`)

```python
@dataclass
class AccessSettings:
    user_ids: list[int]
    custom: Any = None
```

- `user_ids` — белый список пользователей, которым разрешено взаимодействие со стеком/диалогом.
- `custom` — произвольное поле для собственного валидатора. **Внимание:** `custom` сериализуется в
  storage (`_dump_access_settings`, `storage.py:182`), поэтому, если вы его используете, оно тоже должно
  быть JSON-совместимым (для JSON-backends).

### `DefaultAccessValidator` (`src/aiogram_dialog/context/access_validator.py:15`)

Реализует протокол `StackAccessValidator` (`api/protocols/stack_access.py:8`):

```python
async def is_allowed(self, stack, context, event, data) -> bool:
    access_settings = context.access_settings if context else stack.access_settings  # :23-26
    if not access_settings:               return True   # нет ограничений
    if data["event_chat"].type is PRIVATE: return True   # в личке всё своё — всегда True
    if access_settings.user_ids:
        if data["event_from_user"].id not in access_settings.user_ids:
            return False
    return True
```

Логика:
- ограничения берутся из **контекста**, если он есть, иначе из **стека**;
- в приватном чате доступ всегда разрешён (личный стек и так изолирован ключами/`<user_id>`);
- в группе — проверка членства в `user_ids`.

### Жизненный цикл `access_settings`

- При `start(...)` (см. `_start_normal`, `manager/manager.py:284`): если `access_settings` не передан
  явно, он **наследуется** от текущего контекста (`manager.py:302-303`), а если контекста нет — от
  стека (`manager.py:304-305`). Затем `deepcopy` кладётся в новый контекст (`manager.py:308`). Дока:
  «If no access settings are set, they will be copied from last opened dialog in stack»
  (`group_business.rst:31`).
- Для дефолтного личного стека `_default_access_settings` автоматически выставляет `user_ids=[user_id]`
  — поэтому чужой пользователь не влезет даже без явных настроек (тест `test_second_user`,
  `tests/test_group.py:74`).

### Запрещённое взаимодействие (`FORBIDDEN_STACK_KEY`)

Если `is_allowed` вернул `False`, middleware не кладёт `STORAGE_KEY/STACK_KEY/CONTEXT_KEY` в data, ставит
`data["aiogd_stack_forbidden"] = True` (`FORBIDDEN_STACK_KEY`, `intent_middleware.py:51`) и снимает lock.
Событие тогда не доходит до диалога и может быть обработано обычным aiogram-хэндлером; фильтровать —
по ключу `aiogd_stack_forbidden` (дока `group_business.rst:48`). Для callback'ов middleware ещё и
автоматически « answer» делает, если событие осталось `UNHANDLED` (`intent_middleware.py:422`).

### Кастомный валидатор

Передаётся в `setup_dialogs(..., stack_access_validator=...)`. Внутри `data` доступны `event_chat`,
`event_from_user` и весь middleware-контекст — можно строить любую логику (роли, БД, `custom`-поле).

---

## 7. Middleware: цепочка загрузки/сохранения контекста

Файл: `src/aiogram_dialog/context/intent_middleware.py`. Регистрация — в `setup.py:103` `_register_middleware`.

Порядок регистрации (важен!) на каждом наблюдаемом событии (`message`, `business_message`,
`callback_query`, `aiogd_update`, `my_chat_member`, `chat_join_request`):

```
outer: intent_middleware.process_*      # грузит stack+context, берёт lock
outer: context_unlocker_middleware      # в finally снимает lock
inner: manager_middleware               # создаёт DialogManager
inner: context_saver_middleware         # после handler сохраняет context+stack
```

(`setup.py:139-166`). Outer-мидлвари оборачивают всё, inner — ближе к хэндлеру.

### `IntentMiddlewareFactory` — загрузчики

| Метод | Строка | Когда |
|---|---|---|
| `process_message` | `:298` | Обычное сообщение. Если в тексте «спрятан» reply-callback — превращает в `ReplyCallbackQuery` и пере-роутит как `callback_query`. Иначе грузит по intent из reply или дефолтный контекст стека. |
| `process_callback_query` | `:392` | Нажатие inline-кнопки. Вынимает intent_id из callback_data, грузит контекст по интенту (или дефолтный). |
| `process_aiogd_update` | `:367` | Внутреннее событие от `BgManager` (`aiogd_update`). Грузит по `intent_id` либо по `stack_id`. |
| `process_my_chat_member`, `process_chat_join_request` | `:343`, `:355` | Грузят дефолтный контекст. |

Внутренние помощники:
- `_load_context_by_stack` (`:198`) — грузит стек, берёт верхний контекст (или `None` если пусто),
  проверяет доступ, кладёт `STORAGE_KEY/STACK_KEY/CONTEXT_KEY`.
- `_load_context_by_intent` (`:236`) — грузит контекст по intent_id, затем его стек, проверяет
  `_check_outdated`, доступ, кладёт ключи.
- `_load_default_context` (`:271`) — `_load_context_by_stack(DEFAULT_STACK_ID)`.

`EVENT_CONTEXT_KEY` (`"aiogd_event_context"`, `events.py:35`) кладётся в data для каждого события —
содержит `EventContext(bot, chat, user, thread_id, business_connection_id)`. Из него и строится `StorageProxy`.

### `context_saver_middleware` (`intent_middleware.py:437`)

Выполняется **после** handler. Достаёт `STORAGE_KEY` из data; если есть — сохраняет контекст
(`data.pop(CONTEXT_KEY)`) и стек (`data.pop(STACK_KEY)`). Так изменения `dialog_data`/`widget_data`/`state`,
сделанные в хэндлере, попадают в storage. Если `STORAGE_KEY` нет (доступ запрещён / событие не для диалога) —
ничего не сохраняется.

### `context_unlocker_middleware` (`intent_middleware.py:446`)

Outer-обёртка: в `finally` всегда снимает lock (`proxy.unlock()`), даже если handler упал. Гарантирует,
что блокировка стека не «зависнет».

### `IntentErrorMiddleware` (`intent_middleware.py:456`)

Обрабатывает ошибки внутри диалоговых событий (`SUPPORTED_ERROR_EVENTS`, `:427`). Ключевое:
- `InvalidStackIdError` пропускается (`_is_error_supported`, `:471`);
- грузит стек (по `error.stack_id` для `OutdatedIntent`, иначе дефолтный);
- `_load_last_context` (`:486`): если контекст не грузится (`UnknownIntent`/`OutdatedIntent`) — вызывает
  `_fix_broken_stack` (`:479`): снимает и удаляет все контексты, сохраняет пустой стек («сброс битого
  стека»). Это лечит ситуацию после деплоя с удалёнными состояниями (`UnknownState`).

---

## 8. Сериализация и персистентность данных — подводные камни

Данные диалога живут в `dialog_data`, `widget_data`, `start_data`. Они проходят через
`StorageProxy.save_context` → `storage.set_data` → конкретный backend aiogram.

**Главное правило: всё, что кладётся в `dialog_data`/`widget_data`/`start_data`/`result`, должно быть
сериализуемым тем backend'ом, который вы используете.**

- Тип `Data = dict | list | int | str | float | None` (`context.py:7`) — это и есть «контракт»: только
  JSON-примитивы и их комбинации.
- Тестовый/референсный backend `JsonMemoryStorage` (`test_tools/memory_storage.py`) делает
  `json.dumps`/`json.loads` (`:40`, `:43`). На нём положить, например, `datetime`, `set`, `Decimal`,
  pydantic-модель, объект → `TypeError` при сохранении.
- Реальные backends (`RedisStorage`, `MongoStorage` и т.п.) имеют свои сериализаторы (часто JSON или
  pickle через `DefaultKeyBuilder`/json). На pickle-backend объекты пройдут, но это **анти-паттерн**:
  непереносимо, ломается при изменении классов, раздувает storage.
- `MemoryStorage` (из aiogram, без JSON) хранит python-объекты как есть в RAM — там «прокатит» что
  угодно, но при переходе на персистентный storage всё сломается. **Не полагайтесь на это в шаблоне.**

Дополнительно:
- `save_context` делает `copy(vars(context))` — **shallow** (`storage.py:85`). Вложенные структуры
  кладутся по ссылке; для JSON-backend это не проблема (дамп всё равно копирует), но мутировать те же
  объекты после save до dumps — плохая идея.
- `start_data` сериализуется так же, как `dialog_data` — те же ограничения.
- `result` в `done(result=...)` уходит как `data` в `aiogd_update`-событие (через `BgManager`) и/или
  напрямую в `on_process_result` — для bg-сценария он проходит через pydantic-событие, тоже должен быть
  сериализуемым/совместимым.

---

## 9. Изоляция и конкурентность

- При `load_stack` берётся lock на ключ стека через `BaseEventIsolation.lock(key)` (`storage.py:74`).
  Дефолт — `SimpleEventIsolation` (`setup.py:207`), можно заменить через
  `setup_dialogs(..., events_isolation=...)`.
- Тест `tests/test_isolation.py:23` (`test_concurrent_events`) подтверждает: два одновременных `/start`
  обрабатываются **последовательно** — пока первый держит lock и «висит» на `event_common.wait()`,
  второй не стартует (`assert len(data) == 1`). После `event_common.set()` отрабатывает второй.
- Lock берётся на уровне стека → разные стеки (разные пользователи в группе, разные `NEW_STACK`) могут
  обрабатываться параллельно, один стек — строго по очереди. Это защищает от гонок при записи
  `intents`/`dialog_data`.
- Для **продакшна с несколькими воркерами/процессами** `SimpleEventIsolation` (in-memory) недостаточно —
  нужен распределённый isolation (например, `RedisEventIsolation`), иначе два процесса могут одновременно
  изменить один стек.

---

## 10. Мультистек: `DEFAULT_STACK_ID`, `GROUP_STACK_ID`, `NEW_STACK`

| Способ | stack_id | Поведение |
|---|---|---|
| Дефолт (событие без intent) | `DEFAULT_STACK_ID = ""` | В личке — `""`; в группе/бизнесе — автоматически `"<user_id>"` (персональный, `storage.py:149`). |
| `GROUP_STACK_ID` | `"<->"` | Предопределённый **общий** стек. Используется через `manager.bg(stack_id=GROUP_STACK_ID)` для shared-диалога в группе (дока `group_business.rst:16`, тест `test_shared_stack` `tests/test_group.py:163`). |
| Произвольная строка | любой `str` | Свой именованный стек: `manager.bg(stack_id="my_stack")`. |
| `StartMode.NEW_STACK` | случайный `new_id()` | `_start_new_stack` создаёт `Stack()` со случайным id и стартует в нём через `bg` (`manager.py:272`). Новый диалог в новом сообщении, независим. |

Зачем мультистек: несколько параллельных диалогов одному пользователю/в одном чате (например, основное
меню + всплывающее уведомление в отдельном сообщении), shared-меню в группе, изоляция топиков
(разные `thread_id` → разные стеки, `group_business.rst:26`).

Ограничения по стеку (`manager.py`):
- В **не-дефолтном** стеке нельзя `ReplyKeyboardMarkup` (`_ensure_stack_compatible`, `manager.py:370`)
  → `InvalidKeyboardType`. Reply-клавиатуры завязаны на «главное» сообщение, которое логично только в
  дефолтном стеке.
- ShowMode в не-дефолтном стеке по умолчанию `EDIT` (`_calc_show_mode`, `manager.py:517`).

---

## 11. Жизненный цикл контекста (создание/удаление)

Создание — только при **старте** диалога:
- `start(state, data, mode, ...)` (`manager.py:241`) → по `StartMode`:
  - `NORMAL` → `_start_normal` (`:284`): сохраняет текущий контекст, наследует `access_settings`,
    `stack.push(state, data)` (новый `Context`+intent), `dialog.process_start`, `show`.
  - `RESET_STACK` → `reset_stack` (удаляет все контексты, `manager.py:261`) + `_start_normal`.
  - `NEW_STACK` → `_start_new_stack` (новый стек + bg-старт, `:272`).
- LaunchMode влияет на стек до старта (`_process_launch_mode`, `manager.py:315`): `EXCLUSIVE`/`ROOT`
  очищают стек; `SINGLE_TOP` снимает верхний контекст, если стартуется тот же диалог.

Удаление — при **закрытии**:
- `done(result, show_mode)` (`manager.py:196`) → `process_close` → `mark_closed`.
- `mark_closed` (`manager.py:229`): `storage.remove_context(stack.pop())`; если стек опустел —
  `CONTEXT_KEY = None`, иначе грузит новый верхний контекст; `save_stack`. Затем родительский диалог
  получает `process_result(старый start_data, result, ...)`.
- `reset_stack` (`manager.py:261`): циклически `pop`+`remove_context` всего стека, `save_stack`, обнуляет
  `CONTEXT_KEY`.

Дока подтверждает: «Each time you close a dialog, task and dialog context are removed»
(`docs/transitions/index.rst:25`); данные закрытого диалога стираются (родитель не имеет доступа к
контексту ребёнка — только к `result`, `index.rst:105`).

**Подводный камень переполнения:** до 100 диалогов в стеке (`_STACK_LIMIT`). Повторный `start` одного и
того же диалога без закрытия копит контексты → `DialogStackOverflow` (`stack.py:58`). Дока прямо
предупреждает «не забывайте очищать стек, иначе он съест память» (`index.rst:28`).

---

## 12. `IntentFilter` (`src/aiogram_dialog/context/intent_filter.py:9`)

```python
class IntentFilter(Filter):
    def __init__(self, aiogd_intent_state_group: type[StatesGroup] | None): ...
    async def __call__(self, obj, **kwargs) -> bool:
        if self.aiogd_intent_state_group is None: return True
        context = kwargs.get(CONTEXT_KEY)
        if not context: return False
        return context.state.group == self.aiogd_intent_state_group
```

Фильтр, по которому хэндлеры диалога срабатывают только если текущий контекст принадлежит нужной
`StatesGroup`. Используется внутри `Dialog`/`Window`-роутинга (`dialog.py`). При `None` (любая группа)
пропускает всё. Если контекста нет (`CONTEXT_KEY` пуст) — `False`.

`CONTEXT_KEY`, `STACK_KEY`, `STORAGE_KEY`, `CALLBACK_DATA_KEY`, `EVENT_SIMULATED` определены в
`api/internal/middleware.py` (реэкспорт `api/internal/__init__.py`).

---

## 13. `UnsetId` — sentinel для bg-параметров

Определён в `src/aiogram_dialog/api/protocols/manager.py:20` (не в `api/entities/__init__.py`):

```python
class UnsetId(Enum):
    UNSET = "UNSET"
```

Реэкспортируется как `aiogram_dialog.UnsetId`. Нужен, чтобы отличить «параметр не передан» от
«передан `None`» в `bg(...)` для `thread_id`/`business_connection_id`. `coalesce_thread_id` /
`coalesce_business_connection_id` (`bg_manager.py:41`, `:57`): если значение `UNSET` и адрес тот же —
наследуют значение из текущего `EventContext`; если явно `None` — обнуляют. Это позволяет переадресовать
bg-менеджер в другой топик/бизнес-соединение или, наоборот, в «общий» поток.

---

## 14. `DIALOG_EVENT_NAME` и внутренние события

`DIALOG_EVENT_NAME = "aiogd_update"` (`api/entities/update_event.py:20`). `BgManager` шлёт через aiogram
кастомное событие `DialogUpdate(aiogd_update=DialogUpdateEvent)` (`bg_manager.py:173`). Его принимает
обсервер, зарегистрированный в `setup.py:40` `_setup_event_observer`, и обрабатывает `handle_update`
(`manager/update_handler.py:16`), мапя `DialogAction` → методы менеджера (`START`→`start`, `DONE`→`done`,
`SWITCH`→`switch_to`, `UPDATE`→update данных, `FG`→передача live-менеджера).

`DialogStartEvent` несёт `access_settings` (`update_event.py:50`), поэтому ограничения доступа можно
передавать и из background-старта.

**Важно для middleware:** bg-события идут как `aiogd_update`, ваши обычные aiogram-мидлвари их не
увидят — нужно регистрировать на `dispatcher.observers[DIALOG_EVENT_NAME]` (дока `bg/index.rst:90`).

---

## 15. Связи с остальной библиотекой

- **`DialogManager`/`SubManager`** (`manager/manager.py`, `manager/sub_manager.py`) — фасады поверх
  `Context`/`Stack`/`StorageProxy`: `manager.dialog_data` → `current_context().dialog_data`;
  `manager.current_stack()` → `STACK_KEY`. `SubManager.current_context()` (`sub_manager.py:58`) подменяет
  `widget_data` на под-словарь конкретного виджета/строки (`dataclasses.replace`).
- **Виджеты** хранят состояние в `context.widget_data[widget_id]` (Counter, Checkbox, ManagedScroll и др.).
- **Registry** (`setup.py:50`) даёт `state_groups` для `StorageProxy._state` и связь state→Dialog
  (`find_dialog`). Валидирует «одна StatesGroup = один Dialog» (`refresh`, `setup.py:75`; тест
  `tests/test_dialog_state_validation.py:20`).
- **EventContext** (`api/entities/events.py:27`) — единая точка «адреса» события для построения
  `StorageProxy` и bg-переадресации.
- **MediaIdStorage** — отдельный кэш file_id, не путать с context/stack storage.

---

## 16. Чек-лист и предупреждения для продакшн-шаблона

1. **Только JSON-сериализуемое в `dialog_data`/`widget_data`/`start_data`/`result`.** Тип-контракт —
   `Data = dict|list|int|str|float|None`. Никаких `datetime`/`Decimal`/`set`/pydantic-моделей/ORM-объектов:
   их кладите как ISO-строки/числа/dict. На JSON/Redis-backend объект-несериализуемое значение упадёт при
   сохранении (после ответа пользователю!), на in-memory «прокатит» и взорвётся при переезде на персистентный
   storage.
2. **Не используйте `MemoryStorage` для продакшна** — состояние теряется при рестарте, и он маскирует
   ошибки сериализации. Берите персистентный backend (Redis/Mongo) с JSON-сериализацией, не pickle.
3. **Очищайте стек.** Лимит 100 диалогов на стек (`DialogStackOverflow`). Для «корневых» меню используйте
   `StartMode.RESET_STACK` или `LaunchMode.ROOT/EXCLUSIVE`, иначе повторные `start` копят контексты и
   утекает память storage.
4. **Multi-worker → распределённый `events_isolation`.** Дефолтный `SimpleEventIsolation` — in-memory и не
   синхронизирует процессы. При нескольких воркерах передавайте `RedisEventIsolation` (или свой) в
   `setup_dialogs`, иначе гонки за один стек.
5. **Миграции состояний.** Удаление/переименование `StatesGroup` или `State` ломает старые контексты
   (`UnknownState`/`UnknownIntent`); `IntentErrorMiddleware` сбросит битый стек — пользователь молча
   «потеряет» открытый диалог. Планируйте миграции / совместимость состояний при деплое.
6. **Доступ в группах.** В групповом чате дефолтный стек персональный (`<user_id>`); для shared-диалогов
   используйте `GROUP_STACK_ID`/`NEW_STACK` и обязательно задавайте `AccessSettings(user_ids=[...])`.
   Обрабатывайте `aiogd_stack_forbidden` в аiogram-хэндлерах для запрещённых взаимодействий.
7. **Reply-клавиатуры — только в дефолтном стеке** (`InvalidKeyboardType` иначе).
8. **bg-события не видят обычные мидлвари** — регистрируйте их на `observers[DIALOG_EVENT_NAME]`, если
   нужно (БД-сессии, i18n и т.п. при background-обновлениях).
