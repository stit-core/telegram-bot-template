# aiogram_dialog — исчерпывающая документация для построения шаблона ботов

Полный, сверенный с исходным кодом справочник по библиотеке
[**aiogram_dialog**](https://github.com/Tishka17/aiogram_dialog) — собран как фундамент для
продакшн-шаблона телеграм-ботов.

Каждый факт здесь проверен по реальным исходникам (не по памяти и не только по официальной
документации): где возможно, приведены ссылки на файл и строку (`src/aiogram_dialog/.../file.py:LINE`),
рабочие примеры, краевые случаи и найденные в текущем срезе кода неточности.

| | |
|---|---|
| **Источник** | `aiogram_dialog`, ветка `develop`, коммит `08abdf0` (2026-05-02) |
| **Зависимости** | `aiogram>=3.14.0`, `jinja2`, `cachetools` (опц. `diagrams`, `aiohttp` для tools) |
| **Python** | 3.11+ (используются exception notes) |
| **Объём** | 20 reference-глав + 4 сквозных guide; ~53 виджета, ~79 подводных камней |

---

## С чего начать

Порядок чтения зависит от цели:

- **Хочу понять, как библиотека устроена** → [`guides/architecture.md`](guides/architecture.md).
  Связный нарратив: ментальная модель, жизненный цикл апдейта, модель данных, навигация,
  foreground/background, рендеринг.
- **Строю шаблон бота прямо сейчас** → [`guides/building-a-template.md`](guides/building-a-template.md).
  Структура проекта, выбор storage/изоляции, бутстрап, обработка ошибок, DI, i18n, тесты.
- **Нужен конкретный виджет** → [`guides/widgets-quick-reference.md`](guides/widgets-quick-reference.md).
  Шпаргалка: сигнатура в одну строку, назначение, где состояние, главный подводный камень.
- **Готовлюсь к продакшну / отлаживаю странность** →
  [`guides/gotchas-and-production-checklist.md`](guides/gotchas-and-production-checklist.md).
  Все грабли по темам + actionable-чек-лист на 54 пункта.

> Минимум, который определяет весь скелет шаблона: persistent storage (Redis) и только
> JSON-примитивы в данных; `/start` → `StartMode.RESET_STACK`; error-handlers на
> `UnknownIntent`/`UnknownState`; `setup_dialogs(dp)` строго последним; все getter — `**kwargs`
> с дефолтами.

---

## Структура документации

```
aiogram-dialog-docs/
├── README.md                       ← вы здесь (индекс + навигация)
├── guides/                         ← сквозные руководства (синтез поверх reference)
│   ├── architecture.md
│   ├── building-a-template.md
│   ├── widgets-quick-reference.md
│   └── gotchas-and-production-checklist.md
└── reference/                      ← 20 детальных глав по подсистемам
    ├── 01-setup-registration.md ... 20-testing-preview-i18n-faq.md
```

### Guides — сквозные руководства

| Документ | О чём |
|---|---|
| [architecture.md](guides/architecture.md) | Как Dialog/Window/Widget/State/Context/Stack/Manager собираются в систему; жизненный цикл апдейта; модель данных и хранилище; getter-pipeline; навигация и стеки; foreground/background; рендеринг; карта модулей. |
| [building-a-template.md](guides/building-a-template.md) | Практический гайд по сборке продакшн-шаблона: структура, зависимости, storage/изоляция, бутстрап, ошибки состояния, DI, i18n, тестирование, UX-нюансы, чек-лист. |
| [widgets-quick-reference.md](guides/widgets-quick-reference.md) | Компактная шпаргалка по всем ~53 виджетам/фабрикам в 11 категориях + общие правила. |
| [gotchas-and-production-checklist.md](guides/gotchas-and-production-checklist.md) | ~79 подводных камней по 14 темам (суть → чем грозит → как избежать) + продакшн-чек-лист. |

### Reference — детальные главы

**Ядро и архитектура**

| # | Глава | Содержание |
|---|---|---|
| 01 | [setup-registration](reference/01-setup-registration.md) | `setup_dialogs`, `DialogRegistry`, регистрация диалогов, цепочка middleware |
| 02 | [dialog-manager](reference/02-dialog-manager.md) | `DialogManager`: полный интерфейс (`start/done/switch_to/.../find/bg`), `ManagerImpl`/`SubManager` |
| 03 | [window-dialog](reference/03-window-dialog.md) | `Window` и `Dialog`: конструкция, слоты виджетов, lifecycle-хуки, `LaunchMode`, preview |
| 04 | [context-intent-storage-stack](reference/04-context-intent-storage-stack.md) | `Context`, `Stack`, `intent_id`, `StorageProxy`, мультистек, `AccessSettings`, сериализация |
| 05 | [transitions-states](reference/05-transitions-states.md) | Переходы: `StartMode`/`ShowMode`/`LaunchMode`, вложенные диалоги, `render_transitions` |
| 06 | [bgmanager-updates](reference/06-bgmanager-updates.md) | `BgManager`/`BgManagerFactory`, фоновые апдейты, `DIALOG_EVENT_NAME`, `fg()` |
| 07 | [message-manager-media](reference/07-message-manager-media.md) | `MessageManager`: send/edit/delete, `NewMessage`, кеш `file_id` (`MediaIdStorage`) |

**Виджеты**

| # | Глава | Содержание |
|---|---|---|
| 08 | [text-widgets](reference/08-text-widgets.md) | `Const`, `Format`, `Multi`, `Case`, `Jinja`, `List`, `Progress`, `ScrollingText` |
| 09 | [kbd-buttons-groups](reference/09-kbd-buttons-groups.md) | `Button`, `Url`, `WebApp`, `SwitchInlineQuery*`, `CopyText`, `Group`/`Row`/`Column` |
| 10 | [kbd-state-buttons](reference/10-kbd-state-buttons.md) | Навигация: `Start`, `SwitchTo`, `Next`, `Back`, `Cancel` |
| 11 | [kbd-select](reference/11-kbd-select.md) | `Select`, `Radio`, `Multiselect`, `Toggle` + Managed-обёртки |
| 12 | [kbd-checkbox-counter-copy](reference/12-kbd-checkbox-counter-copy.md) | `Checkbox`, `Counter`, `CopyText` |
| 13 | [kbd-calendar-time](reference/13-kbd-calendar-time.md) | `Calendar` (+кастомные view, `CalendarConfig`), `TimeSelect` |
| 14 | [kbd-request](reference/14-kbd-request.md) | `RequestContact`, `RequestLocation`, `RequestPoll` (и почему нет `RequestUser`/`RequestChat`) |
| 15 | [scrolling-listgroup-pager](reference/15-scrolling-listgroup-pager.md) | `ScrollingGroup`, `ListGroup`, `StubScroll`, Pager-виджеты, протокол `Scroll` |
| 16 | [input-widgets](reference/16-input-widgets.md) | `MessageInput`, `TextInput`, `type_factory`, фильтры, комбинированный ввод |
| 17 | [media-linkpreview](reference/17-media-linkpreview.md) | `StaticMedia`, `DynamicMedia`, `MediaScroll`, `LinkPreview`, `MediaAttachment` |
| 18 | [markup-style](reference/18-markup-style.md) | `markup_factory`: inline vs reply, `ReplyKeyboardFactory`, `ForceReply`, стили |

**Машинерия и инструменты**

| # | Глава | Содержание |
|---|---|---|
| 19 | [common-custom-data](reference/19-common-custom-data.md) | `Whenable`/`when`, `Managed`/`find`, getter/data-поток, кастомные виджеты, group/business |
| 20 | [testing-preview-i18n-faq](reference/20-testing-preview-i18n-faq.md) | `BotClient`/`MockMessageManager`, preview, i18n, FAQ, миграции, архитектура `example/mega` |

---

## Ментальная модель за 30 секунд

`aiogram_dialog` — это **слой над aiogram FSM**, который превращает плоское «состояние
пользователя» в **стек открытых экранов с собственными данными**:

- **`Dialog`** (= aiogram `Router`, привязан к одной `StatesGroup`) — контейнер окон.
- **`Window`** (= одно `State`) — один экран: что рендерить (текст/клавиатура/медиа) и как
  реагировать на ввод.
- **`Widget`** — кирпичики окна (`Text`, `Keyboard`, `Input`, `Media`); stateful-виджеты хранят
  состояние в `Context.widget_data`.
- **`Context`** — рантайм одного запуска диалога (`state`, `start_data`, `dialog_data`,
  `widget_data`), живёт от `start` до `done`.
- **`Stack`** — стек открытых диалогов в одном «канале»; одно сообщение Telegram приходится на стек.
- **`DialogManager`** — фасад, через который хендлеры и виджеты всем управляют; живёт один апдейт.

Навигация — две оси: **внутри диалога** (`switch_to`/`next`/`back`, меняют `state`) и **между
диалогами** (`start`/`done`, меняют стек). Подробнее — [architecture.md](guides/architecture.md).

---

## Как собрана эта документация

Исходники библиотеки (`src/`, ~12k строк) и официальная документация (`docs/`, примеры, тесты)
были разбиты на **20 непересекающихся зон**. Каждую зону изучал отдельный агент, сверяя каждое
утверждение с реальным кодом и фиксируя сигнатуры, краевые случаи и подводные камни в
промежуточную заметку (`_notes/`). Поверх 20 заметок синтезированы 4 сквозных руководства
(`guides/`). Поэтому документация описывает **именно тот код, что в коммите `08abdf0`**, включая
расхождения с официальной документацией (например, устаревшие примеры или переименованные API).

При обновлении версии библиотеки сверяйте критичные места (сигнатуры `setup_dialogs`, `Window`,
`DialogManager`, список виджетов) — раздел миграций см.
[reference/20 §8](reference/20-testing-preview-i18n-faq.md).

---

## Ссылки

- Репозиторий: <https://github.com/Tishka17/aiogram_dialog>
- Официальная документация: <https://aiogram-dialog.readthedocs.io/en/stable/>
- PyPI: <https://pypi.org/project/aiogram-dialog>
- Чат: <https://t.me/aiogram_dialog>
