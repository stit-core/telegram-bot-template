---
name: scaffold
description: Добавить строительный блок в существующего бота по конвенциям шаблона. Варианты — feature (новый вертикальный срез features/<name>/ с гексагоном, Provider, StatesGroup, регистрацией в app.py), dialog (новый Dialog/набор Window внутри фичи), window (окно в существующий диалог), backend-port (pkg-клиент + порт фичи в ports.py), middleware (outer/inner-middleware — через PR в tgbotkit), job (периодическая джоба timerkit), notification (NATS-подписчик + доставка через BgManager). Активируй когда юзер говорит "добавь фичу/диалог/окно/порт/джобу/уведомление", "новая команда/кнопка/экран", "scaffold a feature", "после события X слать сообщение", "фиче A нужны данные из B/бэкенда". Для правки существующего блока scaffold НЕ нужен — это прямая правка.
---

# Skill: scaffold (роутер)

Добавляет новый строительный блок в **существующего** бота по конвенциям шаблона. Скилл — **роутер**: общий ритм держится здесь, специфика каждого варианта — в `references/<variant>.md`. Открой нужный reference и веди по нему, не пересказывая его сюда.

## Выбор варианта

| Что добавляешь | Вариант | Reference | Сигналы |
|---|---|---|---|
| Новый вертикальный срез фичи (гексагон, Provider, StatesGroup, регистрация) | `feature` | `references/feature.md` | «добавь фичу `referral`», «новый раздел бота» |
| Новый `Dialog`/набор `Window` внутри существующей фичи | `dialog` | `references/dialog.md` | «добавь второй диалог в profile», «отдельный флоу настроек» |
| Окно в существующий диалог (state + getter + handler) | `window` | `references/window.md` | «добавь экран подтверждения», «ещё один шаг в визард» |
| pkg-клиент (метод/модуль в `pkg/http_client/`) + порт фичи | `backend-port` | `references/backend-port.md` | «фиче нужны данные с бэкенда», «подключи CRM/LLM-API», «фиче A нужны данные из B» |
| Outer/inner-middleware (throttle/auth/i18n) | `middleware` | `references/middleware.md` | «добавь rate-limit», «глобальную проверку бана» |
| Периодическая джоба (`timerkit`) | `job` | `references/job.md` | «каждые N минут чистить», «напоминание по расписанию» |
| NATS-подписчик → сообщение/диалог (`BgManager`) | `notification` | `references/notification.md` | «после события бэкенда X слать сообщение», «push при оплате» |

Несколько вариантов в одной задаче (новая фича с уведомлением) — веди по основному (`feature`), затем подключи нужные шаги из соседнего reference (`notification`).

## Когда НЕ применять

- **Правка существующего** блока (переписать getter, поменять текст окна) — точечная правка без scaffold.
- **Проектирование нового флоу с нуля** (окна/переходы ещё не зафиксированы) — сначала `/dialog-deep-dive`, scaffold — по его артефакту (в т.ч. когда дизайн приходит из стратегии-репо `<org>/strategy`, слой `telegram-bot-flow/<surface>/` — deep-dive транслирует его в карту флоу).
- **Эволюция `StatesGroup`** (удаление/переименование живого State) — это `state-migration`, не scaffold.
- **Новая инфра-механика** (свой runner, новая точка расширения kit'а) — это **PR в `tgbotkit`** через `infra-handoff`, а не код в шаблоне (rule `tgbotkit-boundary`). `middleware` и часть `notification`/`job` затрагивают эту границу — reference об этом предупреждает.
- **Онбординг форка** — это `init-service` → `de-template`.

## Общий ритм (применим ко всем вариантам)

Reference даёт variant-специфичные шаги; этот ритм обрамляет любой из них:

1. **Подтвердить вход.** Уточни недостающее одним блоком до начала (что именно, имя/состояния, endpoint бэкенда, тексты/ключи i18n) — детали в reference.
2. **Сделать изменение** по шагам reference (scaffold-файлы / правка слоёв / регистрация в точках расширения).
3. **RED→GREEN.** Где появляется логика — сначала тест (red по нужной причине), потом код до green. unit для policy/views, flow (`BotClient`+`MockMessageManager`+`JsonMemoryStorage`) для сценария окна. Мокай **порт**, не транспорт.
4. **Startup-smoke.** Тронул `StatesGroup`/`Dialog`/`Window` → `uv run pytest -k collision` (контейнер собирается, `setup_dialogs` без коллизий).
5. **Верифицируй перед claim «готово»:** `make check` (ruff + import-linter + mypy + pytest). Точечно — `uv run pytest tests/...` / `make lint` по ходу.
6. **Conventional Commit:** `feat(<scope>): <subject>` (точный scope — имя фичи). Тронул инфра-поверхность (env/секрет/NATS-subject/runtime-dep) или нужна инфра-механика → `infra-handoff` до коммита.

## Регистрация в точки расширения tgbotkit

Главное отличие от go-scaffold: бот **ничего не проводит в рантайм руками** — он **декларирует** блоки в точки расширения. Composition root один — `src/bot/app.py`: класс `ExtensionProvider` (точки расширения) + `build_container()` (провайдеры):

| Блок | Куда регистрируется |
|---|---|
| `Dialog` (фича/новый диалог) | `RouterBundle` (метод `routers` в `ExtensionProvider`, `app.py`) |
| dispatcher-level хендлер (команда, pre_checkout, successful_payment) | `CommandBundle` через `CommandSpec(observer, handler, filters)` (метод `commands`) |
| NATS-подписчик | `NotifierBundle` через `NotificationRouter.on(...)` (метод `notifiers`) |
| dishka Provider фичи | `build_container()` в `app.py` (`make_async_container(...)`) |
| pkg-клиент нового API | `@provide` в `pkg/http_client/provider.py` (+ имя в `BackendsConfig`, `config.py`) |
| `StatesGroup` | `src/bot/platform/dialogs/states.py` (единый каталог) |
| ErrorUX / resolver локали / stream-bus | соответствующие методы `ExtensionProvider` |

Фасад фичи `__init__.py` экспортит ровно `Provider` + `dialog` (+ `cmd_spec`/`command_specs`) — это всё, что видит `app.py`.

## Anti-patterns (общие; variant-специфичные — в reference)

- ❌ I/O в getter/handler / прямой `httpx`/`redis` мимо usecase→порта (HTTP — только pkg-клиенты).
- ❌ `policy` в getter/handler — доменные решения приходят результатом usecase (import-linter).
- ❌ Прямой импорт другой фичи — только порт + адаптер (`backend-port`, через `adapters.py`/`provider.py`).
- ❌ `State()` по месту в окне — только из `platform/dialogs/states.py`.
- ❌ `print`/stdlib `logging` — только `pylibinfra.logkit.Logger` (забанено ruff T20 + banned-api).
- ❌ Новый middleware/runner в шаблоне — это PR в `tgbotkit`.
- ❌ Не-JSON в `dialog_data`/`widget_data`/`start_data` (`datetime`/`Decimal`/ORM) — упадёт в Redis.
- ❌ Claim «готово» без `make check` + startup-smoke.
- ❌ Scaffold ради правки существующего блока — это прямая правка.

## См. также

- `references/{feature,dialog,window,backend-port,middleware,job,notification}.md` — процедуры вариантов.
- Правила (автогрузятся на matching-файлах): `feature-architecture`, `dialog-architecture`, `storage-serialization`, `state-lifecycle`, `background-updates`, `tests-pipeline`, `tgbotkit-boundary`.
- `docs/reference/architecture.md § Слои фичи` + эталоны `features/profile/`/`booking/` — полная раскладка гексагона; `docs/reference/dialog-mapping.md` — флоу → файлы.
