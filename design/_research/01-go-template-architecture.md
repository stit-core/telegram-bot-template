# 01 · Архитектура `go-backend-template` — разбор для зеркалирования на бот

Design-input артефакт зоны A. Цель — дотошно зафиксировать раскладку слоёв, ports/adapters,
fx-композицию, границу с `golibinfra`, генерацию и тесты в эталонном Go-бэкенде, и в конце дать
**маппинг на aiogram-бот** (потребитель `pylibinfra`). Все пути — реальные, из
`/root/git/sftbmb/sftbmb-core/go-backend-template/`.

Источники-якоря: `docs/reference/architecture.md`, `docs/reference/domain-mapping.md`,
`.claude/rules/{domain-architecture,events-and-messaging,sqlc-and-migrations,tests-pipeline,infra-impact}.md`,
домены `internal/domain/{auth,user,verification}/`, `cmd/{api,migrate,seed-admin}/main.go`,
`.claude/skills/scaffold/references/{domain,port,event,endpoint}.md`, `.claude/skills/de-template/`.

---

## 1. Карта раскладки домена со слоями и их ответственностью

Каждый домен — изолированный bounded context в `internal/domain/<name>/`. Канон раскладки —
`docs/reference/architecture.md` (строки 8–22) и инвариант в
`.claude/rules/domain-architecture.md` (строки 15–17). Реальный полный набор файлов на примере
`auth`:

| Файл | Ответственность | Чистота (I/O?) | Пример |
|---|---|---|---|
| `entity.go` | Доменные типы-агрегаты, pure-методы без I/O, конструкторы с валидацией | **Чистый** | `auth/entity.go` (`User`, `RefreshSession`); `user/entity.go` (`NewUser` валидирует email/role, `func (u *User) CanLogin() bool`) |
| `dto.go` | Input/Output типы use-case (НЕ HTTP-DTO) | Чистый | `auth/dto.go` (`LoginInput`/`LoginOutput`; `type LockState = bruteforcekit.LockState` — alias, чтобы kit структурно удовлетворял порту) |
| `errors.go` | Sentinel-ошибки `var ErrX = errors.New("auth: ...")` | Чистый | `auth/errors.go` (`ErrInvalidCredentials`, `ErrRefreshReused`, …) |
| `policy.go` | Authorization — решения **без I/O**, возвращают `policy.Decision` | **Чистый** | `auth/policy.go` (`CanChangePassword` → admin или self) |
| `usecase.go` | Бизнес-логика; **объявляет порты-интерфейсы**; зависимости только через них; здесь весь I/O (repo/сеть/время) | **I/O-оркестратор** (сам чистый от деталей) | `auth/usecase.go` — `Login`/`Refresh`/`Logout`/`ChangePassword` |
| `events.go` | Outbox-payload типы (поля события) | Чистый | `verification/events.go` (`EmailVerificationRequested`, `PasswordResetRequested`); `user/events.go` (`UserRegistered`) |
| `metrics.go` | Бизнес-счётчики через `bizmetric.Counter`; все `Record*` **nil-safe** (no-op без DI) | I/O (OTel) | `auth/metrics.go` (`biz_auth_login_attempts_total{result=...}`) |
| `delivery/http/{handler,dto,view}.go` | HTTP-вход: huma/v2+chi; `handler.go` парсит вход→зовёт usecase→мапит ошибки; `dto.go` huma-теги; `view.go` mapping entity→ответ | I/O (транспорт) | `auth/delivery/http/handler.go` |
| `delivery/nats/{handler,dto}.go` | NATS-subscriber (опц.) — **равноправный вход в usecase**; локальный payload-DTO | I/O (транспорт) | `verification/delivery/nats/handler.go` |
| `infra/postgres/{repository,queries/*.sql,db/}` | Реализация порта `Repository`; `queries/*.sql` пишутся руками, `db/` — sqlc-генерат (не править) | I/O (БД) | `auth/infra/postgres/repository.go` + `queries/refresh_sessions.sql` |
| `module/{module,adapters}.go` | fx-wiring домена (`module.go`) + cross-domain адаптеры (`adapters.go`) | Композиция | `auth/module/module.go`, `auth/module/adapters.go` |
| `*_test.go`, `mocks/` | Юнит-тесты рядом с кодом; `mocks/` — генерат mockery | — | `auth/usecase_test.go`, `auth/mocks/*` |

**Ключевые инварианты раскладки** (`.claude/rules/domain-architecture.md`):

- **«I/O — это use-case, не метод агрегата.»** Нужен repo/сеть/время → метод `*Usecase`. Чистое
  правило → `policy.go`. Pure-метод на агрегате → `entity.go` (строки 23–24 правила). Таблица
  «ступоров» в `docs/reference/domain-mapping.md` (строки 148–161): уникальность по полю → use-case
  (нужен `repo.GetBy*`), не invariant агрегата; `CreatedAt` ставит репозиторий, не конструктор.
- **Логи — только `logkit.Logger`** (не `fmt.Print*`/`slog.*` — forbidigo), строка 25 правила.
- **HTTP-DTO — domain-specific имена.** huma собирает все DTO в одну OpenAPI registry по имени
  Go-типа; два `ListOutput` → panic. Префиксуй: `EventListOutput`, не `ListOutput`
  (`architecture.md` строки 43–49). Inline `Body struct{...}` именуется по Outer-типу.
- Usecase ведёт телеметрию сам: каждый метод оборачивается `ctx, end := telemetry.Span(ctx, "auth.usecase.login"); defer end(&err)` (`auth/usecase.go:127`).

**Композиция usecase** (`auth/usecase.go:71–124`): зависимости приходят как `UsecaseDeps struct{ fx.In; ... }`
(fx-инъекция по полям), `NewUsecase(d UsecaseDeps)` копирует их в приватную struct `Usecase` и
навешивает `log.With("domain","auth")`. Это разделяет «как fx собирает» (публичный `Deps` с тегом)
и «что хранит usecase» (приватные поля).

---

## 2. Ports & adapters механика

Это центральная конвенция. Источник правды — `architecture.md` (строки 35–41), правило
`domain-architecture.md` (строки 18–20), процедура — `scaffold/references/port.md`.

**Правило депенденси-инверсии:** depguard в `.golangci.yml` блокирует прямые импорты между
бизнес-доменами (`auth ↛ user`). Когда домену A нужны данные B:

1. **Порт объявляется в домене-потребителе A**, прямо в `usecase.go` как Go-interface. Владелец
   контракта — потребитель. Пример: `auth` нужен user — порт `UserReader` живёт в
   `auth/usecase.go:24` (`GetByID`/`GetByEmail` → `*auth.User`). Порт **сужен** до минимума
   (`scaffold/references/port.md` шаг 2 — «не копируй весь Repository»).
2. **DTO в порте — локальные типы потребителя**, не re-export провайдера. `auth.User`
   (`auth/entity.go:9`) — это свой тип с нужными 3–7 полями, НЕ `*user.User`.
3. **Адаптер объявляется в `A/module/adapters.go`** — он единственный, кому depguard разрешает
   импортить домен-провайдера B (пути `module/**` исключены из depguard). Пример:
   `auth/module/adapters.go:16` — `userReaderAdapter{uc *user.Usecase}` оборачивает
   `user.Usecase.LookupByID`, и `userToAuth(u *user.User) *auth.User` (строка 36) маппит
   provider-тип → consumer-DTO.
4. **Адаптер регистрируется в `A/module/module.go`** как fx-провайдер:
   `func(uc *user.Usecase) auth.UserReader { return &userReaderAdapter{uc: uc} }`
   (`auth/module/module.go:37`).

**Виды адаптеров** (всё — порт+адаптер, единый паттерн):

- **Cross-domain через usecase-метод.** Иногда адаптер не нужен — провайдер сам структурно
  удовлетворяет порту: `func(uc *user.Usecase) auth.PasswordVerifier { return uc }`
  (`auth/module/module.go:18`) — `user.Usecase` имеет `VerifyPassword`/`UpdatePassword`
  (`user/usecase.go:311,316`), которые маппятся на порты `auth.PasswordVerifier`/`PasswordSetter`.
  «Lookup-методы без проверки policy — нормальная практика для cross-domain» (`port.md` шаг 5).
- **Адаптер над kit'ом.** Порт `auth.Tokens`/`auth.TokenParser` (`auth/usecase.go:37,42`) →
  адаптеры `tokensAdapter`/`tokenParserAdapter` над `authnkit.JWTSigner`/`JWTParser`
  (`auth/module/adapters.go:48,77`). Порт `auth.LoginGuard` структурно удовлетворяется
  `bruteforcekit.Guard` напрямую: `func(g bruteforcekit.Guard) auth.LoginGuard { return g }`.
- **Адаптер над внешним сервисом.** Порт `verification.Mailer` (`verification/usecase.go:44`) →
  `logMailerAdapter` (`verification/module/adapters.go:42`) — заглушка, которая логирует и пишет
  audit; в проде заменяется реальным mailer.

**Антипаттерны** (`port.md`): возврат типа провайдера из адаптера; широкий порт «на вырост»;
двусторонняя A↔B зависимость (сигнал кривых границ); адаптер в корне домена вместо `module/`;
`//nolint:depguard` вместо порта.

---

## 3. Композиция приложения (cmd + fx + lifecycle)

**Один бинарь `cmd/api`** держит всё: HTTP, outbox-drain, NATS-subscribers, background jobs —
через одну `fx.Lifecycle` (`architecture.md:52–53`). Отдельного worker-процесса нет.

`cmd/api/main.go` собирает приложение из **трёх ярусов fx.Options** (строки 51–88):

- `infraModules` (строки 52–63) — kit-модули `golibinfra`: `config.Module`, `kitConfigs`
  (провайдеры `*.NewConfig`), `logkit.Module`, `telemetry.Module`, `pgkit.Module`,
  `httpkit.Module`, `natskit.Module`, `cachekit.Module`, `flagkit.Module`, `timerkit.Module`.
- `platformModules` (строки 65–81) — платформа этого репо + kit-store-модули: `appconfig.Module`,
  `authgate.Module`, `authnkit.Module`, `bruteforcepg.Module`, `auditpg.Module`, `clockkit.Module`,
  `outboxkit.Module`+`outboxpg.Module`; плюс `fx.Provide` health-probe'ов и jobs в **fx-группы**
  (`fx.Annotate(pgkit.DBProbe, fx.ResultTags(`group:"health"`))`,
  `fx.Annotate(jobs.NewBruteforceCleanup, fx.ResultTags(`group:"timer.job"`))`).
- `domainModules` (строки 83–88) — `usermod.Module`, `authmod.Module`, `verifmod.Module`.

`main()` (строки 95–104): `fx.New(infra, platform, domain, fx.Invoke(...log "starting"...)).Run()`.
`version`/`commit` — link-time переменные (`-ldflags`).

**Структура fx-модуля домена** (`user/module/module.go`, эталон): `fx.Module("user",
fx.Provide(repo, policy-через-fx.Annotate(...fx.As(new(Authorizer))), metrics, usecase,
http.NewHandler, func(u *Usecase) http.Usecase {return u}), fx.Invoke(http.Register))`.
Паттерн: provide все слои + узкий адаптер usecase→`delivery.Usecase` + `fx.Invoke(Register)`
регистрирует роуты/подписки в lifecycle. Verification дополнительно `fx.Invoke(verifnats.Register)`
(`verification/module/module.go:29`).

**Lifecycle для подписок/jobs.** NATS-subscriber регистрируется через `fx.Hook{OnStart, OnStop}`
(`verification/delivery/nats/handler.go:37–51`): `OnStart` зовёт `natskit.SubscribeJSON(bus, ctx,
SubjectUserRegistered, h.onUserRegistered)`, `OnStop` — `cancel()`. Job — это `timerkit.Job{Name,
Interval, Run}` (`jobs/bruteforce.go:11`), отдаётся в группу `timer.job`, поднимается timerkit'ом.

**One-off бинари** (`cmd/migrate`, `cmd/seed-admin`) — **без fx**, прямой `main()`: инициализируют
telemetry вручную, `os.Exit(run(...))` с явным telemetry-shutdown до Exit (`cmd/migrate/main.go:51–55`,
комментарий поясняет почему — `os.Exit` обходит defer). `cmd/migrate` накатывает миграции из
**нескольких источников append-only**: kit-миграции (`bruteforcekit`/`auditkit`/`outboxkit`
`MigrationsFS`) + `app` в конце, чтобы не сдвигать версии (`cmd/migrate/main.go:103–111`).
`cmd/seed-admin` — идемпотентный upsert первого admin (нет публичного пути сделать admin).

---

## 4. Граница с `golibinfra`

Источник — `architecture.md § Граница с golibinfra` (строки 73–80), `ecosystem.md`,
правило в CLAUDE.md § Стиль кода.

- **Что в `golibinfra`:** переиспользуемое/инфраструктурное — generic util, HTTP-client,
  middleware, kit-подобный примитив. «Не плодить полукалеки здесь.» Нет нужного примитива → **PR в
  golibinfra + строка в roadmap-backlog**; временный shim — только с явным OK юзера.
- **Что в этом репо:** доменная/продуктовая логика. Шаблон — **тонкий слой над платформой**;
  улучшения едут всем сервисам сразу.
- **Как kit'ы попадают в код:** только через DI (fx-модули в `cmd/api`) и порты. Usecase
  импортит kit-интерфейсы напрямую как зависимости (`pgkit.Transactor`, `outboxkit.Publisher`,
  `auditkit.Logger`, `clockkit.Clock`, `authnkit.Hasher`, `logkit.Logger` — `auth/usecase.go:13–19`),
  но детали (драйвер БД, JWT-подпись) спрятаны за kit-фасадами. Бизнес-домен **не знает** про
  asyncpg/pgx, NATS-клиент, OTel-SDK — только про интерфейсы kit'ов.
- **Kit-owned таблицы** (`outbox`/`audit_log`/`bruteforce_*`) — схему держит kit (`MigrationsFS`),
  НЕ `migrations/` репо. Не дублировать `CREATE TABLE` (`events-and-messaging.md:40–42`,
  `sqlc-and-migrations.md:41–43`).
- **Инфра-граница деплоя:** репо STOP'ает на image-in-registry. Любое изменение инфра-поверхности
  (env/секрет/миграция-с-эффектом/cross-service-subject/новый порт/`go.mod`) → обязательный
  **INFRA-HANDOFF-блок** до claim «готово»/коммита (`infra-impact.md`).

**Платформенный слой репо** (`internal/platform/`) — то, что специфично проекту, но не домен:
`identity/` (контекстный principal: `Identity{UserID, Role}`, `identity.With/From(ctx)`,
`IPFrom(ctx)` — `identity/identity.go`); `authgate/` (JWT-cookie extractor → кладёт `identity` в
ctx, huma security scheme, log-attr — `authgate/{jwt,module,cookie}.go`); `config/` (`App`-struct
+ `config.Load`, раздаёт под-конфиги kit'ам через fx — `config/config.go`). `pkg/` — мелкие
переиспользуемые pure-утилиты репо вне `internal`: `pkg/policy` (`Decision`/`Allow`/`Deny`),
`pkg/tokens` (`Generate`/`Hash` opaque-токенов).

---

## 5. Генерация и тесты

**Генерация кода** (`sqlc-and-migrations.md`, `tests-pipeline.md`, `.mockery.yml`):

- **sqlc** — `queries/*.sql` пишутся руками с аннотацией `-- name: <Method> :<one|many|exec|execrows>`
  (`auth/.../queries/refresh_sessions.sql`); `db/` — генерат, **никогда руками**, только `make gen`.
  `:one` пусто → `pgx.ErrNoRows`, репозиторий маппит на sentinel (`auth/.../repository.go:48` —
  `pgkit.IsNoRows(err)` → `ErrSessionNotFound`). Optimistic lock через `version`: `WHERE id=$1 AND
  version=$2`, `:execrows`=0 → `ErrConflict`.
- **mockery v3** — `.mockery.yml` перечисляет интерфейсы-порты per-package; генерит
  `mocks/<interface_snake>.go` (пакет `mocks`, тип `Mock<Interface>`) рядом с интерфейсом. Template
  `testify` даёт `EXPECT()`-API. Изоляция (depguard `mocks-isolation`): `*/mocks` импортится только
  из `*_test.go`. Мокаются **только порты домена**, не `*pgxpool.Pool`.
- `make gen` регенерит sqlc+mocks; `make gen-check` (в `make check`) падает при дрейфе.

**Тесты** (`tests-pipeline.md`):

- `<file>_test.go` рядом с `<file>.go`; package `<pkg>_test` (black-box) или `<pkg>` (white-box).
- **Юниты** — через моки портов; иногда stateful in-memory fake вместо мока для проверки
  сайд-эффектов (`auth/usecase_test.go:26` — `memSessions` имплементит `SessionRepository`).
  `golibinfra/testkit/{audittest,authntest,txkit}` дают тестовые реализации kit-портов.
- **Интеграционные** — build-tag `//go:build integration`, поднимают реальный Postgres/NATS через
  testcontainers; `internal/testkit/pgseed.New(t)` — свежая БД+миграции+pool на тест,
  `internal/testkit/identitytest` — тестовые principal. `pgseed.NewUser(opts...)` — option-билдер
  фикстур (`pgseed/pgseed.go:22`).
- **TDD для багфиксов обязателен** (RED→GREEN, оба файла одним коммитом). Coverage CI-floor 60%.
- Анти-паттерны: мокать `*pgxpool.Pool`; тесты на sqlc-генерат; `time.Now()` в коде (инжектить
  `clockkit.Clock`).

**Скаффолдинг** управляется skill'ами (`.claude/skills/scaffold/`, роутер +
`references/{domain,endpoint,event,port,migration}.md`) — детерминированные процедуры добавления
блока с фиксированным «ритмом»: подтвердить вход → изменение → `make gen` → тесты RED→GREEN →
`make check` → Conventional Commit. `de-template` — разовое развёртывание форка (rewrite module
path, prune reference-доменов `auth/user/verification`, doc-driven wiring `cmd/api`).

---

## 6. Маппинг на бот (aiogram + aiogram_dialog + pylibinfra)

Бот — «фронтенд»: вся бизнес-логика на бэкендах (по API/вебхукам), у бота своё — только его
**state** (FSM/диалоги). `pylibinfra` зеркалит `golibinfra` (dishka-Provider'ы вместо fx-модулей,
async-first, OTel из коробки — `pylibinfra/README.md`). Зеркалим раскладку и правила, заменяя
«домен данных» на «фича-сценарий», а delivery — на aiogram-входы.

### 6.1 Слой за слоем: Go-домен → бот-фича

Предлагаемая раскладка `internal/features/<feature>/` (зеркало `internal/domain/<name>/`):

| Go-слой | Бот-аналог | Что внутри |
|---|---|---|
| `entity.go` (агрегат, pure) | `state.py` | **State диалога/сцены** — единственное «своё» у бота: dataclass/pydantic-модель `DialogData`, FSM-`StatesGroup`. Pure, без I/O. Это и есть «домен» бота. |
| `dto.go` | `dto.py` | Input/Output use-case фичи (доменные, не транспортные): что сценарий принимает из апдейта и отдаёт во вью. |
| `errors.py` | `errors.py` | Sentinel-ошибки фичи; маппинг на user-facing сообщения — в delivery (аналог `mapErr`). |
| `policy.go` (pure authz) | `policy.py` | Чистые решения «можно ли»: видимость кнопок/команд по роли из бэкенда, gate сценария. `Decision`-аналог. Без I/O. |
| `usecase.go` (логика+порты) | `usecase.py` / `service.py` | Оркестрация сценария: **объявляет порты** (Protocol) к бэкенду и инфре; вызывает их; ведёт span. Сам не знает про httpx/aiogram. |
| `events.go` | `events.py` (опц.) | Если бот публикует в outbox/NATS через `pylibinfra.outboxkit/natskit` — payload-типы здесь. |
| `metrics.go` (bizmetric) | `metrics.py` | `pylibinfra.bizmetric`-счётчики фичи (`biz_<feature>_*`), nil/no-op-safe. |
| `delivery/http/` | `delivery/handlers/` + `delivery/dialogs/` | **aiogram-роутеры** (Router, хэндлеры команд/callback) и **aiogram_dialog-диалоги** (Window/Dialog) — это «входы» в usecase, как HTTP-handler. Парсят апдейт → зовут usecase → рендерят вью. |
| `delivery/nats/` | `delivery/nats/` (опц.) | NATS-subscriber фичи, если бот реагирует на события бэкенда (push-уведомления юзеру) — равноправный вход в usecase. |
| `delivery/http/view.go` | `delivery/views.py` | Mapping результата usecase → текст/клавиатура/`getter` диалога (аналог `FromEntity`). |
| `infra/postgres/` | `infra/backend/client.py` | **Реализация порта = клиент бэкенда** (httpx через `pylibinfra.httpclient`: retry/CB/OTel/X-Request-ID). У бота нет своей бизнес-БД; «repository» = вызовы API бэкенда. State-storage FSM — через `pylibinfra` (Redis `cachekit`) как infra-адаптер. |
| `module/{module,adapters}.go` | `provider.py` (dishka) + `adapters.py` | dishka-`Provider` фичи: provide state-storage, backend-client-адаптер под порт, usecase, регистрация роутера/диалога. Cross-feature — порт в потребителе + адаптер здесь. |
| `mocks/`, `*_test.go` | `tests/` | Юниты через моки портов (бэкенд-клиент мокается — фича не ходит в сеть). `pylibinfra.testkit`. |

**Главный сдвиг семантики:** у бэкенда «домен» владеет данными (Postgres-агрегат); у бота
«фича» владеет только **состоянием диалога**, а данные — за портом к бэкенду. То есть `infra/` бота
— это **исходящий клиент**, а не хранилище. Pure-ядро бота (`state.py`+`policy.py`) тоньше, чем у
бэкенда, но принцип «I/O — в usecase, чистое — в policy/state» сохраняется 1:1.

### 6.2 Ports/adapters на боте

- **Порт к бэкенду** объявляется в `<feature>/usecase.py` как `typing.Protocol` (аналог Go-interface),
  **сужен** до нужных методов сценария; возвращает **локальные DTO фичи**, не сырые JSON-схемы
  бэкенда (anti-corruption — как `auth.User` вместо `user.User`). Реализация — `infra/backend/`
  поверх `pylibinfra.httpclient`, проводится dishka-провайдером.
- **Cross-feature** (фиче A нужны данные из фичи B, например общий «профиль юзера») — порт в A,
  адаптер в `A/provider.py`/`adapters.py`, оборачивающий usecase B. Прямой импорт фич между собой —
  избегать (можно сделать lint-границу, аналог depguard; но это soft-конвенция, не обязателен на
  старте). Чаще общий ресурс выносится в `internal/platform/` (общий backend-client, identity юзера).
- **Адаптеры над kit'ами** (`pylibinfra.cachekit` для FSM-storage, `httpclient`, `natskit`) —
  ровно как `tokensAdapter` над `authnkit`: kit спрятан за портом фичи.

### 6.3 Композиция приложения

- **Один процесс** (как `cmd/api`): `cmd/bot/main.py` (или `__main__`) собирает dishka-контейнер из
  ярусов провайдеров — `infra` (`pylibinfra` kit-Provider'ы: telemetry, httpclient, cachekit,
  natskit, timerkit), `platform` (identity-резолвер юзера, общий backend-client, config), `features`
  (per-feature `Provider` + регистрация роутеров/диалогов в `Dispatcher`). Это зеркало
  `infraModules/platformModules/domainModules` из `cmd/api/main.go:51–88`.
- **Lifecycle**: aiogram `Dispatcher.start_polling`/webhook + dishka `setup_dishka(container,
  dispatcher)`; фоновые задачи — через `pylibinfra.timerkit` (аналог `timer.job`-группы и
  `jobs/`); NATS-подписки — `OnStart/OnStop`-аналог в lifespan (как `fx.Hook` в
  `verification/delivery/nats/handler.go:37`). Регистрация роутера/диалога фичи = аналог
  `fx.Invoke(http.Register)`.
- **One-off бинари** (как `cmd/migrate`/`cmd/seed-admin`) у бота обычно не нужны (нет своей БД);
  если появятся (миграция Redis-схемы, seed) — отдельный `__main__` без dishka, прямой `main()`.

### 6.4 Граница с pylibinfra (что НЕ писать в шаблоне бота)

- Переиспользуемое/инфра (HTTP-client-обвязка, middleware, RequestID-проброс, FSM-storage-фасад,
  OTel) → **кандидат в `pylibinfra`**, не в бот. Нет примитива → PR в pylibinfra + backlog
  (зеркало правила `architecture.md:73–80`).
- Бот импортит kit-Provider'ы только через DI и kit-фасады; не знает про httpx/redis/nats-py
  напрямую — только про `httpclient.Client`/`cachekit.Cache`/`natskit.Bus`.
- `internal/platform/` бота: `identity/` (кто пользователь Telegram → принципал/роль с бэкенда,
  в контексте апдейта — зеркало `identity.With/From`), `config/` (`App`-конфиг + раздача под-конфигов
  kit'ам), `authgate`-аналог (резолв сессии юзера/токена бэкенда из апдейта). `pkg/`-аналог —
  мелкие pure-утилиты.

### 6.5 Генерация и тесты на боте

- **Нет sqlc** (нет своей БД). Аналог «контракта» — **типизированные клиенты/модели бэкенд-API**
  (pydantic-модели ответов; при наличии OpenAPI бэкенда — кодген клиента, тогда «не править руками»
  сохраняется как у `db/`).
- **Моки** — мокаются **порты к бэкенду** (Protocol), чтобы фича тестировалась без сети
  (зеркало «мокай Repository, не Pool»). aiogram-handler/диалог тестируется через
  `pylibinfra.testkit.handlertest`-аналог с моком usecase-порта (как `delivery/http` мокает
  `Usecase`). FSM-state — детерминируется, как `clockkit.Clock` вместо `time.Now()`.
- **Тесты рядом с кодом**, юниты на usecase/policy через моки портов; интеграционные (реальный
  бэкенд-стек/Redis/NATS) — отдельным маркером (аналог build-tag `integration`).
- **Skill-система** зеркалится: `scaffold` с вариантами `feature`/`handler`/`dialog`/`event`/`port`,
  правила `.claude/rules/*` (feature-architecture, events-and-messaging, tests-pipeline,
  infra-impact), `de-template` для развёртывания форка. INFRA-HANDOFF при изменении env/секрета/
  cross-service-subject сохраняется (`infra-impact.md`).

---

## Сухой остаток — что взять в шаблон бота

1. **Раскладка по слоям + инвариант «I/O в usecase, чистое в policy/state».** Файлы-роли
   `entity/dto/errors/policy/usecase/events/metrics/delivery/infra/module` зеркалятся на фичу; у
   бота `entity`→`state` (диалог), `infra`→backend-client.
2. **Ports&adapters через DI с anti-corruption DTO.** Порт (Protocol) в потребителе, адаптер в
   `provider.py`, локальные DTO — это и даёт «бот=фронтенд, логика за портом к бэкенду».
3. **Трёхъярусная композиция** `infra/platform/features` в одном процессе через dishka; lifecycle
   для polling/webhook, timerkit-jobs и NATS-подписок.
4. **Тонкость над `pylibinfra` + skill/rules-система + INFRA-HANDOFF** — переиспользуемое уходит в
   pylibinfra, конвенции enforce'ятся правилами и скаффолд-скиллами, а не толстым шаблоном.
