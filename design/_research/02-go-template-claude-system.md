# 02 · `.claude`-система go-backend-template — разбор и проекция на бота

Дотошный разбор `.claude`-системы `go-backend-template` (с привлечением `pylibinfra`
для сравнения), чтобы спроектировать аналогичную систему для `telegram-bot-template`
(aiogram + aiogram_dialog, инфра за `pylibinfra`).

Источники (все пути от `/root/git/sftbmb/sftbmb-core/`):
- `go-backend-template/CLAUDE.md`, `go-backend-template/docs/{README,contributing}.md`
- `go-backend-template/.claude/skills/*/SKILL.md` (10 шт.) + `references/` + `state/`
- `go-backend-template/.claude/rules/*.md` (8 шт.)
- `go-backend-template/.claude/agents/*.md` (2 шт.), `.claude/settings.json`, `.claude/plans/roadmap.md`
- `pylibinfra/CLAUDE.md`, `pylibinfra/.claude/skills/{add-kit,release}/SKILL.md`, `pylibinfra/.claude/rules/{comments,forward-only}.md`
- `telegram-bot-template/aiogram-dialog-docs/guides/{architecture,building-a-template}.md` (целевой стек)

---

## 1. Все скиллы go-backend — назначение / триггер / механика / references

10 скиллов. Колонка **Backed** различает: `skill-only` (процедура — текст SKILL.md,
edits под ней) vs `script-backed` (тяжёлая часть в `make`/`scripts/`, скилл оркестрирует).

| Скилл | Назначение | Триггер (description + `/cmd`) | Механика | Backed | References |
|---|---|---|---|---|---|
| **smartdev** | Always-on cockpit дневного флоу: собрать состояние, поднять контекст, **сам переключить** в нужный режим, вести RED→GREEN | старт сессии / после `/clear` / «что у нас», «с чего начать», «статус» | §1 `make status` (детект critical/drift/infra/ATTENTION) → §2 дочитать `roadmap.md` целиком + `go.mod`/`docs/stack` сам → §3 чейн-таблица (приоритет сверху-вниз) → §4 RED→GREEN петля → §5 передача в planner. Вывод ≤25 строк, **не** дамп raw status | script-backed (`make status`) | — |
| **plan** | Planning-first: разложить на атомы, задать вопросы, вести inline-секцию в едином `roadmap.md` (переживает `/clear`) | «/plan», «распиши план», «спланируем»; **любое** содержательное изменение (>1 файла, схема, cross-domain, security). Багфикс → НЕ сюда | §1 3-5 вопросов из `references/questions.md` (через `AskUserQuestion`) ДО записи → §2 slug `<verb>-<object>` → §3 `### <slug>`-секция (bold-лейблы, `####`-фазы, атом = 1 коммит + `Verify:` + `Зависит от:`) → §4 STOP, показать → §5 approve→in-progress → §6 чекпоинты → §7 blocked → §8 done (удалить секцию). Валидатор `validate-plan.sh` в pre-commit | script-backed (валидатор) | `references/questions.md` (банк вопросов: скоуп/API/схема/cross-domain/security/тесты/rollout/infra) |
| **scaffold** | Добавить строительный блок в **существующий** проект по конвенциям. Роутер на 5 вариантов | «добавь домен/endpoint/событие/миграцию/порт», «новый route», «измени схему», «домену A нужны данные из B» | Роутер: таблица «что добавляешь → вариант → reference → сигналы». Общий ритм (§1 подтвердить вход → §2 правка → §3 `make gen` → §4 RED→GREEN → §5 `make check` → §6 Conventional Commit + INFRA-HANDOFF). Специфика — в reference, скилл их не пересказывает | script-backed (`make new-domain`, `make gen`) | `domain`, `endpoint`, `event`, `migration`, `port` (5 пошаговых процедур) |
| **stack-deep-dive** | Интерактивная проработка 8 платформенных артефактов `docs/stack/` — единственный вход проектирования стека. Source of truth и вход `de-template` | «спроектируем стек», «добьём stack-артефакты», сырьё (compose/k8s/main.go), приход из `init-service` | **AskUserQuestion-интервьюер** (≤4 вопроса/раунд, пишет после каждого). 3 режима (A заведение / B сырьё / C углубление). Inside-out волны (service→kit'ы→config+runtime роллапы). Своя память `state/<kind>.md` (коммитится). Контракт `draft→stable` (6 пунктов, главный — непустой `Generates`). Cross-kind sync авто-роллап в config/runtime | skill-only (движок — текст; `make validate-stack-docs` лишь gate) | `workflow-patterns` (3 режима), `field-checklists` (8 kinds), `draft-stable` (6-пунктный gate + тест-критерии), `state-format` (формат памяти) |
| **init-service** | Оркестратор онбординга форка → свой проект. Сам не делает — **чейнит** специализированные скиллы по порядку | «/init-service», «онбординг», «развернул форк», свежий форк (module path ещё `…template`, reference-домены на месте) | 6 этапов: ①домены-вход (в соседнем docs-репо, готовы) → ②`stack-deep-dive` → ③`de-template` → ④`scaffold` доменов → ⑤удалить reference → ⑥`make check`. Между этапами — gate'ы (валидатор зелёный, state без `**blocker**`). Дирижёр, не исполнитель | skill-only (оркестрация) | — (делегирует в чейненные) |
| **de-template** | Развернуть форк в самостоятельный проект по stable `docs/stack`: module path, README, `.env.example`, platform/cmd wiring, prune reference | «/de-template», «разверни фундамент», «де-темплейтизируй»; init-service дошёл до развёртывания. **НЕ на каноническом шаблоне** | Gate (не канон-шаблон / стек stable / state чист). Phase A детерминированная механика (A.1 module path `sed` → A.2 README → A.3 `.env.example` → A.4 strip меты → A.5 prune). Phase B doc-driven wiring (6 `Generates` reviewable-диффом). Запуск **один раз** | **skill-only** (нет committed-скрипта — и механика, и wiring reviewable edits под процедурой) | `prune` (8-точечный чеклист удаления reference), `wiring` (маппинг 6 `Generates`→код) |
| **triage-failure** | Red-арм cockpit'а: разбор красного теста/lint/build/drift, TDD-first для багфиксов (RED→GREEN) | «тест падает», «не компилится», «почему упало», stack trace; smartdev чейнит на ATTENTION. **Багфикс сюда, не plan** | Таблица категорий (build/lint/unit/integration/race/panic/drift). §1 воспроизвести минимально → §2 прочитать сообщение целиком → §3 гипотеза → §4 TDD для багов (падающий тест ПО ТОЙ причине → фикс → green) → §5 не-баг-флоу (таблица фиксов) → §6 чужой код → §7 застрял (делегировать `explorer`, или `plan` на spike) | script-backed (`make test/lint/gen`) | — |
| **infra-handoff** | Оформить INFRA-HANDOFF-блок инфра-админу при изменении инфра-поверхности | правишь env/config/migrations/events/NATS/go.mod; `make status` дал Infra-touch; «что передать админу» | §1 классифицировать (env/миграция/cross-service/runtime-deps) → §2 адресат (корп Vault / проект compose / оба) → §3 блок `WHAT/WHY/ACTION/WHO/DECIDE/RISK` → §4 положить так, чтобы доехало (чат + `**Infra impact.**` в плане; `release.sh` агрегирует) → §5 граница (не патчить Vault/деплой сам) | skill-only | — (правило-якорь `rules/infra-impact.md`) |
| **release** | Запушить версию backend-image (api+migrate lockstep) одной командой + агрегированный handoff | «релиз», «запушим версию», «/release» | Pre-flight (юзер OK / main+clean / `make check` зелёный / залогинен в registry). §1 semver-bump → §2 `make release VERSION=vX.Y.Z` (`release.sh`: валидация semver → confirm-промпт → annotated tag → preflight+doctor → `docker buildx --push` 2 образа → печать INFRA-HANDOFF) → STOP. Handoff (vault/`make ship`) — в чужих репо | script-backed (`make release`/`release.sh`) | — |
| **query-logs** | Чтение прод-логов через корп-Loki под bearer из `.env.local` | «посмотри логи», «что упало в проде», «следи за деплоем», «/query-logs» | Один инструмент `scripts/tools/logs.sh`, 3 режима: `query` (точечно), `errors` (триаж по сигнатурам), `watch` (мониторинг N мин, `run_in_background`+`Monitor`). Токен — только через bash-процесс инструмента (НЕ `cat .env.local`). После находки → `triage-failure` | script-backed (`logs.sh`) | — (правило-якорь `rules/env-local.md`) |

### Карта чейнинга (как скиллы вызывают друг друга)

```
                       ┌──────────── init-service (онбординг-оркестратор) ────────────┐
                       │   stack-deep-dive → de-template → scaffold(domain)×N → prune  │
                       └───────────────────────────────────────────────────────────────┘
                                            (de-template ⟶ prune.md, wiring.md)

day-to-day:  smartdev (cockpit)
               ├─ ATTENTION/red/drift ───────────────► triage-failure  (RED→GREEN; ←delegate explorer)
               ├─ Infra-touch ≠ none ────────────────► infra-handoff   (← rule infra-impact)
               ├─ big task (>5 шагов/схема/security) ─► plan           (questions.md; →release агрегирует Infra impact)
               ├─ scaffold-задача ───────────────────► scaffold        (domain/endpoint/event/migration/port)
               ├─ багфикс ───────────────────────────► triage-failure  (НЕ plan!)
               └─ мелкое/понятное ──────────────────► напрямую (всё равно RED→GREEN)

release:     release (← pre-flight make check; ← агрегирует **Infra impact.** из roadmap)
logs:        query-logs (находка → triage-failure)
```

Ключевые дисциплины чейнинга:
- **smartdev — диспетчер**, переключает, а не комментирует («→ перехожу в `<skill>`, потому что …»).
- **Багфикс никогда не идёт в `plan`** — только `triage-failure` (RED-first). Это явный инвариант в 4 местах.
- **`plan` → `release`** через `**Infra impact.**`: infra-блоки накапливаются в плане, `release.sh` их агрегирует. Если план закрывается раньше релиза — переносятся в `## Backlog`.
- **init-service сам ничего не делает** — только чейнит и держит gate'ы между этапами.

---

## 2. Rules — path-scoped, их роль

8 правил в `.claude/rules/`. Грузятся **когда matching-файл в контексте** (нативный ключ
`paths:`, не `globs:` — подчёркнуто в `contributing.md`). Правило без `paths:` грузилось бы
всегда. Сила — advisory (контекстная подсказка); детерминизм держат git-хуки + `permissions.deny`.

| Rule | `paths:` | Роль |
|---|---|---|
| `forward-only` | `**/*.md` | Любой текст — только текущее состояние, без «было/стало». История — `git log`+Conventional Commits. Планы — без архива (done-секция удаляется) |
| `comments` | `**/*.go` | Комментарии только WHY, ≤1 строка. Запрещены restate-WHAT, narration, tombstones, ссылки на task/PR |
| `domain-architecture` | `internal/domain/**` | Раскладка слоёв, cross-domain только порты+адаптеры (depguard), HTTP DTO domain-specific имена, I/O в usecase не в entity, логи `logkit` |
| `sqlc-and-migrations` | `migrations/**`, `internal/domain/*/infra/postgres/**`, `sqlc.yaml` | Парные up/down, обратимость, не править накатившуюся, sqlc-аннотации, generated не руками, kit-таблицы через MigrationsFS |
| `events-and-messaging` | `**/events.go`, `**/delivery/nats/**`, `internal/jobs/**` | Outbox в одной tx, локальный subject-литерал у consumer, идемпотентность обязательна, subscriber быстрый, jobs в той же fx.Lifecycle |
| `tests-pipeline` | `**/*_test.go`, `internal/testkit/**`, `.mockery.yml` | Black/white-box, моки через mockery v3, TDD для багфиксов, integration build-tag, coverage-floor, инжект clockkit вместо time.Now() |
| `infra-impact` | `.env.example`, `config/**`, `migrations/**`, `**/events.go`, `**/delivery/nats/**`, `cmd/api/**`, `go.mod` | Тронул инфра-поверхность → ОБЯЗАН INFRA-HANDOFF-блок до claim/коммита. Таблица классов поверхности. Якорь для skill `infra-handoff` |
| `env-local` | `.env.local`, `.env.local.example`, `scripts/tools/logs.sh`, `test/stack/up.sh` | Формат dev-tooling токенов, security-инвариант «токен только через tools, не `cat`», граница с одноимённым правилом в compose-репо |

**Паттерн rule↔skill:** правило — terse-инварианты «что соблюдать», скилл — процедура «как делать».
`domain-architecture`↔`scaffold`, `sqlc-and-migrations`↔`scaffold/migration`,
`infra-impact`↔`infra-handoff`, `env-local`↔`query-logs`, `tests-pipeline`↔`scaffold`+`triage-failure`.
«Как и почему» вынесено в `docs/reference/*`, правило только ссылается.

---

## 3. CLAUDE.md-роутер и cockpit-паттерн

**CLAUDE.md = ядро (always-on) + роутер**, ≤200 строк (явный non-goal про длину).
Структура `go-backend/CLAUDE.md`:
- Точка входа (`/smartdev` cockpit · путь потребителя · planning-first).
- «Проектирование первично, код вторичен» — DDD в соседнем docs-репо, stack локально, source of truth.
- Команды (единый `make <verb>`, gate `make check`).
- **Карта «где что»** (таблица Тема→Где: `docs/reference/*` + rule + skill).
- Стиль кода (инварианты: gofumpt, depguard, errors `%w`, golibinfra-first).
- Git workflow, **Границы** (Делать всегда / Сначала спросить / Не делать никогда), Forward-only.

Прогрессивное раскрытие: на холодном старте — только имена+описания скиллов/правил;
тела грузятся по необходимости. CLAUDE.md не дублирует детали — роутит в `docs/`/rules/skills.

**Cockpit-паттерн (`smartdev` + `make status`):** разделение ответственности —
- `make status` (детерминированный bash) даёт **детект критичного**: branch, working tree,
  Critical (BUILD/SQLC/MIGRATIONS/DRAFT), Infra-touch, Plan (Active+next атом), Domains, TODOs,
  и финальную строку `OK`/`ATTENTION:<что>` — это **сигнал ветвления**.
- `smartdev` (модель) **дочитывает прозу** сам (roadmap целиком, go.mod, docs/stack — status
  их намеренно не парсит, «bash хрупок на прозе») и **сам чейнит** в режим.

**Planning-first + roadmap.md:** единственный артефакт планирования — `.claude/plans/roadmap.md`.
Никаких per-slug файлов/архивов/changelog'ов (расходятся с правдой). `## Active` (inline-секции
`### <slug>`) + `## Backlog`. Жизненный цикл `planning→in-progress→blocked?→done`, done →
секция удаляется (forward-only). План закоммичен → переживает `/clear`, ревьюится в PR.

**INFRA-HANDOFF дисциплина:** репо останавливается на image-in-registry; всё, что требует
действия инфра-стороны (env/секрет/миграция-с-эффектом/cross-service/runtime-dep) → структурный
блок `WHAT/WHY/ACTION/WHO/DECIDE/RISK` → копится в `**Infra impact.**` плана → `release.sh`
агрегирует. Soft-механизм (rule+skill, не хук) — гарантия в дисциплине агента.

**Forward-only:** сквозной инвариант (отдельное правило + секция в CLAUDE.md). Текст =
текущее состояние, история в git. Касается и stack-deep-dive `state/`, и планов.

---

## 4. settings.json / hooks

`go-backend/.claude/settings.json`:
- `"effortLevel": "max"`, `"autoMemoryEnabled": false`.
- **`permissions.allow`** — широкий allowlist read-only/safe команд (`make test/lint/check/gen/status`,
  `go test/build/vet`, `sqlc`, `mockery`, `docker buildx*`, `rg/grep/find`, read-only `git`,
  `Read/Glob/Grep(*)`). Цель — меньше permission-промптов на рутинных верификациях.
- **`permissions.deny`** — детерминированные блокировки: `*--no-verify*`, `*--no-gpg-sign*`,
  `git push --force/-f`, `git reset --hard`, `git checkout -- *`, `git clean -f`, `rm -rf *`;
  `Read/Edit(**/*.pem|**/*.key)`; `Edit/Write(**/infra/postgres/db/**)` и `(**/mocks/*.go)`
  (generated); `Edit(go.sum)`; запись в `**/.claude/projects/**/memory/**`.

**Hooks:** Claude Code хуков (PreToolUse/PostToolUse/Stop) **нет** — осознанное решение
(`contributing.md`). Критичные инварианты держат **git-хуки** (`scripts/git-hooks/`, ставятся
`make setup`: commit-msg=Conventional Commits, pre-commit=fmt+vet+lint+validate-stack/plan,
pre-push=`make check`) + **`permissions.deny`**. Soft-guidance — CLAUDE.md и rules.

Двухуровневая защита: **детерминированно** (git-хуки + deny) для критичного; **advisory**
(CLAUDE.md + rules + skills) для остального. `pylibinfra` тоньше: settings.json не разбирали
в задаче, но CLAUDE.md тот же ядро+роутер, gate — `ruff/mypy/pytest`.

---

## 5. Скиллы для бота — предлагаемый аналог

Контекст бота (из `aiogram-dialog-docs/guides/`): aiogram + aiogram_dialog, инфра за
`pylibinfra` (Python, dishka, async-first, pydantic-settings). Своё у бота — **state** (диалоги,
FSM-storage, навигация по стеку), бот — фронтенд к бэкендам (API/вебхуки). Аналог go-backend-системы:

### 5.1. Скиллы, переносимые почти 1:1 (с адаптацией стека)

| go-backend | Бот-аналог | Что меняется под aiogram |
|---|---|---|
| `smartdev` | **`smartdev`** | Тот же cockpit. `make status` → bot-`make status`: branch/tree + Critical (**IMPORT/MYPY/RUFF/STARTUP** — `dp.emit_startup()` ловит коллизии StatesGroup) + DRAFT-stack + Infra-touch + Plan + **Dialogs** (список диалогов/StatesGroup) + TODOs. Чейн-таблица та же |
| `plan` | **`plan`** | 1:1. `references/questions.md` адаптировать: вместо API/схема БД — **диалог-флоу/состояния/storage-сериализация/backend-порты/i18n/rollout состояний**. Атом+`Verify:` (тут `make test`/`pytest`) |
| `triage-failure` | **`triage-failure`** | Категории под Python: import/mypy/ruff/**pytest-asyncio**/**startup-collision**/**storage TypeError** (несериализуемое в dialog_data)/**UnknownIntent-UnknownState**. TDD через `BotClient`+`MockMessageManager`+`JsonMemoryStorage` |
| `query-logs` | **`query-logs`** | **Почти 1:1** — корп-Loki тот же, токен в `.env.local`, `logs.sh` 3 режима. `service` label = имя бот-бинаря. Watch особенно полезен после деплоя |
| `infra-handoff` | **`infra-handoff`** | Тот же `WHAT/WHY/ACTION/WHO/DECIDE/RISK`. Инфра-поверхность бота: **`BOT_TOKEN`/webhook-секрет, Redis (FSM-storage) URL, backend API base-URL, OTEL_*, новая зависимость в pyproject.toml** |
| `init-service` | **`init-service`** | Оркестратор онбординга форка. Этапы: домены/флоу-вход → `stack-deep-dive` → `de-template` → `scaffold(dialog)`×N → prune reference-диалогов → `make check` |
| `de-template` | **`de-template`** | skill-only движок. Phase A: package name (`src/bot/` import-rewrite), README, `.env.example`, strip меты, **prune reference-диалогов** (`echo`/example main_menu). Phase B doc-driven wiring 6+ `Generates` (storage/middlewares/dialogs-router/setup_dialogs/observability/runtime). `prune.md`+`wiring.md` |
| `release` | **`release`** | **image-push, но один образ** (нет api+migrate lockstep — бот = один процесс). `make release VERSION=vX.Y.Z` → `docker buildx --push <host>/<org>/<bot>:<v>`, VERSION/GIT_SHA в бинарь. Агрегирует `**Infra impact.**`, печатает INFRA-HANDOFF (`backend_tag`→`bot_tag`). Pre-flight: main+clean+`make check` |

### 5.2. `scaffold` — варианты под бота

go-backend scaffold-роутер имел `domain/endpoint/event/migration/port`. У бота другие
строительные блоки (из `building-a-template.md` §1: `dialogs/<name>/{dialog,handlers,getters}.py`,
`states.py`, `middlewares/`, `services/`, `infrastructure/`). Предлагаемые варианты:

| Вариант | Reference | Что скаффолдит | Сигналы |
|---|---|---|---|
| **dialog** | `references/dialog.md` | Пакет `dialogs/<name>/` (`dialog.py`=Dialog(Window…), `handlers.py`, `getters.py`, `__init__.py`) + `StatesGroup` в общий `states.py` + include в `dialog_router`. Инварианты: getter `**kwargs`+дефолты, `id` ASCII≤валидатор, `LaunchMode`/`StartMode`-выбор | «добавь диалог/экран/меню», «новый flow профиля» |
| **window** | `references/window.md` | Добавить `Window(state=…)` в существующий Dialog (новое состояние в StatesGroup, виджеты, getter, `SwitchTo`/`Next`/`Back`) | «добавь шаг в диалог», «новый экран в настройках» |
| **backend-port** | `references/backend-port.md` | Порт к внешнему бэкенду: интерфейс в `services/`, реализация через `pylibinfra/httpclient` (retry/circuit-breaker), инжект через middleware-data/dishka. Бот-аналог go-port: изоляция «диалог не знает про HTTP» | «диалогу нужны данные из API X», «дёрни бэкенд Y», «сделай сервис-обёртку» |
| **middleware** | `references/middleware.md` | `BaseMiddleware` (auth/i18n/throttling/db-session/services) + регистрация на `message`+`callback_query`+**`DIALOG_EVENT_NAME`** (иначе фон не видит) | «добавь auth-middleware», «прокинь сессию», «i18n» |
| **job** | `references/job.md` | Фоновая периодика (asyncio task в lifecycle) + при необходимости рассылка через **`BgManager`** (`bg_factory.bg(...)`, не sync) | «по расписанию делать X», «фоновая задача», «cleanup» |
| **notification** | `references/notification.md` | Реактивный фон: webhook/событие из бэкенда → `BgManager.start/update` в чат пользователя. Идемпотентность + адресация (stack_id!), `bg.fg()` короткий | «при событии в бэкенде слать юзеру», «push-уведомление», «обнови сообщение из вне» |

Общий ритм scaffold-роутера сохраняется (подтвердить вход → правка → тесты RED→GREEN через
`BotClient` → `make check`/`pytest` → Conventional Commit + INFRA-HANDOFF при поверхности).

### 5.3. `stack-deep-dive` — бот-артефакты

Тот же AskUserQuestion-движок, 3 режима, `state/<kind>.md`, контракт `draft→stable` с непустым
`Generates`, cross-kind sync. **Меняется набор kinds** под бот-платформу (не 8 backend-овых):

| bot-kind | Чем владеет (из architecture.md/building-a-template.md) |
|---|---|
| **service** | имя бота, package path `src/bot/`, версионирование (ldflags-аналог: VERSION в образ), бинарь |
| **runtime** | entrypoints: polling vs webhook; lifecycle (Bot/Dispatcher/setup_dialogs ПОСЛЕДНИМ); graceful shutdown; jobs |
| **storage** | **критичный для бота** — Redis FSM-storage (не Memory!), JSON-сериализуемость dialog_data, `RedisEventIsolation` при ≥2 воркерах |
| **dialogs** | карта диалогов/StatesGroup, корневой `LaunchMode.ROOT`, `/start`→`RESET_STACK`, error-handlers UnknownIntent/UnknownState |
| **backends** | внешние API/вебхуки, к которым бот фронт: base-URL, auth, retry/circuit-breaker, режим отказа |
| **config** (роллап) | required/optional env (`BOT_TOKEN`, `REDIS_*`, backend-URL), секреты (Vault-ключи), pydantic-settings |
| **auth** | кто и что может (RBAC на диалоги, access_settings стека, admin-команды), authnkit если нужен |
| **observability** | telemetry mode (stdout dev/OTLP prod), biz-метрики `biz_bot_<event>_*`, trace-points (update→dialog→backend), логирование UnknownIntent всплесков |
| **dependencies** | подключённые `pylibinfra`-kit'ы, что НЕ подключено, внешние deps (Redis/Telegram API), capacity |
| **i18n** (опц.) | Fluent/gettext, локали, middleware на message+callback+DIALOG_EVENT |

### 5.4. НОВЫЕ скиллы, нужные именно боту

Эти не имеют 1:1 go-аналога — диктуются спецификой aiogram_dialog:

| Новый скилл | Назначение | Триггер | Почему именно боту |
|---|---|---|---|
| **dialog-deep-dive** | UX-проектирование флоу: дерево диалогов/окон/переходов/getter-контрактов как **source of truth ДО кода** (бот-аналог `domain-deep-dive`). AskUserQuestion-интервьюер, `state/`-память | «спроектируем флоу», «нарисуем диалоги бота» | У бота «домен» — это **диалог-флоу**; навигация по стеку (StartMode/LaunchMode/sub-dialogs) — нетривиальный дизайн, который дешевле спроектировать, чем переписывать |
| **state-migration** | Безопасная миграция `StatesGroup`/`State`: deprecated-пометки, версионирование имён групп, проверка живых контекстов, обязательные error-handlers как сеть | «переименовать состояние», «удалить экран», «деплой ломает кнопки» | Уникальная боль aiogram_dialog: после деплоя у юзеров живые сообщения со старыми callback → `UnknownIntent/UnknownState` (building-a-template §5). Это **forward-only-чувствительный** аналог `sqlc-and-migrations`-дисциплины, но про FSM |
| **preview-flow** | Сгенерировать/проверить превью диалогов и граф переходов (`aiogram_dialog.tools` — **только dev**), smoke `dp.emit_startup()` | «покажи граф переходов», «preview диалога», «проверь старт» | Бот-специфичная верификация: коллизии StatesGroup и незарегистрированные диалоги всплывают только на startup. Дешёвый CI-gate без реального Telegram |

### 5.5. Bot-rules (path-scoped) — предлагаемые

Зеркалят go-rules, но под Python/aiogram. Ключевые:

| bot-rule | `paths:` | Роль |
|---|---|---|
| `forward-only` | `**/*.md` | 1:1 |
| `comments` | `**/*.py` | WHY-only (как pylibinfra, но `.py`) |
| `dialog-architecture` | `src/bot/dialogs/**` | Раскладка `dialog.py`/`handlers.py`/`getters.py`, getter `**kwargs`+дефолты, `id` ASCII, окно читается как разметка, бизнес-логика в `services/` не в handler |
| `storage-serialization` | `src/bot/dialogs/**`, `src/bot/infrastructure/storage*` | Только JSON-примитивы в dialog_data/widget_data/start_data/result; datetime→ISO; Redis не Memory; RedisEventIsolation при ≥2 воркерах |
| `state-lifecycle` | `src/bot/dialogs/states.py`, `**/dialog.py` | States в едином `states.py` (разрыв циклов), error-handlers обязательны, не удалять State без миграции (→ skill `state-migration`) |
| `background-updates` | `**/handlers.py`, `**/*notification*`, `**/*job*` | BgManager для всего вне хендлера (не sync), middleware на DIALOG_EVENT_NAME, `bg.fg()` короткий, идемпотентность фоновых |
| `infra-impact` | `.env.example`, `config.py`, `pyproject.toml`, webhook/storage-wiring | INFRA-HANDOFF при env/секрет/Redis/backend-URL/новой deps |
| `env-local` | `.env.local`, `scripts/tools/logs.sh` | 1:1 — токен только через tools |
| `tests-pipeline` | `tests/**`, `conftest.py` | `BotClient`+`MockMessageManager`+`JsonMemoryStorage`, локаторы `fullmatch`, `reset_history()`, smoke `emit_startup` |

### 5.6. agents и settings.json

- **agents** (`explorer`, `reviewer`) — переносятся 1:1 (read-only, model sonnet, сжатая сводка).
  `reviewer`-чеклист адаптировать: вместо «транзакция+outbox» — «storage-сериализуемость,
  getter `**kwargs`, error-handlers, BgManager не sync, id виджетов ASCII».
- **settings.json** — каркас тот же. `allow`: `make test/lint/check`, `uv run ruff/mypy/pytest`,
  `docker buildx*`, `rg/grep/find`, read-only git. `deny`: `*--no-verify*`, force-push,
  `reset --hard`, `rm -rf *`, `Read/Edit(*.pem|*.key)`, запись в generated (если есть) и в
  `**/memory/**`. **Hooks — так же не заводить**; критичное на git-хуках (commit-msg + pre-push
  `make check`) + `permissions.deny`. `autoMemoryEnabled: false`.

---

## 6. Ключевые решения (для проектирования бот-системы)

1. **Сохранить весь каркас go-backend-системы** (CLAUDE.md ядро+роутер ≤200 строк ·
   smartdev-cockpit с `make status`-детектом + дочитыванием прозы · planning-first в едином
   forward-only `roadmap.md` · init-service→stack-deep-dive→de-template→scaffold цепочка ·
   двухуровневая защита git-хуки+deny, hooks НЕ заводить · INFRA-HANDOFF дисциплина) — он
   стек-агностичен и проверен.

2. **`scaffold` переосмыслить под блоки aiogram_dialog**: `dialog/window/backend-port/middleware/
   job/notification` вместо `domain/endpoint/event/migration/port`. `backend-port` — прямой
   идейный наследник go-`port` (изоляция «диалог не знает про HTTP», как «домен не импортит домен»).

3. **3 НОВЫХ бот-специфичных скилла** под уникальные боли aiogram_dialog: **`dialog-deep-dive`**
   (флоу как source-of-truth ДО кода, аналог domain-deep-dive), **`state-migration`** (безопасная
   эволюция StatesGroup/State — иначе деплой ломает живые кнопки), **`preview-flow`** (граф
   переходов + smoke `emit_startup` как CI-gate).

4. **`stack-deep-dive` целиком переиспользуем как движок** (AskUserQuestion, 3 режима, state-память,
   `draft→stable` с непустым `Generates`, cross-kind sync), но **с бот-набором kinds**, где
   критичны **`storage`** (Redis+JSON-сериализуемость+изоляция) и **`dialogs`** (корень/RESET_STACK/
   error-handlers) — две вещи, без которых бот падает в проде на первом деплое.
