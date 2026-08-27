# Флоу диалога → файлы фичи

Маппинг элементов флоу диалога (окно / переход / getter-данные / состояние / реакция) на файлы и
конструкции в `src/bot/features/<feature>/`. Сомнение «куда это положить в коде» — смотри сюда.
Аналог `domain-mapping.md` у go-эталона; потребляет `scaffold` (вариант `dialog`/`window`).

Флоу проектируется как source-of-truth **до** кода (`/dialog-deep-dive`): окна, переходы, данные,
состояние, реакции. Источник дизайна — либо интервью (`AskUserQuestion`), либо **стратегия-репо**
(см. ниже). Эталон раскладки — `features/profile/` (просмотр + редактирование профиля).

## Вход из стратегии (`<org>/strategy`)

Если рядом sibling-checkout'ом лежит стратегия-репо (форк `business-strategy-template`) со слоем
`docs/projects/<project-slug>/telegram-bot-flow/<surface>/` — дизайн уже спроектирован аналитиком
(5 kind, брать `status: stable`). Слой **features-ориентирован**: диалог, его окна и его use-case'ы
бота собраны в фичу `features/<feature>/{dialog.md, window.md, use-case.md}` (одна фича = один диалог);
команды и уведомления — сквозными реестрами `command.md`/`notification.md` на корне поверхности.
`/dialog-deep-dive` транслирует слой в карту флоу, `/scaffold` разворачивает в код:

| Артефакт стратегии (поля) | → код бота |
|---|---|
| `features/<feature>/dialog.md` (`states-group`, `windows`, `launch-mode`, `started-by`, `dialog-data`) | `StatesGroup` (имя = `states-group`); порядок `State` = порядок `windows`; `LaunchMode` (`root`→`ROOT`); точки входа; pydantic-модель `state.py` (`dialog_data`) |
| `features/<feature>/window.md` (H2-секция на окно: `state`, `message`, `widgets`, `getter`, `errors`) | `Window` (`state`); текст → `Format`/`I18NFormat` + `.ftl`; виджеты (`button`/`url`/`select`/`multiselect`/`text-input`/`calendar`) → `kbd`/`TextInput`/`Calendar`; getter-ключи (source + fallback); `errors` → `ErrorUX`/getter-дефолты |
| `features/<feature>/use-case.md` (H2-секция на UC: `operation`, Actor/Inputs/Outputs/Dependencies/Steps/Errors) | метод-оркестратор `usecase.py` фичи (имя ← `operation`); `Inputs` → аргументы handler'а/getter'а; `Dependencies` `use-case:<ctx>.<Operation>` → метод порта (`ports.py`) → pkg-клиент; `Dependencies` `dialog-data` → чтение/запись state; `Outputs`/`Errors` → sentinel-исходы, по которым handler/getter маршрутизируют (`when`) |
| `command.md` (`command`, `starts`, `stack`, `payload`) | `CommandSpec` (`CommandBundle`); `stack: reset` → `RESET_STACK`; `payload` → `start_data` |
| `notification.md` (`trigger`, `to`, `content`, `idempotency`) | NATS-подписчик (`NotifierBundle`/`BgManager`); `trigger: event:…` → subject; идемпотентность |

`widget.action`/`getter.source` = `use-case:<uc-slug>` — **use-case бота** этой фичи (реф **без точки**)
→ метод `usecase` фичи (оркестратор). Сам bot UC в `Dependencies` ссылается на **доменный** use-case
`use-case:<ctx>.<Operation>` (**с точкой**, имена — из `domains/<ctx>/use-cases/` той же стратегии) →
метод порта фичи (`ports.py`) → pkg-клиент. Точка различает уровни: без точки — оркестратор бота
(`usecase`), с точкой — домен на бэкенде (порт). `notification.trigger` = `event:<ctx>.<Event>` →
subject подписчика. `states-group`/`state`/`operation`/`id` виджета — структурные идентификаторы, **не
переименовываются** (их читает код). Контракт read-only — `ecosystem.md § Хендофф из стратегии`.

## Bounded context

Один сценарий ↔ одна фича `features/<name>/` ↔ одна `StatesGroup` (`platform/dialogs/states.py`) ↔
один `Dialog` (`<name>/dialogs.py`). `Dialog` — это `Router`; регистрируется в `RouterBundle`
(метод `routers` `ExtensionProvider`, `app.py`). Фасад `__init__.py` экспортит `Provider` + `dialog`.

## Окно (Window)

| Элемент флоу | Код |
|---|---|
| Окно сценария | `Window(...)` в `dialogs.py`, `state=<SG>.<STATE>` |
| Состояние окна | `State()` в `StatesGroup` (`platform/dialogs/states.py`) |
| Статический текст/подпись | `I18NFormat("<key>")` — перевод из `locales/<lang>/<feature>.ftl` |
| Динамический текст | `Format("{name}")` — поле из getter-dict |
| Кнопки/раскладка | виджеты `kbd` (`Row`/`Column`/`SwitchTo`/`Cancel`/`Back`/`Button`/`Start`) |
| Ввод значения | `TextInput(id=…, type_factory=…, on_success=…, on_error=…)` |
| Данные окна | `getter=getters.<name>_getter` |

Правила окна (rule `dialog-architecture`): `id` виджетов — ASCII, короткие, уникальные; один
media/markup/input на окно; корневой диалог — `LaunchMode.ROOT`.

## Переход (transition)

| Тип | Код | Где |
|---|---|---|
| В другое окно ЭТОГО диалога | `SwitchTo(text, id=…, state=<SG>.<OTHER>)` | `dialogs.py` |
| Назад по стеку окна | `Back(text)` | `dialogs.py` |
| Закрыть диалог (к вызвавшему) | `Cancel(text)` / `manager.done()` | `dialogs.py` / `handlers.py` |
| Запустить другой диалог | `Start(text, id=…, state=<OtherSG>.<STATE>)` | `dialogs.py` |
| Программная навигация после действия | `manager.switch_to(<SG>.<STATE>)` / `manager.start(…, mode=…)` | `handlers.py` |
| Вход из команды | `dialog_manager.start(<SG>.<STATE>, mode=StartMode.…)` | dispatcher-level handler |

`/start` — всегда `StartMode.RESET_STACK` (иначе стек копится → `DialogStackOverflow`). Между
диалогами — только `Start`/`done`; `SwitchTo` на окно чужого диалога нельзя. Условный переход
(`when` в артефакте) — маршрутизация **исхода usecase**, не правило окна: handler смотрит результат
usecase и зовёт нужный `switch_to`.

## Getter-данные (что показать)

| Элемент флоу | Код |
|---|---|
| Ключи, нужные окну | ключи `dict[str, Any]` из `getter` |
| Источник | `getter` дёргает `usecase` (read), **не** pkg-клиент/httpx напрямую |
| Инъекция | `@inject` из `dishka.integrations.aiogram_dialog` + `FromDishka[...]` |
| Обязательный хвост | `**kwargs: Any` (getter зовут со всем middleware_data) |
| Дефолты | для **всех** ключей `Format` — иначе KeyError при рендере |
| Мягкая ошибка | доменную ошибку ловим в getter, кладём текст в поле (`status`) — окно не падает в recovery |

В терминах стратегии: каждый `getter.<key>` артефакта = ключ возвращаемого dict; `fallback` =
дефолт ключа; `source: use-case:…` = вызов usecase.

## Состояние / данные диалога

| Элемент флоу | Код |
|---|---|
| FSM-состояния | `StatesGroup` в `platform/dialogs/states.py` (единый каталог) |
| Рабочие данные (черновик) | pydantic-`BaseModel` в `state.py` → `manager.dialog_data` |
| Сериализация | только JSON-примитивы (нет `datetime`-объектов/`Decimal`/ORM) — иначе падёт в Redis |
| Доменная сущность | **не** в state — она за портом (грузится getter'ом каждый рендер) |

## Реакция (handler)

| Элемент флоу | Код |
|---|---|
| Клик по кнопке | `on_click=handlers.on_…`, `@inject` |
| Успешный ввод | `TextInput(on_success=handlers.on_…)` — получает `value` |
| Ошибка ввода (`type_factory`) | `TextInput(on_error=handlers.on_…)` |
| Мутация | handler дёргает `usecase` (не policy/pkg напрямую); данные из аргумента виджета, не из getter |
| Ошибка usecase | ловим, текст через `views.error_text`, показываем без падения окна |
| Навигация после реакции | `manager.switch_to` / `manager.done` / `manager.start` |
| Вход по команде | dispatcher-level handler, `@inject` из `dishka.integrations.aiogram`; `dialog_manager` — kwarg |

## Данные с бэкенда (порт → pkg-клиент)

| Элемент флоу | Код |
|---|---|
| Чтение/мутация на бэкенде | метод usecase → порт (`ports.py`, Protocol) |
| Реализация порта | pkg-клиент `pkg/http_client/internal/<api>.py` (структурно удовлетворяет порт) |
| Связка порт→клиент | `provider.py` (`@provide`, Scope.REQUEST) |
| Кросс-фича | порт в потребителе + `adapters.py` (единственное место импорта чужой фичи) |
| Маппинг kit-ошибки → sentinel | в `usecase` (anti-corruption), не в presentation |

## Конкретный пример: `profile`

Флоу: `/menu → [Профиль] → VIEW (имя/email) → [✏️ Имя] → EDIT_NAME (ввод) → сохранить → назад в VIEW`.

```python
# platform/dialogs/states.py
class Profile(StatesGroup):
    VIEW = State()
    EDIT_NAME = State()


# features/profile/dialogs.py
view_window = Window(
    Format("👤 <b>{name}</b> {badge}\n✉️ {email}\n{status}"),  # динамика ← getter
    Row(
        SwitchTo(I18NFormat("profile-edit-name"), id="edit_name", state=ProfileSG.EDIT_NAME),
        Cancel(I18NFormat("common-back")),
    ),
    state=ProfileSG.VIEW,
    getter=getters.profile_getter,
)
edit_name_window = Window(
    I18NFormat("profile-enter-name"),
    TextInput(
        id="name_input",
        type_factory=str,
        on_success=handlers.on_save_name,
        on_error=handlers.on_name_error,
    ),
    Back(I18NFormat("common-back")),
    state=ProfileSG.EDIT_NAME,
)
profile_dialog = Dialog(view_window, edit_name_window)
```

```python
# features/profile/getters.py — данные окна VIEW (read через usecase)
@inject
async def profile_getter(
    uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity], **kwargs: Any
) -> dict[str, Any]:
    try:
        view = await uc.view(identity)  # usecase, не pkg-клиент
    except errors.ProfileError as exc:
        return {"name": "—", "email": "", "badge": "", "status": views.error_text(exc)}  # мягко
    data = views.to_window(view)
    data["status"] = ""
    return data  # все ключи Format заполнены


# features/profile/handlers.py — реакция в окне EDIT_NAME
@inject
async def on_save_name(
    message: Message,
    widget: ManagedTextInput[str],
    manager: DialogManager,
    value: str,
    *,
    uc: FromDishka[ProfileUsecase],
    identity: FromDishka[BotIdentity],
) -> None:
    try:
        await uc.rename(identity, value)  # мутация ← value виджета
    except errors.ProfileError as exc:
        await message.answer(views.error_text(exc))  # ошибка → текст, окно не падает
        return
    await manager.switch_to(ProfileSG.VIEW)  # успех → назад (перерисует getter)
```

Маппинг по элементам:

| Элемент флоу профиля | Файл / конструкция |
|---|---|
| Окна VIEW / EDIT_NAME | `dialogs.py`: `view_window` / `edit_name_window` |
| Состояния | `platform/dialogs/states.py`: `Profile.VIEW` / `Profile.EDIT_NAME` |
| Переход VIEW→EDIT_NAME | `SwitchTo(..., state=ProfileSG.EDIT_NAME)` |
| Переход EDIT_NAME→VIEW (успех) | `manager.switch_to(ProfileSG.VIEW)` в `on_save_name` |
| Данные имя/email/badge | `getters.profile_getter` → `views.to_window` |
| Ввод нового имени | `TextInput(on_success=on_save_name)` |
| Сохранение (мутация) | `usecase.rename` → порт `BackendGateway` → `ProfileAPI.rename_user` (Idempotency-Key) |
| Валидация имени | `policy.validate_name` (PURE) → `Decision` → `errors.NameRejected` |
| Кросс-фича (onboarded?) | порт `OnboardingReader` + `adapters.py` → `start` usecase |
| Тексты кнопок/подсказок | `locales/<lang>/profile.ftl` |

## Особый случай: dispatcher-level (payments)

`pre_checkout_query` и `successful_payment` приходят **не как dialog-callback**, а как апдейты
диспетчера → регистрируются через `CommandBundle` (`CommandSpec`), а не как окно диалога. Связь
инвойса с платежом — через `invoice_payload` (= order_id), не через dialog-стек. См.
`features/payments/handlers.py`. В терминах стратегии это записи `command.md` и реестр
`notification.md`, не `window`.
