---
name: init-service
description: Оркестратор онбординга потребителя шаблона бота — ведёт путь форк → проектирование флоу диалогов (dialog-deep-dive) → проектирование стека (stack-deep-dive) → de-template → scaffold фич в код → удаление reference-фич, пока проект не перестанет помнить про шаблон. Активируй когда юзер форкнул telegram-bot-template и говорит "/init-service", "онбординг", "развернуть свой бот из шаблона", "с чего начать новый бот из шаблона", или когда видишь свежий форк (имя проекта всё ещё telegram-bot-template, reference-фичи start/profile/payments на месте). Сам не проектирует и не де-темплейтит — чейнит специализированные скиллы по порядку.
---

# Skill: init-service (онбординг-оркестратор)

Дирижёр пути «форк шаблона → свой бот». Не делает проектирование/генерацию сам, а **ведёт по этапам и чейнит** специализированные скиллы, держа фокус: дизайн первичен, код вторичен и разворачивается по нему. Один проход доводит до проекта, который ничего не помнит про шаблон.

Полное описание пути для человека — `docs/getting-started.md`; этот скилл его исполняет.

## Когда применять

- "/init-service" / "онбординг" / "развернул форк, что дальше"
- Свежий форк: `[project] name` ещё `telegram-bot-template`, reference-фичи `start`/`profile`/`payments`/`lang`/`notifications` на месте
- Юзер: «хочу развернуть свой бот из шаблона»

## Когда НЕ применять

- Проект уже де-темплейтизирован (своё имя, reference-фичи удалены) — обычный день, иди в `/smartdev`.
- Юзер хочет добавить фичу/диалог в уже-свой бот — это `scaffold`, не онбординг.

## Pre-flight

- [ ] Форк создан, репозиторий склонирован (Gitea → **Use this template** → `<org>/<bot>`).
- [ ] `make setup` прогнан (`uv sync` + git-хуки commit-msg/pre-commit/pre-push).
- [ ] `pylibinfra` доступен (приватный git+ssh резолвится при `uv sync`); если `tgbotkit` ещё не тегнут — ревизия в `[tool.uv.sources]` указывает на коммит с kit'ом (см. `pyproject.toml`).
- [ ] Понятно, что бот делает (1-2 фразы продуктового сценария) — это вход этапа 1.

## Этапы (чейнить по порядку, не делать самому)

### 1. Спроектировать флоу диалогов → `dialog-deep-dive`

Прежде чем разворачивать платформу — зафиксируй **пользовательские сценарии как флоу**: какие диалоги, окна, переходы, какие данные нужны getter'ам, какие состояния виджетов. Это source-of-truth presentation **до** кода.

- **Чейнь в `dialog-deep-dive`** per сценарий: окна → переходы → getter-данные → состояния виджетов → StatesGroup-инвентарь. Артефакты — `docs/stack/dialogs.md` (карта флоу) + рабочая память скилла.
- **Если есть стратегия-репо** (`<org>/strategy`, форк `business-strategy-template`, sibling-checkout'ом рядом) и в нём для bot-поверхности заполнен слой `telegram-bot-flow/<surface>/` — дизайн диалогов уже спроектирован аналитиком (фичи `dialog/window/use-case` + сквозные `command/notification`, брать только `stable`). `dialog-deep-dive` тогда **транслирует** его в карту флоу (read-only, в стратегию не пишем), интервью — только по дырам. Контракт хендоффа — `docs/reference/ecosystem.md`.
- Reference-фичи (`start`/`profile`/...) — учебные образцы раскладки; удаление — этап 5.

### 2. Спроектировать стек → `stack-deep-dive`

- **Чейнь в `stack-deep-dive`**: волнами фундамент→роллап (`service` → киты/storage/backends → `dialogs`/messaging/auth/observability → `config`/`runtime`) до `status: stable` всех артефактов с **непустой `Generates`**. ⚠️ `storage` (Redis, не Memory) и `dialogs` (флоу из этапа 1, error-handlers) — критичные.
- В `service.md § Identity` зафиксируй имя проекта/package path (по ним `de-template` переименует, `scaffold` найдёт фичи).
- Gate: `make validate-stack-docs` зелёный + все артефакты `stable` + state `stack-deep-dive` чист по `**blocker**`.

### 3. Развернуть фундамент → `de-template`

- Gate: стек `stable`, валидатор зелёный, state чист.
- **Чейнь в `de-template`**: читает stable-артефакты, разворачивает по `Generates` — имя проекта, README, `.env.example`, wiring `app.py`/`config.py`. Механика детерминирована (Phase A); wiring — reviewable diff (Phase B). Зависимость `pylibinfra[tgbotkit]` остаётся.

### 4. Scaffold спроектированных фич → `scaffold feature`

Платформа развёрнута — теперь по каждому **stable**-флоу из этапа 1 разверни код фичи:

- **Чейнь в `scaffold` (вариант `feature`)** per фича: разворачивает вертикальный срез `features/<name>/` (полный гексагон или сокращённый), Provider, регистрацию в `app.py` (`build_container` + `ExtensionProvider`), StatesGroup в `platform/dialogs/states.py`; бэкенд-данные — pkg-клиент (`scaffold` backend-port).
- **Инвариант порядка**: scaffold своих фич идёт **до** удаления reference (этап 5) — иначе теряешь живой образец.

### 5. Удалить/переделать reference-фичи

Когда свои фичи спроектированы и сгенерированы — убрать учебные `profile`/`payments`/`lang`/`notifications` и **переделать** `start` под своё меню (чеклист — `de-template references/prune.md`):
- `start` обычно НЕ удаляется целиком — переписывается под корневой ROOT + своё меню (бот без ROOT-диалога не имеет точки входа).
- `payments`/`notifications`/`lang` — прунятся, если бот без платежей/push/i18n; иначе адаптируются.

### 6. Финал

`make check` зелёный + startup-smoke (`pytest -k collision`) чистый → проект больше не помнит про шаблон. Сообщи юзеру: онбординг закрыт, дальше обычный флоу через `/smartdev`; релиз образа — `/release`. `docs/getting-started.md` (META) можно удалить.

## Что init-service НЕ делает

- ❌ Не проектирует флоу/стек сам — это `/dialog-deep-dive` и `/stack-deep-dive` (раунды `AskUserQuestion`, дисциплина опции-vs-Other, draft→stable gate).
- ❌ Не лезет в `state/` чейненных скиллов — только проверяет на чистоту `**blocker**` как gate-условие.
- ❌ Не правит фундамент руками и не де-темплейтит — это `de-template`.
- ❌ Не запускает `de-template` до зелёного `make validate-stack-docs`.
- ❌ Не пропускает проектирование ради «быстро сгенерить» — дизайн первичен, иначе движку не из чего разворачивать.

## Anti-patterns

- ❌ Кодить/править `platform`/`app.py` до того как спроектированы артефакты.
- ❌ Удалять reference-фичи до того как свои готовы (теряешь живой образец гексагона).
- ❌ Удалить `start` целиком, оставив бота без ROOT-диалога.
- ❌ Дублировать процедуру deep-dive внутри этого скилла — он только дирижёр.
