# scaffold › dialog — новый Dialog внутри существующей фичи

Добавляет **второй (или ещё один) `Dialog`** — отдельный флоу со своей `StatesGroup` — внутри уже существующей фичи, рядом с её основным диалогом. Полезно, когда у фичи несколько слабо связанных сценариев (просмотр vs мастер настройки), которые удобнее держать как разные диалоги, а не как окна одного. Соответствует rule `dialog-architecture`.

> Один `Dialog` ⇄ одна `StatesGroup`. Если новый сценарий — это +1-2 окна того же флоу с теми же данными, тебе нужен `references/window.md`, а не отдельный диалог.

## Когда применять

- «В profile добавь отдельный диалог настроек уведомлений».
- «У фичи нужен мастер из нескольких шагов как самостоятельный флоу».

## Когда НЕ применять

- Окно в уже существующий диалог → `references/window.md`.
- Совсем новый сценарий, не связанный с фичей → `references/feature.md` (новая фича).

## 1. Подтвердить вход

- В какую фичу добавляем? Имя нового диалога/`StatesGroup`?
- Окна и переходы (из `dialog-deep-dive`, если флоу нетривиальный)?
- Как в него входят: кнопка из существующего окна (`Start`), команда (`/foo`), вложенный запуск из handler'а (`manager.start(...)`)?
- Корневой (`LaunchMode.ROOT`) — почти наверняка **нет** (ROOT в проекте один, обычно `start`).

## 2. Новая StatesGroup — в центральный каталог

В `src/bot/platform/dialogs/states.py`:

```python
class ProfileSettings(StatesGroup):   # отдельная группа, не расширение существующей
    MENU = State()
    NOTIFY = State()
```

⚠️ Не добавляй состояния в существующую `StatesGroup` фичи, если это новый **диалог** — два `Dialog` на одну `StatesGroup` валит `setup_dialogs` (startup-smoke поймает).

## 3. Файлы

Новый диалог обычно не требует нового usecase/порта — переиспользует существующие фичи. Минимум:

- расширить `dialogs.py` фичи новым `Dialog` (или завести `dialogs_settings.py`, если файл разрастается);
- добавить getters/handlers для его окон (в существующие `getters.py`/`handlers.py` фичи или отдельные модули — слой тот же);
- если нужен новый usecase-метод — добавь в существующий `usecase.py`; новый порт/HTTP-вызов — `ports.py`+pkg-клиент+`provider.py` (см. `backend-port.md`).

```python
# dialogs.py (дополнение)
from aiogram_dialog import Dialog, Window
from pylibinfra.tgbotkit import I18NFormat
from bot.features.profile import getters
from bot.features.profile.state import ProfileSettingsSG   # re-export в state.py
from bot.platform.dialogs.common import back_to_menu

settings_menu = Window(
    I18NFormat("profile-settings-title"),
    back_to_menu("settings_back"),
    state=ProfileSettingsSG.MENU,
    getter=getters.settings_getter,
)
profile_settings_dialog = Dialog(settings_menu)   # своя StatesGroup
```

В `state.py` добавь re-export: `ProfileSettingsSG = states.ProfileSettings`.

## 4. Точка входа

- **Кнопка из существующего окна фичи** — `Start(I18NFormat("..."), id="to_settings", state=ProfileSettingsSG.MENU)` (фабрика `open_dialog` из `platform/dialogs/common.py`). `Start` запускает вложенный диалог поверх текущего (стек); `back_to_menu`/`Cancel` вернёт назад.
- **Из handler'а** — `await manager.start(ProfileSettingsSG.MENU, mode=StartMode.NORMAL)` (НЕ `RESET_STACK`, если хочешь вернуться назад).
- **Командой** — добавь `CommandSpec("message", on_settings_command, (Command("settings"),))` в фасад фичи и в `command_specs`.

## 5. Регистрация в RouterBundle

Новый `Dialog` — это `Router`, его надо отдать kit'у:

- экспортируй из `__init__.py` фичи: либо отдельным именем (`settings_dialog`), либо включи в кортеж, если фасад уже отдаёт несколько;
- в `src/bot/app.py` (`ExtensionProvider.routers`) добавь `profile.settings_dialog` в `RouterBundle`. **Каждый `Dialog` регистрируется отдельно** — kit не разворачивает вложенность сам.

```python
# app.py (фрагмент ExtensionProvider)
@provide
def routers(self) -> RouterBundle:
    return (start.dialog, profile.dialog, profile.settings_dialog, payments.dialog, lang.dialog)
```

## 6. Тесты + верификация

- flow-тест на вход в новый диалог (кнопка/команда → окно появилось).
- добавь новый `Dialog` в список детача в `tests/flows/test_composition.py` (`for dialog in (...)`).
- `uv run pytest -k "collision" -q` — startup-smoke (две StatesGroup не коллизят).
- `make check`.

`feat(profile): add settings dialog`

## Anti-patterns

- ❌ Два `Dialog` на одну `StatesGroup` — `setup_dialogs` упадёт. Новый диалог = новая группа.
- ❌ `LaunchMode.ROOT` на втором диалоге — ROOT один на проект.
- ❌ Забыть зарегистрировать новый `Dialog` в `RouterBundle` (`ExtensionProvider` в `app.py`) — апдейты его окон не дойдут.
- ❌ `manager.start(..., mode=RESET_STACK)` для вложенного флоу, из которого надо вернуться — сотрёт стек, `Cancel` будет некуда вести.
