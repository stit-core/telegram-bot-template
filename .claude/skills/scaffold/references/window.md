# scaffold › window — окно в существующий диалог

Добавляет одно `Window` (state + getter + handler) в **уже существующий** `Dialog`. Самый частый scaffold: ещё один шаг визарда, экран подтверждения, экран ошибки/деталей. Аналог «endpoint в существующий домен» у go-template. Соответствует rule `dialog-architecture`.

## Когда применять

- «Добавь экран подтверждения перед сохранением».
- «Ещё один шаг ввода в мастер регистрации».
- «Окно с деталями по клику».

## Когда НЕ применять

- Новый самостоятельный флоу/`StatesGroup` → `references/dialog.md`.
- Нужны новые данные с бэкенда → сначала `references/backend-port.md`, потом окно.

## 1. Подтвердить вход

- В какой `Dialog`/фичу? Имя нового `State`?
- Что окно показывает (какие данные getter) и что делает (какие реакции handler)?
- Откуда на него переходят и куда оно ведёт дальше (`SwitchTo`/`Next`/`Back`/`Cancel`/`Start`)?
- Нужен ли ввод (`TextInput`/`MessageInput`) — тогда `on_success`/`on_error`.

## 2. Новый State — в центральный каталог

Добавь `State()` в **существующую** `StatesGroup` фичи (это окно того же флоу — то же группа), `src/bot/platform/dialogs/states.py`:

```python
class Profile(StatesGroup):
    VIEW = State()
    EDIT_NAME = State()
    CONFIRM = State()        # ← новое окно
```

⚠️ Один `State` = одно окно. Не переиспользуй существующий `State` для второго окна (дубль `state=` → `setup_dialogs` упадёт).

## 3. getter (если окно показывает данные)

Окно с динамикой требует getter. Дёргает **usecase** (не порт/pkg-клиент), `**kwargs` обязателен, дефолты всех ключей `Format`:

```python
# getters.py (дополнение)
@inject
async def confirm_getter(
    uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity], **kwargs: Any
) -> dict[str, Any]:
    # данные для подтверждения; ошибку ловим тут, окно не падает
    return {"summary": "...", "status": ""}
```

Чисто статическое окно (только текст+кнопки) getter не требует.

## 4. handler (если окно реагирует)

Реакции/навигация. Данные — из аргументов виджета (`value` у `TextInput`), не из getter. Навигация — `manager.switch_to`/`next`/`back`/`done`:

```python
# handlers.py (дополнение)
@inject
async def on_confirm(
    callback: CallbackQuery, button: Button, manager: DialogManager,
    *, uc: FromDishka[ProfileUsecase], identity: FromDishka[BotIdentity],
) -> None:
    try:
        await uc.commit(identity)          # мутация
    except errors.ProfileError as exc:
        await callback.answer(views.error_text(exc), show_alert=True)
        return
    await manager.switch_to(ProfileSG.VIEW)   # успех → назад
```

dialog-level хендлер → `@inject` из `dishka.integrations.aiogram_dialog`. `DialogManager` в dialog-level приходит аргументом виджета (не `FromDishka`).

## 5. Само окно + связать переходы

```python
# dialogs.py (дополнение)
from aiogram_dialog.widgets.kbd import Button, Row, Back
from aiogram_dialog.widgets.text import Const
from bot.features.profile import getters, handlers

confirm_window = Window(
    Const("Сохранить изменения?"),
    Row(
        Button(I18NFormat("common-confirm"), id="confirm", on_click=handlers.on_confirm),
        Back(I18NFormat("common-back")),
    ),
    state=ProfileSG.CONFIRM,
    getter=getters.confirm_getter,
)

# окно добавляется в СУЩЕСТВУЮЩИЙ Dialog (порядок окон не важен для роутинга — важен state=):
profile_dialog = Dialog(view_window, edit_name_window, confirm_window)
```

Привяжи переход из окна, откуда приходят: добавь `SwitchTo(Const("..."), id="to_confirm", state=ProfileSG.CONFIRM)` в кнопки исходного окна. `id` виджета — ASCII, короткий, **уникален в пределах окна** (callback_data строится из него).

## 6. Тесты + верификация

- flow-тест: дойти до нового окна (через переход), проверить текст/кнопки; для окна-реакции — проверить навигацию после клика.
- кнопки локай по `callback_data`/тексту.
- `uv run pytest -k "collision" -q` — startup-smoke (новый State не дублирует существующий).
- `make check`.

`feat(profile): add confirm window`

## Anti-patterns

- ❌ Переиспользовать существующий `State` для нового окна (дубль `state=`).
- ❌ `State()` по месту в `dialogs.py` вместо `platform/dialogs/states.py`.
- ❌ getter ходит в порт/pkg-клиент/httpx — дёргай usecase.
- ❌ `Format("{x}")` без ключа `x` в getter — `KeyError` уронит рендер.
- ❌ Несколько `media`/`markup`/`input` в одном окне (aiogram_dialog допускает по одному каждого типа).
- ❌ Не привязать переход к новому окну — оно будет недостижимо (проверь графом, `preview-flow`).
