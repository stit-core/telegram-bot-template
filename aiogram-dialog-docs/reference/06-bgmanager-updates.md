---
zone: 06
title: "Фоновые обновления (BgManager), обновление сообщений вне обработчиков"
source_repo: aiogram_dialog
source_ref: "develop @ 08abdf0 (2026-05-02)"
aiogram: ">=3.14.0"
files:
  - src/aiogram_dialog/manager/bg_manager.py
  - src/aiogram_dialog/manager/updater.py
  - src/aiogram_dialog/manager/update_handler.py
  - src/aiogram_dialog/api/entities/update_event.py
  - src/aiogram_dialog/api/entities/events.py
  - src/aiogram_dialog/manager/message_manager.py
  - src/aiogram_dialog/manager/manager.py (show / _calc_show_mode / bg / fg)
  - src/aiogram_dialog/setup.py
docs:
  - docs/bg/index.rst
  - docs/how_are_messages_updated/index.rst
status: reference
---

# Зона 06. Фоновые обновления (BgManager) и механика обновления сообщений

## TL;DR (как это работает в одном абзаце)

Внутри обычного хэндлера у вас есть полноценный `DialogManager`, привязанный к
текущему апдейту, чату и стеку. Как только вы выходите за пределы хэндлера
(фоновая `asyncio.Task`, webhook от платёжки, брокер сообщений, хэндлер, который
хочет тронуть **другого** пользователя/чат), полноценного менеджера у вас нет —
нет «текущего апдейта». Тогда вы берёте **background manager** (`BgManager`),
реализующий узкий протокол `BaseDialogManager` (`start` / `done` / `switch_to` /
`update` / `bg` / `fg`). Его методы не делают работу синхронно: они формируют
искусственный апдейт `DialogUpdate` (с внутренним событием `DialogUpdateEvent`,
тип события — `aiogd_update` = `DIALOG_EVENT_NAME`) и **прогоняют его через тот же
aiogram-диспетчер** (`Updater.notify`). Диспетчер находит зарегистрированный при
`setup_dialogs` обработчик `handle_update`, тот поднимает уже **полноценный**
`DialogManager` для нужного чата/стека (через middleware) и вызывает на нём
реальные `start` / `switch_to` / `show` / `done`. Дальше срабатывает обычный
конвейер рендера → `MessageManager.show_message`, который и решает, что сделать с
сообщением (edit / send / delete+send / ничего).

---

## 1. Зачем нужен BgManager

`docs/bg/index.rst:1` перечисляет три случая, когда «правильного» `dialog_manager`
у вас нет:

* фоновые задачи (`asyncio.create_task`, прогресс-бары, долгие операции);
* http / broker хэндлеры (вебхуки платёжек, очереди, внешние события);
* хэндлеры, которые обновляют диалог **другого** пользователя/чата.

Важное ограничение из доки (`docs/bg/index.rst:11`): «вы **не можете** использовать
обычный `dialog_manager` вне aiogram-dialog-хэндлера». Обычный менеджер живёт
ровно один апдейт (создаётся `ManagerMiddleware`, по выходу из хэндлера
`close_manager()` обнуляет ему `_data`/`_event` — `manager.py:621`). Поэтому для
всего, что снаружи, существует `BgManager`.

> Доступа к текущему состоянию/`dialog_data` у `BgManager` НЕТ
> (`docs/bg/index.rst:16`): «все эти действия выполняются в фоне, и у вас нет
> доступа к текущему state или dialog data». Чтобы получить доступ — нужен
> контекст `fg()` (см. §6).

---

## 2. Как получить BgManagerFactory

`setup_dialogs(...)` **возвращает** `BgManagerFactory` (`setup.py:230`, объект
`BgManagerFactoryImpl`, `setup.py:245`). Способы достать фабрику:

| Откуда | Как | Ссылка |
|---|---|---|
| Результат `setup_dialogs` | `dialog_bg_factory = setup_dialogs(dp)` | `docs/bg/index.rst:55`, `setup.py:253` |
| Inject в любой aiogram-хэндлер | аргумент `dialog_bg_factory: BgManagerFactory` | `docs/bg/index.rst:41` |
| Inject по ключу в middleware | `data[BG_FACTORY_KEY]`, `BG_FACTORY_KEY = "dialog_bg_factory"` | `manager_middleware.py:17,79` |
| Из dialog-хэндлера | `manager.middleware_data["dialog_bg_factory"]` | `docs/bg/index.rst:62` |

Фабрика прокидывается **во все** observers через `BgFactoryMiddleware` как
**outer**-middleware (`setup.py:168-170`, `manager_middleware.py:62-80`), поэтому
ключ `dialog_bg_factory` доступен в любом хэндлере/мидлваре, зарегистрированном
после `setup_dialogs`.

### Сигнатура `BgManagerFactory.bg` (`api/protocols/manager.py:83`, реализация `bg_manager.py:292`)

```python
def bg(
    self,
    bot: Bot,                 # ОБЯЗАТЕЛЕН: у фабрики нет «текущего» bot
    user_id: int,             # ОБЯЗАТЕЛЕН
    chat_id: int,             # ОБЯЗАТЕЛЕН
    stack_id: str | None = None,            # None -> DEFAULT_STACK_ID ("")
    thread_id: int | None = None,
    business_connection_id: str | None = None,
    load: bool = False,       # подгрузить реальные Chat/User из Telegram
) -> BaseDialogManager: ...
```

Возврат — `BgManager`. Внутри `user`/`chat` оборачиваются в `FakeUser`/`FakeChat`
(`bg_manager.py:302-303`); `stack_id=None` => `DEFAULT_STACK_ID = ""`
(`bg_manager.py:304`, `stack.py:13`). У фабрики нет event_context, поэтому
`thread_id` / `business_connection_id` НЕ наследуются — передавайте явно.

---

## 3. Как получить BgManager из существующего менеджера: `manager.bg(...)`

Сигнатура `BaseDialogManager.bg` (`api/protocols/manager.py:64`); две реализации,
поведение идентичное: `DialogManagerImpl.bg` (`manager.py:564`) и
`BgManager.bg` (`bg_manager.py:111`).

```python
def bg(
    self,
    user_id: int | None = None,                       # None -> текущий
    chat_id: int | None = None,                       # None -> текущий
    stack_id: str | None = None,                      # см. логику ниже
    thread_id: int | UnsetId | None = UnsetId.UNSET,  # UNSET -> наследуется
    business_connection_id: str | UnsetId | None = UnsetId.UNSET,
    load: bool = False,
) -> BaseDialogManager: ...
```

Здесь `bot` уже известен из текущего event_context — передавать не нужно (главное
отличие от фабрики).

### Логика подстановки user/chat/stack/intent (важно!)

* `user_id=None` или равен текущему → берётся **реальный** `User` из контекста;
  иначе создаётся `FakeUser(id=..., first_name="")` (`bg_manager.py:99-103`).
* `chat_id=None`/текущий → реальный `Chat`; иначе `FakeChat(id=..., type="")`
  (`bg_manager.py:105-109`). В `DialogManagerImpl` есть нюанс: если у события нет
  чата (`event_chat` отсутствует) и `chat_id` не передан — кидается
  `ValueError("Explicit chat_id is required ...")` (`manager.py:557-561`).
* `thread_id` / `business_connection_id` = `UnsetId.UNSET` (sentinel,
  `api/protocols/manager.py:20`) → значение **наследуется**, но ТОЛЬКО если
  user и chat совпадают с текущими (`coalesce_*`, `bg_manager.py:41-70`). Если
  целевой чат/пользователь другой — `business_connection_id` обнуляется в `None`,
  `thread_id` тоже в `None`. То есть для чужого чата thread/business не
  «протекают». Передать `None` явно тоже можно — он перекроет наследование.
* `stack_id`:
  - если передан явно → используется он, `intent_id = None`
    (`bg_manager.py:147-148`);
  - если `None` **и** новый event_context идентичен текущему → наследуется
    текущий `stack_id` и текущий `intent_id` (`bg_manager.py:140-143`;
    в `DialogManagerImpl` — `current_stack().id` и `current_context().id`,
    `manager.py:597-601`);
  - если `None` **и** контекст изменился (другой чат/юзер/thread/business) →
    `stack_id = DEFAULT_STACK_ID ("")`, `intent_id = None`
    (`bg_manager.py:144-146`).

> Практический вывод: `manager.bg()` без аргументов = «тот же чат, тот же стек,
> тот же intent» — именно так делают прогресс-бар-примеры
> (`example/loading.py:61`, `docs/widgets/text/progress/example.py:47`).
> `manager.bg(user_id=other, chat_id=other)` = «другой получатель, дефолтный стек».

---

## 4. Методы BgManager (что доступно вне хэндлера)

Все методы — `async`, возвращают `None`, и **ничего не делают синхронно**: они
лишь ставят искусственный апдейт в очередь loop'а (через `Updater.notify`) и сразу
возвращают управление. Реальная работа происходит позже, в обработчике
`handle_update`.

| Метод | Сигнатура | Что эмитит | Эффект (в `handle_update`) |
|---|---|---|---|
| `done` | `done(result=None, show_mode=None)` (`bg_manager.py:198`) | `DialogUpdateEvent(action=DONE)` | `dialog_manager.done(result=...)` — закрыть текущий диалог, показать нижний |
| `start` | `start(state, data=None, mode=StartMode.NORMAL, show_mode=None, access_settings=None)` (`bg_manager.py:213`) | `DialogStartEvent(action=START)` | `dialog_manager.start(...)` — открыть диалог и показать |
| `switch_to` | `switch_to(state, show_mode=None)` (`bg_manager.py:234`) | `DialogSwitchEvent(action=SWITCH)` | `switch_to(state)` + `show()` |
| `update` | `update(data=None, show_mode=None)` (`bg_manager.py:250`) | `DialogUpdateEvent(action=UPDATE)` | вписать `data` в `dialog_data` и `show()` |
| `bg` | см. §3 | — (синхронный) | вернуть новый `BgManager` |
| `fg` | `fg()` async-ctxmgr (`bg_manager.py:265`) | `DialogFgEvent(action=FG)` | см. §6 |

Тело каждого: `await self._load()` (опционально, см. §7) → `await self._notify(...)`
(`bg_manager.py:173-176`). `_notify` собирает `DialogUpdate(aiogd_update=event)` и
зовёт `Updater.notify`. Базовые параметры события (`from_user`, `chat`,
`intent_id`, `stack_id`, `thread_id`, `business_connection_id`) берутся из
`_base_event_params()` (`bg_manager.py:162-171`).

> `update_handler.handle_update` для `UPDATE` молча выходит, если нет контекста:
> `if not dialog_manager.has_context(): logger.warning("No context found"); return`
> (`update_handler.py:35-37`). То есть фоновый `update()` по пустому/закрытому
> стеку — это просто warning в лог, без ошибки и без сообщения.

---

## 5. Механизм доставки: DIALOG_EVENT_NAME и Updater

Это сердце зоны. Последовательность:

1. **Регистрация при setup.** `setup_dialogs` создаёт кастомный observer
   `router.observers["aiogd_update"]` (`setup.py:39-42`) и регистрирует на нём
   `handle_update` для `any_state` (`setup.py:45-47, 232`).
   `DIALOG_EVENT_NAME = "aiogd_update"` (`update_event.py:20`).

2. **Эмиссия.** `BgManager._notify` строит `DialogUpdate(Update)` — это **подделка
   под aiogram `Update`** с лишним полем `aiogd_update: DialogUpdateEvent`
   (`update_event.py:62-74`). Его `event_type` == `"aiogd_update"`, `event` ==
   вложенный `DialogUpdateEvent`. `update_id=0`.

3. **Постановка в очередь.** `Updater.__init__` поднимается по `parent_router` до
   корня и требует, чтобы корень был `Dispatcher`, иначе
   `TypeError("Root router must be Dispatcher.")` (`updater.py:11-16`).
   `notify()` (`updater.py:18-24`) НЕ обрабатывает апдейт сразу — он делает
   `loop.call_soon(callback, context=copy_context())`, а callback внутри —
   `asyncio.create_task(self._process_update(...))`. То есть: возврат немедленный,
   обработка — на следующей итерации loop, в **копии** текущего contextvars.

4. **Прогон через диспетчер.** `_process_update` (`updater.py:30-40`) зовёт
   `dp.propagate_event(update_type="update", event=update, bot=..., event_from_user=event.from_user, event_chat=event.chat, event_thread_id=event.thread_id, **dp.workflow_data)`.
   Тот прогоняет искусственный `Update` через весь конвейер. Сработает observer
   `aiogd_update` → middlewares (intent + manager) поднимут реальный
   `DialogManager` для указанных chat/stack/intent → `handle_update`.

5. **Применение.** `handle_update` (`update_handler.py:16-43`):
   - сначала `dialog_manager.show_mode = event.show_mode or ShowMode.AUTO`;
   - по типу события вызывает `start` / (`switch_to`+`show`) / `update`-логику /
     `done` на **полноценном** менеджере. Дальше — обычный рендер и
     `MessageManager` (см. §8).

### Подводный камень с middlewares (из доки)

`docs/bg/index.rst:90`: «Background manager шлёт кастомные события через aiogram
dispatcher, поэтому ваши middlewares **по умолчанию не сработают** на них». Чтобы
ваш middleware видел фоновые апдейты, регистрируйте его на observer событий
диалога:

```python
from aiogram_dialog import DIALOG_EVENT_NAME
dispatcher.observers[DIALOG_EVENT_NAME].middleware(MyMiddleware())
```

(Внутренние middlewares aiogram-dialog — manager/intent/context — на observer
`aiogd_update` уже навешаны в `setup.py:134,144,157,164`.)

---

## 6. Контекст `fg()` — «дотянуться» до полноценного менеджера из фона

Если в фоне нужен реальный доступ к `dialog_data` / `start_data` / виджетам —
используйте async-контекст `fg()` (`bg_manager.py:265-285`).

```python
async with bg_manager.fg() as manager:   # manager: DialogManager (полноценный!)
    manager.dialog_data["progress"] = i
    await manager.update()
```

Как устроено:

* эмитится `DialogFgEvent` с двумя `asyncio.Future`: `entered` и `exited`
  (`update_event.py:57-59`, `bg_manager.py:267-272`);
* апдейт ставится через `notify_task` (а не `notify`!) — возвращается `Task`,
  который выполняется в **копии** контекста (`updater.py:26-28`);
* `await event.entered` — ждём, пока `handle_update` поднимет реальный менеджер и
  сделает `event.entered.set_result(dialog_manager)` (`update_handler.py:31-33`);
* пока вы внутри `with`, обработчик «висит» на `await event.exited`
  (`update_handler.py:33`) — то есть контекст/стек **заблокирован** на вас;
* на выходе — `event.exited.set_result(None)` (или `set_exception(e)` при ошибке,
  `bg_manager.py:280-284`), затем `await task`.

> Важно: `DialogManagerImpl.fg()` — это просто `yield self` (`manager.py:617-619`),
> т.е. внутри обычного хэндлера `fg()` ничего не пересоздаёт. А вот `BgManager.fg()`
> — это полноценный «вход» в диалог через диспетчер. Внутри `with` все изменения
> происходят в захваченном контексте и атомарно сохраняются context_saver'ом по
> завершении обработчика.

Примеры: `example/loading.py:64-72` (прогресс через `fg()` + `m.update()`),
тесты `tests/test_fg.py:36-44` (`bg(user_id=2, chat_id=-1).fg()` — старт диалога
для другого пользователя в групповом чате с немедленным выполнением).

---

## 7. `load=True` — подгрузка реальных Chat/User

По умолчанию `BgManager` оперирует `FakeChat(type="")` / `FakeUser(first_name="")`
(`fake_data.py:22-27`) — у них помечено `fake = True`, и `is_chat_loaded` /
`is_user_loaded` возвращают `False` (`utils.py:160-175`).

`_load()` (`bg_manager.py:178-196`) при `load=True`:
* если чат «fake» → `bot.get_chat(chat_id)`;
* если юзер «fake» → `bot.get_chat_member(chat_id, user_id).user`.

Зачем: реальный объект нужен виджетам/геттерам, которые читают `event.from_user`
или `event_chat` (имя, username, тип чата) — для них fake-данные пусты. **Минусы:**
2 лишних запроса к Telegram API на каждый фоновый вызов; может упасть, если бот не
видит чат/участника. Пример с `load=True`:
`docs/widgets/text/progress/bg_manager_example.py:7`.

> `_calc_show_mode` смотрит `event_chat.type` (см. §9). Для fake-чата тип == `""`
> (не PRIVATE), поэтому без `load=True` фоновый AUTO почти всегда выберет `EDIT`,
> даже если реальный чат приватный. Если важна корректная логика SEND/EDIT по
> типу чата — ставьте `load=True` либо задавайте `show_mode` явно.

---

## 8. Как библиотека решает edit / send / delete (`MessageManager.show_message`)

Финальное решение принимает `MessageManager.show_message`
(`message_manager.py:168-214`). На вход — `new_message: NewMessage` (с уже
вычисленным конкретным `show_mode`, не AUTO) и `old_message: OldMessage | None`
(восстановлен из стека: `manager.py:475-499` — берёт `last_message_id`,
`last_reply_keyboard`, `content_type` и т.д.; текст помечен `UnknownText.UNKNOWN`,
т.к. реального текста в сторадже нет).

Дерево решений (по порядку):

1. `show_mode is NO_UPDATE` → `raise MessageNotModified` — ничего не шлём, ids не
   сохраняем (`message_manager.py:172-174`; в `manager.show` это ловится,
   `manager.py:401-404`).
2. `old_message` есть **и** `show_mode is DELETE_AND_SEND` → удалить старое и
   послать новое. Порядок оптимизирован, чтобы не мигало: при reply-клавиатуре
   сперва шлём, потом удаляем; иначе наоборот (`message_manager.py:175-187`).
3. `old_message` нет **или** `show_mode is SEND` → снять старую клавиатуру и
   послать новое сообщение (`message_manager.py:188-198`).
4. `_message_changed(...)` == `False` → ничего не делаем, возвращаем старое
   (`message_manager.py:200-203`). Сравнение приблизительное: клавиатуры толком
   не сравнить (наличие любой reply_markup => считаем «изменилось»), link preview
   и media-id учитываются (`message_manager.py:129-153`).
5. `_can_edit(...)` == `False` → удалить и послать заново. Нельзя редактировать,
   если: убрали media, была/будет voice, была/будет reply-клавиатура
   (`message_manager.py:155-166`).
6. Иначе — `edit_message_safe`: пытаемся `edit_text` / `edit_caption` /
   `edit_media` (`message_manager.py:305-337`). На `"message is not modified"` →
   `MessageNotModified`; на `"message can't be edited"` / `"message to edit not
   found"` → **fallback на send** (`message_manager.py:308-319`).

`remove_*` и `edit_*`/`delete` обёрнуты в защиту от типовых `TelegramBadRequest`
(`message to delete not found`, `message can't be deleted`, `MESSAGE_ID_INVALID`
и т.п.) — `message_manager.py:242-302`. Business-сообщения нельзя удалять — для них
вместо delete просто снимается клавиатура (`message_manager.py:282-290`).

После успешной отправки/редактирования `manager.show` вызывает
`_save_last_message` (`manager.py:406, 501`), обновляя `last_message_id` в стеке,
плюс кеширует `media_id`.

---

## 9. ShowMode при фоновых обновлениях (почему EDIT может слать новое)

`ShowMode` (`api/entities/modes.py:4-34`):

| Значение | Поведение |
|---|---|
| `AUTO` | дефолт: вычисляется через `_calc_show_mode` |
| `EDIT` | редактировать существующее сообщение диалога |
| `SEND` | послать новое сообщение |
| `DELETE_AND_SEND` | удалить старое и послать новое (delete не работает >48ч) |
| `NO_UPDATE` | не трогать сообщение вообще |

`_calc_show_mode` (`manager.py:510-527`) для `AUTO`:

```
если show_mode != AUTO            -> вернуть как есть
если event_chat.type != PRIVATE   -> EDIT
если last_reply_keyboard          -> DELETE_AND_SEND
если stack.id != DEFAULT_STACK_ID -> EDIT
если event — Message:
    media_group_id is None                 -> SEND
    media_group_id == last_income_group_id  -> EDIT
    иначе                                   -> SEND
иначе (callback, фоновое событие и т.п.)    -> EDIT
```

`ShowMode.important` из доки (`docs/how_are_messages_updated/index.rst:13`):
«ShowMode меняется только на **следующий** апдейт, потом возвращается к AUTO».

### Почему фоновый EDIT может фактически послать НОВОЕ сообщение

Это ключевой «сюрприз» зоны. EDIT — это *намерение*, а не гарантия. Сообщение
уедет как новое в нескольких случаях:

1. **Старого сообщения нет** (`old_message is None`: стек только что создан, либо
   `last_message_id` потёрли) → ветка 3 в §8 всегда шлёт новое
   (`message_manager.py:188`). Поэтому фоновый `start()` логично создаёт новое
   сообщение.
2. **Редактирование невозможно** (`_can_edit == False`): на месте была/нужна
   reply-клавиатура, voice, или удаляется media → удалить+послать
   (`message_manager.py:205-210`).
3. **Telegram отказал в edit**: «message can't be edited» / «message to edit not
   found» → fallback на send (`message_manager.py:313-317`). Типично, если
   пользователь руками удалил сообщение бота, или прошло слишком много времени.
4. **AUTO в фоне почти всегда даёт EDIT, но...** для фонового события `event` —
   это `DialogUpdateEvent` (не `Message`), значит ветка `isinstance(self.event,
   Message)` не срабатывает и возвращается `EDIT` (последняя строка
   `manager.py:527`). НО если `event_chat.type != PRIVATE` (а для `FakeChat` тип
   == `""` ≠ PRIVATE — см. §7) тоже `EDIT`. Так что без `load=True` фон по AUTO
   стабильно идёт в EDIT — и если редактировать нечего, превращается в send по
   п.1–3.

> Доп. нюанс из `prevent_new_message.py` (`docs/widgets/text/progress/`): чтобы
> ответ пользователя в приватном чате (где AUTO→SEND) не плодил новое сообщение,
> в `MessageInput` ставят `dialog_manager.show_mode = ShowMode.EDIT`. Это не про
> фон напрямую, но та же механика «AUTO в приватном чате на Message = SEND».

---

## 10. Связи с остальной библиотекой

* **`setup_dialogs`** (`setup.py`) — точка, где регистрируется observer
  `aiogd_update` + `handle_update`, и где рождается `BgManagerFactoryImpl`. Без
  `setup_dialogs` фоновые апдейты доехать не могут.
* **`Updater`** (`updater.py`) — мост в aiogram `Dispatcher.propagate_event`.
  Требует, чтобы корень роутера был `Dispatcher`.
* **`DialogUpdate` / `DialogUpdateEvent`** (`update_event.py`) — «псевдо-aiogram
  Update», переносящий действие (`DialogAction`: DONE/START/UPDATE/SWITCH/FG) и
  адресацию (chat/user/stack/intent/thread/business).
* **`ManagerMiddleware` / `IntentMiddleware`** — на фоновом апдейте поднимают
  полноценный `DialogManager` для целевого стека (через `STORAGE_KEY`,
  intent/stack из события).
* **`MessageManager`** — единственное место, где реально дёргается Telegram Bot
  API для показа сообщения; кастомизируется через `setup_dialogs(message_manager=...)`.
* **`FakeChat` / `FakeUser`** (`fake_data.py`) + `is_*_loaded` (`utils.py`) —
  механизм «ленивых» получателей и флаг для `load=True`.
* **`test_tools`** (`MockMessageManager`, `BotClient`) — позволяет тестировать фон
  без реального Telegram (см. `tests/test_fg.py`).

---

## 11. Рабочие примеры

### 11.1. Прогресс-бар из фоновой задачи (через `bg().update()`)

```python
# docs/widgets/text/progress/example.py
async def background(manager: BaseDialogManager):
    count = 10
    for i in range(1, count + 1):
        await asyncio.sleep(1)
        await manager.update({"progress": i * 100 / count})
    await asyncio.sleep(1)
    await manager.done()

@dp.message(Command("start"))
async def start_handler(message: Message, dialog_manager: DialogManager):
    await dialog_manager.start(state=Main.progress)
    asyncio.create_task(background(dialog_manager.bg()))  # тот же чат/стек/intent
```

### 11.2. Прогресс через `fg()` (нужен прямой доступ к `dialog_data`)

```python
# example/loading.py
async def background(callback: CallbackQuery, manager: BaseDialogManager):
    count = 10
    for i in range(1, count + 1):
        await asyncio.sleep(1)
        async with manager.fg() as m:        # m: полноценный DialogManager
            m.dialog_data["progress"] = i * 100 / count
            await m.update()
    await asyncio.sleep(1)
    await manager.done()
```

### 11.3. Старт диалога для ДРУГОГО пользователя/чата

```python
# из вебхука / другого хэндлера
bg = bg_factory.bg(bot=bot, user_id=other_user, chat_id=other_chat, load=True)
await bg.start(SomeSG.first, mode=StartMode.RESET_STACK)
# или из существующего менеджера:
bg = manager.bg(user_id=other_user, chat_id=other_chat)  # stack_id="" по умолч.
await bg.start(SomeSG.first)
```

### 11.4. Фоновый «достучаться» с явным show_mode

```python
bg = manager.bg()
await bg.update({"x": 1}, show_mode=ShowMode.EDIT)   # принудительно редактировать
await bg.switch_to(SomeSG.next, show_mode=ShowMode.DELETE_AND_SEND)
```

---

## 12. Подводные камни для продакшн-шаблона

* **`bg()` требует валидных `user_id`/`chat_id`/`stack_id`.** `BgManager` не
  валидирует существование чата/стека до отправки апдейта. Неверная адресация =
  тихий промах: `handle_update` для `UPDATE` без контекста только пишет
  `logger.warning("No context found")` и выходит (`update_handler.py:35-37`) — ни
  исключения, ни сообщения пользователю. Для чужого чата `stack_id` по умолчанию
  становится `""` (DEFAULT_STACK_ID) — это **другой** стек, чем у текущего юзера;
  если вам нужен конкретный стек — передавайте его явно.

* **Асинхронность и гонки.** Методы `BgManager` возвращаются **до** реального
  выполнения (`Updater.notify` ставит задачу через `call_soon` —
  `updater.py:18-24`). Несколько подряд `bg.update()` из плотного цикла без
  `await asyncio.sleep` могут наложиться, перегнать друг друга и упереться в
  flood-limit Telegram при частых edit. Дросселируйте частоту обновлений
  (как в примерах — `sleep(1)`), и помните: between-апдейт изменения
  `dialog_data` видны только если они были сохранены (context_saver) предыдущим
  обработчиком.

* **`fg()` сериализует доступ к контексту/стеку.** Пока вы внутри `async with
  bg.fg()`, соответствующий стек заблокирован (обработчик висит на
  `await event.exited`, `update_handler.py:33`). Долгая работа внутри `with`
  держит лок и блокирует другие апдейты этого пользователя/стека. Делайте тело
  `with` коротким (мутация данных + `update()`), тяжёлую логику — снаружи.

* **`load=True` стоит запросов и может падать.** Каждый `_load` для fake-данных =
  до двух вызовов API (`get_chat`, `get_chat_member`, `bg_manager.py:185,193`).
  В вебхуках/брокерах это лишняя задержка и точка отказа (бот может не иметь
  доступа к чату/участнику). Включайте `load=True` только когда геттеры/виджеты
  реально читают данные пользователя/чата, либо когда важна AUTO-логика
  SEND/EDIT по типу чата (без него fake-чат имеет `type=""` ≠ PRIVATE).

* **EDIT не гарантирует редактирование.** Фоновый `EDIT`/AUTO может послать новое
  сообщение (нет старого / нельзя редактировать / Telegram отказал — §9). Если
  важно «никогда не плодить сообщения», ловите случай удалённого сообщения и/или
  используйте `ShowMode.NO_UPDATE` там, где показ не нужен.

* **Middlewares не срабатывают на фоновых событиях по умолчанию.** Любую вашу
  бизнес-middleware (auth, throttling, i18n), от которой зависит рендер диалога,
  нужно дополнительно навесить на `dispatcher.observers[DIALOG_EVENT_NAME]`
  (`docs/bg/index.rst:90-96`), иначе фоновый рендер пойдёт без неё.

* **Корень роутера обязан быть `Dispatcher`.** `Updater.__init__` поднимается до
  корня и кидает `TypeError("Root router must be Dispatcher.")`
  (`updater.py:12-15`), если `setup_dialogs` был вызван на изолированном `Router`,
  не включённом в `Dispatcher`. Включайте dialog-роутеры в `Dispatcher` до
  фоновых вызовов.
