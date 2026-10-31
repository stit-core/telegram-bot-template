---
name: init-service
description: Оркестратор онбординга форка шаблона бота — ведёт путь форк → проектирование флоу диалогов (dialog-deep-dive) → проектирование стека (stack-deep-dive) → de-template → scaffold фич → удаление reference-фич, пока проект не перестанет помнить про шаблон. Используй, когда юзер форкнул telegram-bot-template и хочет развернуть из него свой бот или спрашивает, с чего начать (/init-service), и когда видишь свежий форк (имя проекта ещё telegram-bot-template, reference-фичи start/profile/payments на месте). Сам не проектирует и не де-темплейтит — чейнит специализированные скиллы по порядку.
---

# Skill: init-service (онбординг-оркестратор)

Дирижёр пути «форк шаблона → свой бот». Не делает проектирование/генерацию сам, а **ведёт по этапам и чейнит** специализированные скиллы, держа фокус: дизайн первичен, код вторичен и разворачивается по нему. Один проход доводит до проекта, который ничего не помнит про шаблон.

Полное описание пути для человека — `docs/getting-started.md`; этот скилл его исполняет.

## Когда применять

- "/init-service" / "онбординг" / "развернул форк, что дальше"
- Свежий форк: `[project] name` ещё `telegram-bot-template`, reference-фичи `start`/`profile`/`booking`/`payments`/`lang`/`notifications` на месте
- Юзер: «хочу развернуть свой бот из шаблона»

## Когда не применять

- Проект уже де-темплейтизирован (своё имя, reference-фичи удалены) — обычный день, иди в `/smartdev`.
- Юзер хочет добавить фичу/диалог в уже-свой бот — это `scaffold`, не онбординг.

## Pre-flight

- [ ] Форк создан, репозиторий склонирован (Gitea → **Use this template** → `<org>/<bot>`).
- [ ] `make setup` прогнан (`uv sync` + git-хуки commit-msg/pre-commit/pre-push).
- [ ] `pylibinfra` резолвится при `uv sync` (git-тег в `[tool.uv.sources]` `pyproject.toml`; доступ к приватной Gitea — `git config … insteadOf` из README).
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

Когда свои фичи спроектированы и сгенерированы — убрать учебные `profile`/`booking`/`payments`/`lang`/`notifications` и **переделать** `start` под своё меню (чеклист — `de-template references/prune.md`):
- `start` обычно не удаляется целиком, а переписывается под корневой ROOT + своё меню: бот без ROOT-диалога не имеет точки входа.
- `payments`/`notifications`/`lang` — прунятся, если бот без платежей/push/i18n; иначе адаптируются.

### 6. Финал

`make check` зелёный + startup-smoke (`pytest -k collision`) чистый → проект больше не помнит про шаблон. Сообщи юзеру: онбординг закрыт, дальше обычный флоу через `/smartdev` (задачи обычно приходят из корня проекта — сессией корня или её фоновым агентом, прямой заход тоже нормален); релиз образа — `/release`. `docs/getting-started.md` (META) можно удалить.

## Границы

init-service — только дирижёр: проектирование флоу и стека ведут `/dialog-deep-dive` и
`/stack-deep-dive` (раунды `AskUserQuestion`, draft→stable gate), фундамент разворачивает
`de-template`, код фич — `scaffold`. В `state/` чейненных скиллов он лишь проверяет отсутствие
`**blocker**` как gate-условие. Порядок этапов держит дизайн первичным: код и правки
`platform`/`app.py` — только по спроектированным артефактам, иначе движку не из чего
разворачивать; reference-фичи уходят последними, пока служат живым образцом.
