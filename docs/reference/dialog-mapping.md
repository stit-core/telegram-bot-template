# Флоу диалога → файлы фичи

Маппинг элементов флоу диалога (окно / переход / getter-данные / состояние / реакция) на
конкретные файлы и конструкции внутри `src/bot/features/<feature>/`. Если сомнение «куда это
положить в коде» — смотри сюда. Аналог `domain-mapping.md` у go-эталона; потребляет `scaffold`
(вариант `dialog`/`window`).

Флоу диалога проектируется как source-of-truth **до** кода (skill `dialog-deep-dive`): какие окна,
переходы между ними, какие данные нужны в каждом окне, какое состояние, какие реакции. Этот файл —
мост от той формы к коду. Эталон — `features/profile/` (просмотр + редактирование профиля).

## Bounded context

Один сценарий ↔ одна фича `features/<name>/` ↔ одна `StatesGroup` (в `platform/dialogs/states.py`)
↔ один `Dialog` (в `<name>/dialogs.py`). `Dialog` является `Router` — регистрируется в
`RouterBundle` (`extensions.py`).

## Окно (Window)

| Элемент флоу | Код |
|---|---|
| Окно сценария | `Window(...)` в `dialogs.py`, привязано `state=<SG>.<STATE>` |
| Состояние окна | `State()` в `StatesGroup` (`platform/dialogs/states.py`) |
| Статический текст/подпись | `I18NFormat("<key>")` — перевод по ключу из `locales/<lang>/<feature>.ftl` |
| Динамический текст | `Format("{name}")` — поле из getter-dict |
| Кнопки/раскладка | виджеты `kbd` (`Row`/`Column`/`SwitchTo`/`Cancel`/`Back`/`Button`/`Start`) |
| Ввод текста/значения | `TextInput(id=…, type_factory=…, on_success=…, on_error=…)` |
| Данные окна | `getter=getters.<name>_getter` (если окно показывает динамику) |

Правила окна (rule `dialog-architecture`): `id` виджетов — ASCII, короткие, уникальные; один
media/markup/input на окно; корневой диалог — `LaunchMode.ROOT`.

## Переход (transition)

| Тип перехода | Код | Где |
|---|---|---|
| В другое окно ЭТОГО диалога | `SwitchTo(text, id=…, state=<SG>.<OTHER>)` | `dialogs.py` (декларативно) |
| Назад по стеку окна | `Back(text)` | `dialogs.py` |
| Закрыть диалог (к вызвавшему) | `Cancel(text)` / в handler `manager.done()` | `dialogs.py` / `handlers.py` |
| Запустить другой диалог | `Start(text, id=…, state=<OtherSG>.<STATE>)` | `dialogs.py` |
| Программная навигация после действия | `manager.switch_to(<SG>.<STATE>)` / `manager.start(…, mode=…)` | `handlers.py` |
| Вход в диалог из команды | `dialog_manager.start(<SG>.<STATE>, mode=StartMode.…)` | `handlers.py` (dispatcher-level) |

`/start` — всегда `StartMode.RESET_STACK` (иначе стек копится до 100 → `DialogStackOverflow`).

## Getter-данные (что показать)

| Элемент флоу | Код |
|---|---|
| Список данных, нужных окну | ключи возвращаемого `dict[str, Any]` в `getter` |
| Источник данных | `getter` дёргает `usecase` (read), **не** gateway/httpx напрямую |
| Инъекция зависимостей | `@inject` из `dishka.integrations.aiogram_dialog` + `FromDishka[...]` |
| Обязательный хвост сигнатуры | `**kwargs: Any` (getter зовут со всем middleware_data) |
| Дефолты | для **всех** ключей `Format` — иначе KeyError при рендере |
| Мягкая обработка ошибки | doмен-ошибку ловим в getter и кладём текст в поле (`status`), чтобы окно не упало в recovery |

## Состояние / данные диалога

| Элемент флоу | Код |
|---|---|
| FSM-состояния сценария | `StatesGroup` в `platform/dialogs/states.py` (единый каталог) |
| Рабочие данные диалога (черновик ввода) | pydantic-`BaseModel` в `state.py`; кладётся в `manager.dialog_data` |
| Ограничение сериализации | только JSON-примитивы (`datetime`→ISO, нет Decimal/ORM) — иначе падёт в Redis |
| Доменная сущность | **не** в state — она за gateway (грузится getter'ом каждый рендер) |

## Реакция (handler)

| Элемент флоу | Код |
|---|---|
| Клик по кнопке | `on_click=handlers.on_…` (dialog-level), `@inject` из `aiogram_dialog` |
| Успешный ввод | `TextInput(on_success=handlers.on_…)` — получает `value` |
| Ошибка ввода (`type_factory` кинул) | `TextInput(on_error=handlers.on_…)` |
| Мутация | handler дёргает `usecase` (не policy/gateway напрямую); данные из аргументов виджета, не из getter |
| Ошибка usecase | ловим, текст через `views.error_text`, показываем без падения окна |
| Навигация после реакции | `manager.switch_to` / `manager.done` / `manager.start` |
| Вход по команде | dispatcher-level handler, `@inject` из `dishka.integrations.aiogram`; `dialog_manager` — обычный kwarg |

## Конкретный пример: `profile`

Флоу: `/menu → [Профиль] → VIEW (показать имя/email) → [✏️ Имя] → EDIT_NAME (ввести имя) →
сохранить → назад в VIEW`.

```python
# platform/dialogs/states.py — состояния сценария
class Profile(StatesGroup):
    VIEW = State()        # окно просмотра
    EDIT_NAME = State()   # окно ввода нового имени

# features/profile/dialogs.py — окна + переходы
view_window = Window(
    Format("👤 <b>{name}</b> {badge}\n✉️ {email}\n{status}"),   # динамика ← getter
    Row(
        SwitchTo(I18NFormat("profile-edit-name"), id="edit_name", state=ProfileSG.EDIT_NAME),  # → EDIT_NAME
        Cancel(I18NFormat("common-back")),                       # закрыть диалог
    ),
    state=ProfileSG.VIEW,
    getter=getters.profile_getter,                               # данные окна
)
edit_name_window = Window(
    I18NFormat("profile-enter-name"),
    TextInput(id="name_input", type_factory=str,
              on_success=handlers.on_save_name,                  # реакция на ввод
              on_error=handlers.on_name_error),
    Back(I18NFormat("common-back")),                             # назад в VIEW
    state=ProfileSG.EDIT_NAME,
)
profile_dialog = Dialog(view_window, edit_name_window)
```

```python
# features/profile/getters.py — данные окна VIEW (read через usecase)
@inject
async def profile_getter(uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity],
                         **kwargs: Any) -> dict[str, Any]:
    try:
        view = await uc.view(identity)                  # usecase, не gateway
    except errors.ProfileError as exc:
        return {"name": "—", "email": "", "badge": "", "status": views.error_text(exc)}  # мягко
    data = views.to_window(view)
    data["status"] = ""
    return data                                         # все ключи Format заполнены

# features/profile/handlers.py — реакция в окне EDIT_NAME
@inject
async def on_save_name(message: Message, widget: ManagedTextInput[str], manager: DialogManager,
                       value: str, *, uc: FromDishka[ProfileUsecase],
                       identity: FromDishka[BotIdentity]) -> None:
    try:
        await uc.rename(identity, value)                # мутация ← value виджета, не getter
    except errors.ProfileError as exc:
        await message.answer(views.error_text(exc))     # ошибка → текст, окно не падает
        return
    await manager.switch_to(ProfileSG.VIEW)             # успех → назад (перерисует getter)
```

Маппинг по элементам:

| Элемент флоу профиля | Файл / конструкция |
|---|---|
| Окна VIEW / EDIT_NAME | `dialogs.py`: `view_window` / `edit_name_window` |
| Состояния VIEW / EDIT_NAME | `platform/dialogs/states.py`: `Profile.VIEW` / `Profile.EDIT_NAME` |
| Переход VIEW→EDIT_NAME | `SwitchTo(..., state=ProfileSG.EDIT_NAME)` |
| Переход EDIT_NAME→VIEW (успех) | `manager.switch_to(ProfileSG.VIEW)` в `on_save_name` |
| Данные имя/email/badge | `getters.profile_getter` → `views.to_window` |
| Ввод нового имени | `TextInput(on_success=on_save_name)` |
| Сохранение (мутация) | `usecase.rename` → `gateway.update_name` (`Idempotency-Key`) |
| Валидация имени | `policy.validate_name` (PURE) → `errors.NameRejected` |
| Тексты кнопок/подсказок | `locales/<lang>/profile.ftl` (`profile-edit-name`, `profile-enter-name`) |

## Особый случай: dispatcher-level (payments)

`pre_checkout_query` и сообщение с `successful_payment` приходят **не как dialog-callback**, а как
апдейты диспетчера → регистрируются через `CommandBundle` (`CommandSpec`), а не как окно диалога.
Связь инвойса с платежом — через `invoice_payload` (= order_id), не через dialog-стек. Маппинг:
`on_buy` (dialog `on_click`, шлёт `send_invoice`) → `on_pre_checkout` (dispatcher, `answer_pre_checkout`
timeout-guard ≤10с) → `on_successful_payment` (dispatcher, `guard_charge` дедуп). См.
`features/payments/handlers.py`.
