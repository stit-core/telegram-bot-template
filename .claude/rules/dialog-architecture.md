---
name: dialog-architecture
description: Инварианты presentation-слоя aiogram_dialog (Dialog/Window, getter, handler, DI). Terse; «как и почему» — design/ARCHITECTURE.md §7 + aiogram-dialog-docs/. Грузится при правке dialogs.py/getters.py/handlers.py.
paths:
  - "**/dialogs.py"
  - "**/getters.py"
  - "**/handlers.py"
---

# Архитектура диалога (presentation)

Это самый верхний слой фичи (rule `feature-architecture`). `getter` = данные, `handler` =
реакции — они не импортят друг друга. Полный референс виджетов — `aiogram-dialog-docs/`.

## Window / Dialog

- Один `Dialog` ⇄ одна `StatesGroup`; `Dialog` **является** `Router` → отдаётся в `RouterBundle`
  через `__init__.py` (не регистрируется руками — это делает kit).
- `state=` каждого `Window` — из `bot.platform.dialogs.states` (НЕ объявлять `State()` по месту).
- Корневой/«домашний» диалог — `launch_mode=LaunchMode.ROOT` (стек не растёт от повторного входа).
  ROOT в проекте один (сейчас — `start`).
- Переход в другую фичу — по её `State` из `states` (`Start(...)`/`SwitchTo(...)`), **не** импортом
  модуля другой фичи. Общие кнопки — фабрики из `platform/dialogs/common.py` (`open_dialog`/
  `back_to_menu`), не разделяемые синглтоны.
- `id` виджета: ASCII, короткий, **уникален в пределах окна** (callback_data строится из него;
  коллизия → клики уходят не туда). Кнопка — своя на окно (фабрика), не один инстанс на два окна.
- Статические подписи — `I18NFormat("<key>")` (перевод по ключу, префикс = фича); динамика —
  `Format("{key}")` с данными из getter. Все `{...}` в `Format` обязаны иметь значение в getter.

## getter — только данные

- `getter(**kwargs)` async, дёргает **usecase** (не порт/pkg-клиент/httpx) и **не импортит
  `policy`** (контракт import-linter). `**kwargs` ОБЯЗАТЕЛЕН — getter
  зовут со всем `middleware_data`; не перечисляй reserved-ключи руками.
- DI — `@inject` из **`dishka.integrations.aiogram_dialog`** (getter не event-handler диспетчера),
  зависимости через `FromDishka[...]`. Возврат — `dict` со **всеми** ключами, что читает `Format`
  (дефолты для каждого: пустая строка/`—`, иначе `KeyError` уронит рендер).
- Доменную ошибку ловим **в getter** и кладём мягкий `status`/плейсхолдеры — окно не должно падать
  в recovery (`error_text` из `views`).

## handler — реакции и навигация

- `on_click`/`on_success`/`on_error`: дёргают usecase (мутации), данные берут из аргументов виджета
  (`value`), **не** из getter. Навигация — `manager.switch_to`/`next`/`done`/`start`.
- **Handler не принимает доменных решений** и не импортит `policy` (контракт «Handlers/getters
  без policy»). **Все** шаги wizard'а — методы usecase (включая passthrough вроде
  `set_services`); usecase возвращает результат-данные (`set_guests → GuestsStep(draft,
  address_required)`), handler мапит их на экран (`switch_to`) и ошибки на текст
  (`views.error_text`). usecase никогда не трогает `DialogManager`/экраны.
- **Формат-валидация ввода** («это число?») — `type_factory` виджета → `on_error`; доменная
  валидация («не больше N гостей») — policy внутри usecase → доменная ошибка.
- Dialog-level хендлеры — `@inject` из **`dishka.integrations.aiogram_dialog`**.
- Dispatcher-level хендлеры (команды, `pre_checkout`, `successful_payment`) — `@inject` из
  **`dishka.integrations.aiogram`**; отдаются в `CommandBundle` через `CommandSpec`, не в `Dialog`.
- `DialogManager` в dispatcher-level хендлере приходит из `middleware_data` — это **обычный
  kwarg**, НЕ `FromDishka[DialogManager]`.
- `/start` (и любой ре-вход в корень) — `mode=StartMode.RESET_STACK`: иначе стек копится до лимита
  100 → `DialogStackOverflow`.
- Ошибку usecase превращаем в текст (`views.error_text`) и показываем без падения окна; не-наши
  ошибки не глотаем.

## Чек

- В `dialog_data`/`widget_data`/`start_data` — только JSON-примитивы (rule `storage-serialization`).
- Новый/изменённый `State` → rule `state-lifecycle` (deprecation, не удаление живых).
- Кнопки в flow-тестах локаются по `callback_data`/тексту (rule `tests-pipeline`).
- `make check` зелёный (import-linter держит `dialogs → getters|handlers → views → usecase`
  и запрет `handlers`/`getters` → `policy`).
