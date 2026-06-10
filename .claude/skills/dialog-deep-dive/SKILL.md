---
name: dialog-deep-dive
description: Спроектировать флоу диалога как source-of-truth ДО кода — окна, переходы, getter-данные, состояния виджетов, StatesGroup. Ведёт сессию через раунды AskUserQuestion (без монологов и догадок), фиксирует флоу в docs (карта диалога) + рабочую память state/. Аналог domain-deep-dive, но для UI-сценария бота. Если рядом sibling-checkout'ом лежит стратегия-репо (`<org>/strategy`, форк business-strategy-template) со слоем telegram-bot-flow/<surface>/ — работает ТРАНСЛЯТОРОМ его stable-артефактов (dialog/window/command/notification) в карту флоу и код-понятия, а не интервьюером. Активируй когда проектируешь новый пользовательский сценарий/флоу, говоришь "/dialog-deep-dive", "спроектируем диалог", "продумаем флоу/экраны", "как должен идти этот сценарий", "разверни дизайн из стратегии", или когда init-service/plan дошёл до нового флоу. Точечная правка уже спроектированного окна — прямой Edit/scaffold, не сюда.
---

# Skill: dialog-deep-dive

Проектирование **флоу диалога** как source-of-truth **до** кода. Где `stack-deep-dive` отвечает «на какой платформе», этот скилл — «как именно пользователь идёт по сценарию»: какие окна, какие переходы между ними, какие данные нужны каждому окну (getter), какое состояние виджетов держим, какая `StatesGroup`.

Зачем до кода: флоу, придуманный по ходу написания `dialogs.py`, расползается (недостижимые окна, тупики, getter без данных, дубль State → `setup_dialogs` падает). Спроектированный флоу — это вход для `scaffold feature`/`dialog`/`window` и для `preview-flow` (граф-проверка).

## Когда применять

- Новый пользовательский сценарий: «визард регистрации», «оформление заказа», «настройки».
- `/init-service` дошёл до этапа 1 (проектирование флоу), `/plan` упёрся в «а как идёт диалог».
- Переделка существующего флоу (несколько окон/переходов меняются разом).

## Когда НЕ применять

- Одно окно/одна кнопка в готовый диалог, флоу очевиден → прямой `scaffold window`.
- Платформа (polling/webhook, Redis, бэкенды) → `stack-deep-dive`.
- Эволюция `StatesGroup` живого бота → `state-migration` (это про безопасность деплоя, не про дизайн).

## Главный ритм: AskUserQuestion

Скилл — **интервьюер**, не сценарист. Партнёр — тот, кто владеет продуктовым сценарием; его решения дословно ложатся в карту флоу, скилл их **не сочиняет**. Каждый шаг — раунд `AskUserQuestion` (до 4 вопросов) → ответ → пишем в карту/`state` через `Edit` → следующий раунд.

- ❌ Длинный prose «вот как бы я нарисовал флоу» вместо вопросов.
- ❌ «По умолчанию» добавить экран подтверждения/отмены, потому что «обычно так».
- ❌ >4 вопросов одним AskUserQuestion (инструмент режет молча).
- ❌ Копить ответы «запишу в конце» — пиши после каждого раунда (теряется при `/clear`).
- ✅ Сомневаешься, нужен ли отдельный экран подтверждения → лишний раунд, а не догадка.

Enum'ы как опции (тип виджета, тип перехода, launch-mode); тексты, имена State, конкретные данные — свободной формой (Other).

## Вход из стратегии (`<org>/strategy`)

Если рядом sibling-checkout'ом лежит стратегия-репо (форк `business-strategy-template`, жёсткий
upstream экосистемы) и в нём для bot-поверхности есть слой
`docs/projects/<project-slug>/telegram-bot-flow/<surface>/` — **дизайн уже спроектирован
аналитиком** (скиллы `telegram-bot-flow-deep-dive`/`-audit`). Тогда скилл — **транслятор**, не
интервьюер: читает 4 kind и разворачивает их в карту флоу и код-понятия.

| Артефакт стратегии (поля) | → код-понятие бота |
|---|---|
| `dialogs/<slug>/index.md` (`states-group`, `windows`, `launch-mode`, `started-by`, `dialog-data`) | `StatesGroup` (имя = `states-group`); порядок `State` = порядок `windows`; `LaunchMode` (`root`→`ROOT`); точки входа; контракт `dialog_data` |
| `windows/<slug>/index.md` (`state`, `message`, `widgets`, `getter`, `errors`) | `Window` (`state` = имя `State`); текст → `I18NFormat`/`Format` + `.ftl`; виджеты (`button`/`url`/`select`/`multiselect`/`text-input`/`calendar`) → `kbd`/`TextInput`/`Calendar`; getter-ключи (source + **fallback**); `errors` → `ErrorUX`/getter-дефолты |
| `command.md` (`command`, `starts`, `stack`, `payload`) | dispatcher-level `CommandSpec` (`CommandBundle`); `stack: reset` → `RESET_STACK`; deep-link `payload` → `start_data` |
| `notification.md` (`trigger`, `to`, `content`, `idempotency`) | NATS-подписчик (`NotifierBundle`/`BgManager`); `trigger: event:…` → subject; идемпотентность |

Действия и данные ссылаются на домен: `widget.action` / `getter.source` = `use-case:<ctx>.<Operation>`
→ usecase/порт фичи (имена операций — из `domains/<ctx>/use-cases/` той же стратегии);
`notification.trigger` = `event:<ctx>.<Event>` → subject подписчика. Зеркало UX — `interface/<surface>/`
той же стратегии. Полный маппинг полей в файлы фичи — `docs/reference/dialog-mapping.md`.

**Контракт чтения.** Брать только `status: stable`-артефакты; стратегия-репо **read-only** (в неё
не пишем — дыры в дизайне эскалируются аналитику запуском `/telegram-bot-flow-deep-dive`, до ответа
фиксируются в `state/` как `**blocker**`). Карта флоу всё равно пишется в `docs/stack/dialogs.md`
(с пометкой источника — `<project-slug>`/`<surface>` стратегии): она остаётся входом
`scaffold`/`preview-flow`. Раунды `AskUserQuestion` — **только по дырам** (чего в артефактах нет:
тексты ошибок вне канон-ключей, платформенные детали), не по уже принятым решениям аналитика.

## Что проектируем (оси флоу)

| Ось | Вопросы |
|---|---|
| **Окна** | сколько экранов? что каждый показывает (статика vs динамика)? медиа? |
| **Переходы** | как из окна в окно: `SwitchTo` (внутри группы) / `Next`/`Back` / `Start` (вложенный диалог) / `Cancel`/`done` (выход) / ввод (`TextInput.on_success`)? тупики есть? |
| **Точка входа** | команда (`/foo`) / кнопка из другого диалога (`Start`) / вложенный `manager.start`? корневой (`LaunchMode.ROOT`) — да/нет? `/start`=RESET_STACK? |
| **getter-данные** | какие ключи `Format("{...}")` в каждом окне? откуда (usecase→порт/identity/state)? дефолты на случай ошибки? |
| **Состояние виджетов** | что держим в `dialog_data`/`widget_data`/`start_data` между окнами (черновик ввода, выбор)? всё JSON-сериализуемо? |
| **StatesGroup** | имя группы, перечень `State` (один State = одно окно); не пересекается с существующими? |
| **Ошибки/edge** | пустые данные, отказ бэкенда (мягкий `status` в getter), невалидный ввод (`on_error`), stale-callback (что в `ErrorUX`)? |
| **i18n** | какие ключи перевода (префикс = фича)? какие подписи статичны (`I18NFormat`) vs динамичны (`Format`)? |

## Карта флоу (артефакт)

Пиши карту в `docs/stack/dialogs.md` (раздел `## Flow: <feature>`) — она же роллапится в stack-артефакт `dialogs`. Формат — таблица окон + список переходов + getter-контракт:

```markdown
## Flow: checkout

**Точка входа.** Кнопка «Купить» из меню → Start(CheckoutSG.OFFER). Не ROOT.

**Окна.**
| State | Показывает (getter-ключи) | Реакции (handler) | Переходы |
|---|---|---|---|
| OFFER | title, price (usecase.offer) | on_buy | → CONFIRM (SwitchTo) · ← меню (Cancel) |
| CONFIRM | summary (из start_data) | on_confirm / on_back | success → DONE · ← OFFER (Back) |
| DONE | order_id (usecase.result) | — | ← меню (Cancel) |

**Состояние виджетов.** start_data: {offer_id: str}. dialog_data: {} (всё с бэкенда). JSON ✓.

**Ошибки.** OFFER: бэкенд недоступен → getter отдаёт price="—", status="временно недоступно".
CONFIRM отмена → Back на OFFER. stale → ErrorUX подсказывает /start.

**StatesGroup.** Checkout(OFFER, CONFIRM, DONE) — новая, не пересекается.

**i18n.** ключи: checkout-offer-title, checkout-confirm, checkout-done, common-back.
```

## Память `state/<feature>.md`

- Рабочие вопросы по флоу, ещё не решённые (`## Открытые вопросы`, опц. `**blocker**`), неочевидные UX-решения (`## Решения`).
- Все пусты → удалить. **Forward-only**. Коммитится (`.claude/skills/dialog-deep-dive/state/`).

## Контракт «готов к scaffold»

Флоу готов отдавать в `scaffold`, когда:
1. Каждое окно имеет `State`, getter-ключи (с источником) и переходы — нет «висящих» окон.
2. **Достижимость**: из точки входа есть путь в каждое окно; из каждого окна есть выход (нет тупиков). Сомнительно — проверь графом (`preview-flow`, `render_transitions`).
3. Состояние виджетов — только JSON-примитивы (rule `storage-serialization`).
4. `StatesGroup` не пересекается с существующими (rule `state-lifecycle`).
5. Ошибочные/пустые ветки описаны (getter-дефолты, `on_error`, stale → `ErrorUX`).
6. `state/` чист по `**blocker**`.

Все ✅ → через `AskUserQuestion` «Готов кодить? → `scaffold feature/dialog/window`».

## Завершение сессии

1. Перечислить спроектированные/обновлённые флоу (карты в `docs/stack/dialogs.md`).
2. Нерешённые `**blocker**` (из `state/`).
3. Предложить: проверить граф (`/preview-flow`) перед кодом; затем `scaffold`. Если пришёл из `/init-service` — вернуться в оркестратор (этап 2 — стек).

## Запреты

- Не сочинять флоу/экраны — спрашивать через `AskUserQuestion`.
- Не писать код (`dialogs.py`/getters/handlers) — это `scaffold`, после дизайна.
- Не оставлять окно без перехода-выхода (тупик) или без `State`.
- Не класть в виджет-состояние не-JSON (`datetime`/объект).
- Не пересекать новую `StatesGroup` с существующими.
- Не аккумулировать историю в `state/` — forward-only.
- Не задавать >4 вопросов одним AskUserQuestion.
