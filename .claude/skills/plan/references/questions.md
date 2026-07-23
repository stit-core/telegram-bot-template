# Планировочные вопросы (бот)

Список для шага 1 skill `plan`. Выбирай 3–5 релевантных задаче — не задавай всё подряд. Дизайн-вопросы задавай через `AskUserQuestion`. Если на 5+ ответ «не знаю / решай сам» — задача недозрелая: предложи research-spike или отложить.

## Скоуп
- Что входит в задачу? Что осознанно НЕ входит?
- Это новая фича / новый диалог-флоу / рефакторинг / эксперимент? (Багфикс → `triage-failure`, не план.)
- Связано ли с другими PR/задачами/секциями roadmap?

## Диалог-флоу (presentation)
- Сколько окон, какие переходы между ними? (Если флоу ещё не зафиксирован → `dialog-deep-dive` сперва.)
- Какие данные нужны getter'у каждого окна? Откуда (usecase → порт)?
- Корневой диалог (`LaunchMode.ROOT`) или вложенный? Откуда входят (`/start`, команда, кнопка)?
- Состояния виджетов (`widget_data`/`dialog_data`) — что храним? Всё JSON-сериализуемо?

## State-эволюция (`platform/dialogs/states.py`)
- Добавляем новый `State`/`StatesGroup` или меняем существующий?
- Меняешь/удаляешь **живой** State → это deprecation, не удаление (→ `state-migration`). Что у юзеров в открытых диалогах сломается на деплое?

## Порты бэкенда / данные
- Нужен новый метод pkg-клиента / порта фичи (`scaffold` backend-port)? Какой endpoint, форма ответа (wire-модель)?
- Идемпотентность мутации нужна? (`Idempotency-Key`, ASCII-safe.)
- Несколько именованных бэкендов (`BackendsConfig` + `*_BASE_URL` env → INFRA-HANDOFF)? Деградация при open-breaker — какой UX-текст?
- Боту нужен только свой state (Redis) или поход в бэкенд?

## Cross-feature
- Какая фича владеет логикой? Нужен ли cross-feature порт + адаптер (`ports.py` потребителя + `adapters.py`)?

## Платежи / WebApp / i18n (если задеты)
- Платёж: цена/состав берутся с бэкенда (не из callback)? Дедуп по `charge_id`?
- WebApp: initData валидируется (`validate_init_data`)? Канал доставки (свой бэкенд-эндпоинт vs `sendData`)?
- i18n: новые ключи перевода? Префикс = имя фичи? Все локали (`locales/<lang>/<feature>.ftl`) покрыты?

## Фон / события
- Новый notification (NATS-subject → Telegram)? Durable consumer (JetStream) или core?
- Периодическая джоба (`timerkit`)? Идемпотентность доставки (at-least-once)?
- Фоновые апдейты не проходят обычные middleware — нужно дублировать на `DIALOG_EVENT_NAME`?

## Тесты
- RED-first для какого слоя? unit (policy/views) или flow (BotClient+MockMessageManager)?
- Мокаем порт (не транспорт)? Локаторы кнопок по callback_data?

## Rollout / откат
- Деплой ломает живые диалоги (State-эволюция)? error-handler как сеть достаточен?
- Что делать, если падает в проде? `/start` RESET_STACK спасает?

## Инфра-поверхность (→ секция Infra impact + skill infra-handoff)
- Новый/изменённый required env-var/секрет (`config.py`/`.env.example`, `BOT_TOKEN`/`WEBHOOK_*` — значение в compose env проекта)?
- Webhook vs polling-режим тронут? `allowed_updates` расширяются?
- Cross-service NATS-subject (notification)?
- Новая инфра-механика (middleware/runtime/новый kit-helper) → это **не правка шаблона**, а PR в `tgbotkit` через `infra-handoff`.
- Новая runtime-зависимость (`pyproject.toml`)?
