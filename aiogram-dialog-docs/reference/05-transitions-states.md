---
zone: "05 — Переходы между окнами и диалогами"
title: "Transitions & States: start / done / switch, StartMode, ShowMode, LaunchMode, вложенные диалоги"
source_repo: "/tmp/aiogram_dialog"
source_rev: "develop @ 08abdf0 (2026-05-02)"
aiogram: ">=3.14.0"
verified_against_code: true
tags: [aiogram-dialog, transitions, stack, start, done, switch, StartMode, ShowMode, LaunchMode, nested-dialogs, sub-dialogs]
---

# Зона 05. Переходы между окнами и диалогами

Эта заметка покрывает все способы менять то, что видит пользователь: переключение окон
внутри диалога (`switch_to` / `next` / `back`), запуск нового диалога (`start` + `StartMode`),
закрытие (`done`) с возвратом результата, режимы перерисовки (`ShowMode`), режимы запуска
диалога (`LaunchMode`), стек задач (task stack), вложенные диалоги (sub-dialogs) и инструмент
визуализации `render_transitions`.

---

## 0. Базовая модель: task stack и context

Понять переходы невозможно без модели стека.

- **Stack** (`src/aiogram_dialog/api/entities/stack.py:38`) — `@dataclass(unsafe_hash=True)`.
  Хранит **только список `intents: list[str]`** (id контекстов) + метаданные последнего
  отрисованного сообщения (`last_message_id`, `last_media_id`, `content_type`,
  `has_protected_content`, `last_reply_keyboard`, `last_income_media_group_id`) и
  `access_settings`. У стека есть `id` (`stack.py:53`). Дефолтный стек имеет
  `DEFAULT_STACK_ID = ""` (`stack.py:13`).
  - `push(state, data) -> Context` (`stack.py:57`) — создаёт новый `Context` с новым
    `intent_id`, добавляет id в `intents`. При `len(intents) >= _STACK_LIMIT (=100)`
    бросает `DialogStackOverflow` (`stack.py:58`, `stack.py:15`).
  - `pop()` (`stack.py:72`) — снимает верхний intent_id. `last_intent_id()`,
    `empty()`, `default()`.
- **Context** (`src/aiogram_dialog/api/entities/context.py:11`) — `@dataclass(unsafe_hash=True)`.
  Поля: `_intent_id`, `_stack_id`, `state: State`, `start_data: Data`, `dialog_data: dict`,
  `widget_data: dict`, `access_settings`. Это «локальные переменные» одного запуска диалога:
  `start_data` (вход), `dialog_data` (рабочие данные), `widget_data` (состояния виджетов).
  Доступны через `manager.start_data` / `manager.dialog_data` / `manager.current_context()`.
- `Data = dict | list | int | str | float | None` (`context.py:7`) — тип `start_data` и
  `result`. **Должен быть JSON-сериализуемым**, т.к. хранится в FSM-storage.

Ключевые инварианты:
- Каждый `start` → новая запись в стеке + новый context (своя пустая `dialog_data`).
- Каждый `done` → запись и context удаляются из storage, пользователь возвращается к нижележащему.
- Можно запустить **один и тот же диалог несколько раз** — каждый получит свой context.
  Поэтому не забывайте чистить стек (иначе он «съест» память) — лимит 100 диалогов на стек.

---

## 1. Переключение окна внутри диалога (state switch)

Не трогает стек, не меняет context — просто меняет `context.state` и перерисовывает окно.
Все данные (`dialog_data`, `widget_data`) сохраняются.

### `manager.switch_to(state, show_mode=None)`
`src/aiogram_dialog/manager/manager.py:355`

```python
async def switch_to(self, state: State, show_mode: ShowMode | None = None) -> None
```
- Проверяет `context.state.group == state.group`, иначе `ValueError`
  (`manager.py:362`) — **переключаться можно только внутри своей `StatesGroup`**.
  Для перехода в другой диалог — это `start`, а не `switch_to`.
- Устанавливает `self.show_mode = show_mode or self.show_mode` и просто пишет
  `context.state = state` (`manager.py:367-368`). **Сам по себе не вызывает `show()`** —
  перерисовку обеспечивает обёртка (хендлер после обработки колбэка, либо
  `update_handler` для bg, см. §8). При вызове из обработчика клика `Dialog._callback_handler`
  → `_need_refresh` → `show()` (`dialog.py:156-157`, `dialog.py:160-178`).

### `manager.next(show_mode=None)` / `manager.back(show_mode=None)`
`src/aiogram_dialog/manager/manager.py:327` / `:341`
- Берут `self.dialog().states()` (порядок = порядок передачи `Window` в `Dialog`),
  находят индекс текущего state и переключаются на `+1` / `-1` через `switch_to`.
- `next` на последнем окне → `ValueError` (`manager.py:331`); `back` на первом → `ValueError`
  (`manager.py:345`). **Нет цикличности** — это краевой случай для динамических визардов.

### Виджеты-кнопки
`src/aiogram_dialog/widgets/kbd/state.py`
- `SwitchTo(text, id, state, on_click=None, when=None, show_mode=None, style=...)`
  (`state.py:38`) — вызывает `manager.switch_to(self.state, show_mode=...)`; сначала
  пользовательский `on_click`, потом переключение (`state.py:58-64`).
- `Next(text=Const("Next"), id="__next__", on_click=None, show_mode=None, ...)`
  (`state.py:67`) — `manager.next(...)`. **id по умолчанию `"__next__"`**.
- `Back(text=Const("Back"), id="__back__", ...)` (`state.py:96`) — `manager.back(...)`.
  **id по умолчанию `"__back__"`**.
- Подводный камень из доки (`docs/transitions/index.rst:64`): у `Back`/`Next` дефолтные id
  совпадают. Если в окне **несколько** кнопок одного типа с разными `on_click` — задавайте
  явные уникальные `id`, иначе коллизия callback_data.

Императивный пример (`docs/transitions/switch.py`) vs кнопочный (`docs/transitions/buttons.py`):
кнопки `SwitchTo`/`Back`/`Next` — это просто обёртки над одноимёнными методами менеджера.

---

## 2. Запуск диалога — `manager.start(...)` и `StartMode`

### Сигнатура
`src/aiogram_dialog/manager/manager.py:241` (протокол — `api/protocols/manager.py:35`)

```python
async def start(
    self,
    state: State,
    data: Data = None,                       # → context.start_data, доступно как manager.start_data
    mode: StartMode = StartMode.NORMAL,
    show_mode: ShowMode | None = None,
    access_settings: AccessSettings | None = None,
) -> None
```
- `state` идентифицирует **диалог** (по группе) и стартовое окно. Не обязательно первое окно
  группы, но будьте аккуратны (`docs/transitions/index.rst:78`).
- `data` сохраняется в новый context как `start_data`. Запущенный диалог **не имеет доступа**
  к родительскому context — общение только через `start_data` (вход) и `result` в `done` (выход).
- Поток по `mode` (`manager.py:251-259`): `NORMAL` → `_start_normal`;
  `RESET_STACK` → `reset_stack(remove_keyboard=False)` + `_start_normal`;
  `NEW_STACK` → `_start_new_stack`; иначе `ValueError`.

### `_start_normal` — что происходит при обычном старте
`src/aiogram_dialog/manager/manager.py:284`
1. Если стек не пуст — берём `old_dialog`. **Если у текущего (верхнего) диалога
   `launch_mode is EXCLUSIVE` → `ValueError`** (`manager.py:292-296`). То есть поверх
   EXCLUSIVE-диалога стартовать ничего нельзя.
   > Подводный камень: текст ошибки гласит `"...launch_mode==SINGLE"`, хотя проверяется
   > `EXCLUSIVE` — это неточность сообщения, а не логики.
2. `new_dialog = registry.find_dialog(state)`; `_process_launch_mode(old, new)` (см. §4).
3. Если есть текущий context — он сохраняется в storage; `access_settings` наследуется
   из текущего context, затем из стека, если не передан явно (`manager.py:300-305`).
4. `context = stack.push(state, data)` → новый context кладётся как текущий
   (`manager.py:307-309`).
5. `await self.dialog().process_start(self, data, state)` — внутри `Dialog.process_start`
   делает `switch_to(state)` и вызывает `on_start` (`dialog.py:86-96`).
6. Если после `process_start` контекст не сменился (id совпал) → `show()`
   (`manager.py:311-313`). Если внутри `on_start` запустили ещё один диалог — повторного
   `show()` текущего не будет (это и используется в цепочках вложенных стартов).

### `StartMode`
`src/aiogram_dialog/api/entities/modes.py:37`

| Значение | Что делает со стеком | Когда использовать |
|---|---|---|
| `NORMAL` (default) | Кладёт диалог **поверх** текущего стека (`stack.push`). Текущий диалог остаётся под ним. | Обычный переход «вглубь», sub-dialog. |
| `RESET_STACK` | Полностью **очищает текущий стек** (`reset_stack(remove_keyboard=False)`), затем `NORMAL`. Старые контексты удаляются из storage. | Команда `/start`, «начать заново». Клавиатуру старого сообщения **не убирает** (remove_keyboard=False) — её перетрёт новый рендер. |
| `NEW_STACK` | Создаёт **новый отдельный стек** (`Stack()`), диалог запускается в нём через background-менеджер. Старый стек сохраняется и работает независимо. | Параллельные независимые «нити» (новое сообщение). См. `example/multistack.py`. |

### `reset_stack(remove_keyboard=True)`
`src/aiogram_dialog/manager/manager.py:261` — снимает все контексты из storage, опционально
убирает клавиатуру последнего сообщения, обнуляет текущий context. **Не вызывает колбэки**
`on_close` (доступно и как публичный метод протокола, `api/protocols/manager.py:194`).

### `NEW_STACK` — детали и ограничения
`_start_new_stack` (`manager.py:272`): создаёт `Stack()` и делает
`self.bg(stack_id=stack.id).start(state, data, mode=NORMAL, ...)`. То есть **через
background-менеджер и механизм нотификаций** (`update_handler`, §8), а не прямым вызовом.
Следствия/ограничения:
- Диалог в **не-дефолтном стеке** не может использовать `ReplyKeyboardMarkup` —
  `_ensure_stack_compatible` бросает `InvalidKeyboardType` (`manager.py:370-378`).
- `MessageInput` и текстовый ввод в неосновном стеке работают только при reply на сообщение
  с кнопками (комментарий в `example/multistack.py:87-88`), т.к. апдейт нужно сматчить со стеком.
- `_calc_show_mode` для неосновного стека по умолчанию даёт `EDIT` (`manager.py:517-518`).

### Виджет `Start`
`src/aiogram_dialog/widgets/kbd/state.py:153`
```python
Start(text, id, state, data=None, on_click=None, show_mode=None,
      mode=StartMode.NORMAL, when=None, style=...)
```
Вызывает `manager.start(state=..., data=self.start_data, mode=self.mode, show_mode=...)`
(`state.py:177-188`). Сначала пользовательский `on_click`, потом старт.
`render_transitions` распознаёт `Start` как ребро графа (зелёное).

---

## 3. Закрытие диалога — `manager.done(...)` и передача результата

### Сигнатура
`src/aiogram_dialog/manager/manager.py:196`
```python
async def done(self, result: Any = None, show_mode: ShowMode | None = None) -> None
```

### Алгоритм (`manager.py:196-217`)
1. `self.show_mode = show_mode or self.show_mode`.
2. `await self.dialog().process_close(result, self)` → вызывает `on_close(result, manager)`
   закрываемого диалога (`dialog.py:216-219`).
3. `old_context = current_context()`; `await self.mark_closed()`.
4. **`mark_closed`** (`manager.py:229-239`): `stack.pop()`, удаляет context из storage; если
   стек пуст → `CONTEXT_KEY = None`, иначе загружает context нижележащего диалога; сохраняет стек.
5. Если после pop **контекста нет** (закрыли корневой диалог) →
   `_process_last_dialog_result` (`manager.py:188-194`) → просто `_remove_kbd()` (убирает
   клавиатуру у последнего сообщения). **`on_process_result` родителя НЕ вызывается** — его нет.
6. Если контекст есть → `dialog.process_result(old_context.start_data, result, self)` для
   **нижележащего** диалога (`manager.py:213-214`).
7. Если контекст после этого не сменился (id совпал) → `show(show_mode)` (`manager.py:215-217`).

### Как результат попадает в родителя — `process_result`
`src/aiogram_dialog/dialog.py:198`
```python
async def process_result(self, start_data: Data, result: Any, manager) -> None:
    context = manager.current_context()
    await self._process_callback(self.on_process_result, start_data, result, manager)
    if context.id == manager.current_context().id:
        await self.windows[context.state].process_result(start_data, result, manager)
```
- Вызывается `on_process_result(start_data, result, manager)` родителя.
  **`start_data` здесь — это `start_data` ЗАКРЫВШЕГОСЯ (дочернего) диалога**
  (`old_context.start_data`), а `result` — то, что передали в `done(result=...)`.
- Затем, если context не сменился внутри `on_process_result`, вызывается
  `Window.process_result` текущего окна родителя (`window.py:141-145`) → его
  `on_process_result(start_data, result, manager)`.
- Сигнатура колбэка: `OnResultEvent = Callable[[Data, Any, DialogManager], Awaitable]`
  (`dialog.py:32`). Регистрируется на уровне `Dialog(on_process_result=...)` или
  `Window(on_process_result=...)`.

Минимальный пример (`docs/transitions/done.py`):
```python
async def main_process_result(start_data, result, dialog_manager):
    print("We have result:", result)

dialog = Dialog(Window(..., Start(..., state=SubDialogSG.first)),
                on_process_result=main_process_result)

async def close_subdialog(callback, button, manager):
    await manager.done(result={"name": "Tishka17"})
```

### Виджет `Cancel`
`src/aiogram_dialog/widgets/kbd/state.py:124`
```python
Cancel(text=Const("Cancel"), id="__cancel__", result=None, on_click=None,
       when=None, show_mode=None, style=...)
```
Вызывает `manager.done(self.result, show_mode=...)` (`state.py:144-150`). Чтобы вернуть
данные из кнопки — задайте `result=...`. id по умолчанию `"__cancel__"`.

> Краевой случай (тест `test_finish_last`, `tests/test_transitions.py:108`): `Cancel` на
> корневом диалоге закрывает клавиатуру (`reply_markup` пропадает), новых сообщений нет.
> `done()` на корне безопасен.

---

## 4. `LaunchMode` — поведение диалога при запуске

`src/aiogram_dialog/api/entities/launch_mode.py:4`. Задаётся в `Dialog(launch_mode=...)`
(`dialog.py:43`), default `STANDARD`. Логика — `_process_launch_mode` (`manager.py:315`),
плюс проверка EXCLUSIVE в `_start_normal` (`manager.py:292`).

| Значение | Поведение при старте этого диалога | Можно ли стартовать поверх него | Пример |
|---|---|---|---|
| `STANDARD` (default) | Без ограничений — кладётся поверх стека. | Да | обычный |
| `ROOT` | При старте **сбрасывает стек** (`reset_stack(remove_keyboard=False)`), становится корнем. | Да | главное меню |
| `EXCLUSIVE` | При старте **сбрасывает стек** (становится единственным). | **Нет** — старт поверх → `ValueError` (`manager.py:292-296`). | баннеры |
| `SINGLE_TOP` | Если **тот же диалог уже на вершине** — старая копия снимается (`pop` + удаление context) и заменяется новой, без накопления. | Да | страница товара |

Детали реализации `_process_launch_mode` (`manager.py:315-325`):
- `new_dialog.launch_mode in (EXCLUSIVE, ROOT)` → `reset_stack(remove_keyboard=False)`.
- `SINGLE_TOP` **и** `new_dialog is old_dialog` (один и тот же объект `Dialog` на вершине) →
  снять текущий context (`pop` + `remove_context`), `CONTEXT_KEY = None`. Затем обычный push
  положит свежую копию. Сравнение **по identity объекта Dialog**, не по группе.

Рабочий пример — `example/launch_modes.py`: `banner` (EXCLUSIVE), `main_menu` (ROOT),
`product` (SINGLE_TOP, переоткрытие самого себя просто заменяет верхушку).

> Подводный камень: `EXCLUSIVE` и `ROOT` сбрасывают стек **молча, без `on_close`** — данные
> нижележащих диалогов теряются. Не кладите важный незакрытый прогресс под кнопку,
> ведущую в ROOT/EXCLUSIVE-диалог.

---

## 5. `ShowMode` — как обновлять сообщение диалога

`src/aiogram_dialog/api/entities/modes.py:4`. Текущий режим — свойство `manager.show_mode`
(`manager.py:93-101`), по умолчанию `ShowMode.AUTO`. Любой метод перехода принимает
`show_mode=` и делает `self.show_mode = show_mode or self.show_mode` — то есть установленный
режим «прилипает» до следующей перерисовки.

| Значение | Семантика | Когда |
|---|---|---|
| `AUTO` (default) | Решает `_calc_show_mode` (`manager.py:510`): см. ниже. | По умолчанию почти всегда. |
| `EDIT` | Редактировать текущее сообщение диалога. | Реакция на колбэк (тихое обновление). |
| `SEND` | Отправить новое сообщение. | После ввода текста пользователем — чтобы UI всплыл вниз. |
| `DELETE_AND_SEND` | Удалить старое сообщение диалога и отправить новое. | Когда нужно «всплыть» с медиа/после reply-клавиатуры. **Telegram не даёт удалять сообщения старше ~48 ч** (`modes.py:23`). |
| `NO_UPDATE` | Вообще не рендерить и не обновлять. | Side-эффекты без изменения экрана (например, ответ отдельным сообщением). `show()` сразу выходит (`manager.py:385-387`). |

### Логика `AUTO` (`_calc_show_mode`, `manager.py:510-527`)
По порядку:
1. Если `show_mode` уже не AUTO — вернуть его.
2. Чат **не приватный** → `EDIT`.
3. Последнее сообщение было с reply-клавиатурой → `DELETE_AND_SEND`.
4. Стек **не дефолтный** → `EDIT`.
5. Событие — `Message`: нет media_group → `SEND`; media_group тот же, что прошлый входящий →
   `EDIT`; иначе `SEND`.
6. Иначе (колбэк) → `EDIT`.

Практический итог: на **сообщение** пользователя бот по умолчанию шлёт новое сообщение
(`SEND`), на **нажатие кнопки** — редактирует (`EDIT`). Это и есть смысл `AUTO`.

> Подводный камень: установка `show_mode` через `manager.show_mode = ...` или через
> параметр перехода влияет на **ближайший** `show()`. Если хотите разовый `SEND` после ввода —
> передавайте его в `manager.next(show_mode=ShowMode.SEND)` / `update(show_mode=...)`, а не
> полагайтесь на глобальное состояние.

---

## 6. `manager.update(data=None, show_mode=None)`

`src/aiogram_dialog/manager/manager.py:529`
```python
async def update(self, data: dict | None = None, show_mode=None) -> None:
    if data:
        self.current_context().dialog_data.update(data)
    await self.show(show_mode)
```
- Мерджит `data` в `dialog_data` текущего context и **принудительно перерисовывает** окно
  (`show`). Удобно из внешних/фоновых обработчиков, чтобы и записать данные, и обновить экран.
- Отличие от `switch_to`: не меняет state, только данные + рендер.
- В `SubManager` (внутри `ListGroup` и т.п.) переопределён так, что пишет в `dialog_data`
  родителя, но `show()` делегирует менеджеру (`sub_manager.py:142-149`).

---

## 7. Вложенные диалоги (sub-dialogs)

Вложенность здесь — это **не дерево виджетов**, а стек: «дочерний» диалог просто
запускается поверх «родительского» в том же стеке.

Контракт:
- Запуск: `manager.start(ChildSG.state, data=...)` или виджет `Start(...)`
  (`docs/transitions/start.py`). Дочерний получает `data` как `start_data`, свою пустую
  `dialog_data`, свой `widget_data`. К родительскому context доступа нет.
- Возврат: дочерний делает `manager.done(result=...)`. Родитель ловит результат в
  `on_process_result(start_data, result, manager)` (диалога и/или окна), где `start_data` —
  это `start_data` **дочернего**, `result` — переданное в `done`.
- Полный пример: `example/subdialog.py` — `name_dialog` собирает имя и `done({"name": ...})`,
  `main_menu` принимает его в `process_result` и пишет в свой `dialog_data`.

### Цепочка вложенных стартов через `on_start` / автозакрытие через `on_process_result`
`tests/test_nested_transitions.py` показывает нетривиальный паттерн:
- `MainSG.on_start` → `manager.start(SecondarySG)`; `SecondarySG.on_start` →
  `manager.start(ThirdSG)`. То есть `/start` (RESET_STACK на Main) разворачивает стек
  `Main → Secondary → Third`, и пользователь сразу видит `Third` (тест ждёт `"Third"`).
  Работает потому, что `_start_normal` не делает `show()`, если внутри `on_start` контекст
  снова сменился (`manager.py:311-313`).
- `SecondarySG.on_process_result` → `manager.done()`: когда `Third` закрывается (`Cancel`),
  результат прилетает в `Secondary`, тот немедленно закрывается сам, и управление падает в
  `Main` (тест ждёт `"First"`). Это способ сделать «прозрачный» промежуточный диалог.

> Краевой случай: рекурсивный `start` в `on_start` без условия выхода = бесконечная
> цепочка/переполнение стека (лимит 100 → `DialogStackOverflow`).

---

## 8. Background-менеджер, `SubManager` и доставка переходов

- `manager.start/done/switch_to/update` существуют в **трёх** реализациях:
  - `ManagerImpl` (`manager/manager.py`) — основной, синхронный, прямой доступ к стеку.
  - `BgManager` (`manager/bg_manager.py:73`) — для фоновых задач: не меняет стек напрямую,
    а **шлёт `DialogUpdateEvent`** (`DialogAction.START/DONE/SWITCH/UPDATE`) через `Updater`,
    который роутер обрабатывает в `handle_update` (`manager/update_handler.py:16`). Там
    события снова превращаются в вызовы `dialog_manager.start/switch_to/done/show`.
    Получается через `manager.bg(...)` или `BgManagerFactory.bg(bot, user_id, chat_id, ...)`.
  - `SubManager` (`manager/sub_manager.py:26`) — прокси для виджетов в `ListGroup`; почти всё
    делегирует родителю, но изолирует `widget_data` по `widget_id`/`item_id`.
- `NEW_STACK` использует именно `BgManager` (`_start_new_stack`, `manager.py:272-282`).
- `IncorrectBackgroundError` (`manager.py:122-128`): если обратиться к «живому» менеджеру из
  фоновой корутины после завершения обработки апдейта — нужно брать `manager.bg()`.
- `DialogAction.DONE` через bg вызывает `done(result=event.data)` (`update_handler.py:42-43`).

---

## 9. `render_transitions` — граф переходов

`src/aiogram_dialog/tools/transitions.py:94`
```python
def render_transitions(router: Router, title="Aiogram Dialog",
                       filename="aiogram_dialog", format="png")
```
- Собирает все диалоги (`collect_dialogs(router)`), строит ориентированный граф состояний и
  сохраняет картинку (`Diagram(..., outformat=format, show=False)`).
- Цвета рёбер (`widget_edges`, `transitions.py:24`): `Start` — зелёный; `SwitchTo`/`Next` —
  синий; `Back` — серый; `Cancel` — серый пунктир (рисуется ко всем окнам, откуда в эту
  группу был `Start`). Обходит вложенные `Group`/`Row` рекурсивно (`walk_keyboard`,
  `transitions.py:46`).
- Учитывает подсказки `Window(preview_add_transitions=[...])` — добавляет рёбра, которых нет
  в реальной клавиатуре (для `MessageInput`/динамики), см. `render_window` (`transitions.py:70`)
  и `example/launch_modes.py` / `example/subdialog.py` (`preview_add_transitions=[Next()]`).
- **Зависит от внешнего пакета `diagrams`** (импорт на уровне модуля,
  `transitions.py:6-7`) и от Graphviz в системе. Если `diagrams`/Graphviz не установлены —
  `import aiogram_dialog.tools.transitions` упадёт. Поэтому в проде вызывать только как
  dev-скрипт, не на старте бота (см. `example/launch_modes.py:158` — вызов до `start_polling`).
- Иконка узла — `tools/calculator.png` (`transitions.py:21`), label = имя state.

---

## 10. Сводка сигнатур (`DialogManager`)

| Метод | Файл:строка | Назначение |
|---|---|---|
| `start(state, data=None, mode=NORMAL, show_mode=None, access_settings=None)` | `manager.py:241` | Запуск диалога (push/reset/new stack). |
| `done(result=None, show_mode=None)` | `manager.py:196` | Закрыть верхний диалог, вернуть `result` родителю. |
| `switch_to(state, show_mode=None)` | `manager.py:355` | Сменить окно внутри той же группы. |
| `next(show_mode=None)` / `back(show_mode=None)` | `manager.py:327` / `:341` | Соседнее окно по порядку; крайние → `ValueError`. |
| `update(data=None, show_mode=None)` | `manager.py:529` | Мердж в `dialog_data` + перерисовка. |
| `show(show_mode=None)` | `manager.py:380` | Перерисовать текущее окно. |
| `reset_stack(remove_keyboard=True)` | `manager.py:261` | Очистить стек без колбэков. |
| `mark_closed()` | `manager.py:229` | Низкоуровневый pop из стека (используется в `done`). |
| `bg(user_id, chat_id, stack_id, thread_id, business_connection_id, load)` | `manager.py:564` | Фоновый менеджер для другого чата/стека. |

---

## 11. Связи с остальной библиотекой
- **Виджеты-кнопки** (`widgets/kbd/state.py`) — тонкие обёртки над методами менеджера; см. зону виджетов.
- **Окно/диалог** (`window.py`, `dialog.py`) — `process_start`/`process_result`/`process_close`
  связывают переходы с колбэками `on_start`/`on_process_result`/`on_close`.
- **Storage** (`context/storage.py`) — `save_context`/`load_context`/`remove_context`/`save_stack`
  вызываются из `start`/`done`/`reset_stack`; `start_data`/`result` обязаны быть сериализуемыми.
- **Setup** (`setup.py`, `collect_dialogs`) — нужен для `render_transitions` и регистрации.
- **AccessSettings** (`api/entities/access.py`) — параметр `start(access_settings=...)`,
  наследуется по стеку; см. зону доступов.
- **test_tools** (`BotClient`, `MockMessageManager`) — как тестировать переходы (см. тесты §0).

---

## 12. Чек-лист подводных камней для продакшн-шаблона
1. **`/start` → всегда `StartMode.RESET_STACK`** (или `ROOT`-диалог). Иначе стек растёт до
   лимита 100 → `DialogStackOverflow`. См. все примеры (`example/*`, `tests/*`).
2. **`switch_to` только внутри своей `StatesGroup`**, между диалогами — только `start`/`done`.
3. **`next`/`back` не цикличны** — на краях `ValueError`. Для динамических визардов
   проверяйте границы или используйте `switch_to`.
4. **`done` на корне безопасен** (закрывает клавиатуру), но `on_process_result` не зовётся —
   некому. Не вешайте критичную логику возврата на корневой `done`.
5. **`start_data`/`result`/`dialog_data` должны быть JSON-сериализуемыми** (FSM storage).
6. **`NEW_STACK`/неосновной стек**: запрещён `ReplyKeyboardMarkup`, текстовый ввод ограничен,
   рендер по умолчанию `EDIT`.
7. **`EXCLUSIVE`/`ROOT` сбрасывают стек молча, без `on_close`** — теряются данные нижних
   диалогов; поверх `EXCLUSIVE` старт запрещён (`ValueError`).
8. **`render_transitions` тянет `diagrams` + Graphviz** — только dev-скрипт, не в рантайме бота.
