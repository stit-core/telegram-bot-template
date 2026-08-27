# Roadmap

Единственный артефакт планирования проекта — этот файл. Подпапок, `<slug>.md`, архивов и
changelog'ов нет: они расходятся с правдой и мешают.

**Planning-first.** Изменение идёт через план — секцию в `## Active` ниже. Прямая правка без
плана допустима только для truly-atomic (опечатка, один очевидный файл) и багфиксов (→ skill
`/triage-failure`, RED-first). Отклонение от плана — осознанное и проговаривается с юзером.

**Жизненный цикл.** `planning → in-progress → blocked? → done`. По `done` секция задачи удаляется
целиком — история остаётся в `git log`. Незакрытый follow-up переезжает в `## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `CLAUDE.md`.

**Current focus:** none

## Active

## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `CLAUDE.md`.

**Current focus:** none

## Active

### harden-http-boundary — строгая HTTP-граница шаблона
**Создан:** 2026-08-27 · **Статус:** in-progress (все атомы закрыты, финальный прогон)

**Контекст.** Довести шаблон до планки go-канона (см. `go-backend-template`: strict gate, depguard-
зонтик, канон ошибок/тестов), не переворачивая архитектуру. Слабости сняты разведкой: booking/
payments ловят только `UnavailableError` (404/409 улетают в recovery как generic crash); user-тексты
ошибок в трёх слоях и мимо i18n; import-linter уже, чем декларируют доки (`ports`/`errors`/`views`
вне «чистого ядра», сырой `httpx` в фичах не запрещён, обход pkg не запрещён); wire-модели глотают
дрейф (`extra="ignore"` + бизнес-дефолты `currency="XTR"`/`premium=False`); `FakeApiClient` без
`put`/`delete` на трёх `type: ignore`, mypy не смотрит tests; `ApiClients.get()` падает лениво на
первом юзере; три конвенции idempotency-key; пин pylibinfra v0.3.0 (v0.5.1 нёс фикс изоляции
событий диалогов); ретраи/breaker не покрыты ни одним тестом (`max_retries=0` в conftest).

**Не входит в скоуп.** Codegen клиентов из OpenAPI — отклонено юзером (wire-схемы пишем руками, без лишних зависимостей); AST-archtest (границы закрывают
import-linter/ruff/mypy); prune `is_first_time`/`adapters.py` (остаётся единственным reference-
примером cross-feature адаптера); e2e-harness поверх реального стека; правки дизайна диалогов.

**Открытые вопросы.**
- [x] Q1: фасад pkg — да: фичи импортируют только `bot.pkg.http_client` (клиенты, ошибки,
  wire-модели), прямой `pylibinfra.httpclient` в фичах форбидится линтером.
- [x] Q2: i18n error-текстов — в этот план (`error_text` → `.ftl`-ключи ru/en).
- [x] Q3: coverage-пол — в `make check`, ratchet от замера, scope с WHY-комментом.
- [x] Q4: тег pylibinfra v0.6.0 — разрешён (Q2 kit-плана), A13 разблокирован.

**Атомы.**

#### Phase 1 — kit v0.6 в шаблоне
- [x] **A1:** `[tool.uv.sources]` rev `v0.3.0` → `v0.6.0` (тег на remote); `uv lock && make sync`;
  импорты/старт зелёные на новом ките.
  - Verify: `make test` → PASS · Зависит от: —
- [x] **A2:** Аудит natskit v0.4 (`!`: dedup/DLQ/dead-letter) на `notifications`/`tgbotkit`-пути
  шаблона; адаптация подписчика при изменении API; интеграционные тесты редоставки.
  - Verify: `make test-integration` → PASS (Docker) · Зависит от: A1

#### Phase 2 — pkg-канон
- [x] **A3:** Фасад pkg: `errors.py` (реэкспорт таксономии кита), `wire.py` (база wire-моделей:
  `extra="forbid"`, `frozen=True`), `idempotency.py` (канон-хелпер sha256/ASCII); `internal/codec.py`
  удалён (декод через `model=`); клиенты на `model=` + база wire; бизнес-дефолты из wire-моделей
  убраны (`currency`, `premium` — обязательные поля).
  - Verify: `uv run pytest tests/pkg tests/unit` → PASS · Зависит от: A1
- [x] **A4:** Идемпотентность-канон: все три клиента считают ключ сами (`idempotency.key(...)`
  от доменных id), respx-тесты формата/ASCII; `BookingAPI` перестаёт требовать ключ kwarg'ом.
  - Verify: `uv run pytest tests/pkg` → PASS · Зависит от: A3
- [x] **A5:** `JsonApi`-Protocol в pkg (типизированная поверхность `ApiClient`); клиенты зависят
  от Protocol; `FakeApiClient` реализует его целиком (`put`/`delete`, `post_error`, payload
  per-path) — ноль `type: ignore` в harness.
  - Verify: `uv run mypy src tests` → clean на затронутом; `make test` → PASS · Зависит от: A3
- [x] **A6:** Негативный канон tests/pkg: transport→`UnavailableError`, 429→`RateLimitedError`
  (+`retry_after`), 401→`AuthError`, 5xx с `max_retries>0` → ретраи→`UnavailableError`, POST без
  ключа = одна попытка; маркер `pkg` в pyproject + файлах.
  - Verify: `uv run pytest tests/pkg -m pkg` → PASS · Зависит от: A3

#### Phase 3 — канон фич
- [x] **A7:** Usecase-канон таксономии: единый шаблон маппинга `ApiError`→sentinel во всех трёх
  HTTP-фичах (404/409 → доменные, остальной `ApiError` → `*Unavailable`); `payments/errors.py`
  получает `PaymentUnavailable`; sentinel'ы не несут user-текст.
  - Verify: `uv run pytest tests/unit tests/flows` → PASS · Зависит от: A3
- [x] **A8:** Текст только в views + i18n: `views.error_text` — единственный источник user-текста
  ошибок, отдаёт `.ftl`-ключ; локали ru/en пополнены; payments получает `views.error_text`;
  flow-тесты на ключах.
  - Verify: `make test` → PASS · Зависит от: A7
- [x] **A9:** Fail-fast composition: тест резолвит из контейнера все pkg-API и все фичевые порты
  (+ smoke `setup_dialogs`, если не покрыт) — неконфигурённый бэкенд падает тестом, не первым юзером.
  - Verify: `uv run pytest tests/flows/test_composition.py` → PASS · Зависит от: A1

#### Phase 4 — enforcement
- [x] **A10:** import-linter: «чистое ядро» расширено на `ports`/`errors`/`views`; новые контракты —
  `httpx` запрещён в `features`/`platform` (транспорт только в pkg); `pylibinfra.httpclient`
  запрещён вне `bot.pkg` (фасад — Q1); `handlers`/`getters`/`dialogs` не импортят `bot.pkg`
  (данные — через usecase).
  - Verify: `make lint` → PASS · Зависит от: A3, A7
- [x] **A11:** ruff/mypy строже: ruff floor `>=0.16` + добор правил (DTZ, PGH, A, ISC, RSE, SLF,
  ERA, PERF, FURB — tune по прогону); mypy покрывает `tests` (Makefile `mypy src tests`),
  `warn_unreachable`, `extra_checks`, `enable_error_code=[ignore-without-code, ...]`; всплывшее — чинить.
  - Verify: `make check` → OK · Зависит от: A5
- [x] **A12:** Гейт: `make check` += `uv lock --check` (дрейф лока) и coverage-пол
  (`--cov-fail-under`, ratchet от замера, WHY-коммент scope); `.claude/settings.json`
  `permissions.deny`: `--no-verify`, `git push --force*`, `git reset --hard*`, `Edit(.env*)`,
  `Edit(uv.lock)`, `Read(**/*.key|*.pem)`.
  - Verify: `make check` → OK · Зависит от: A11
- [x] **A13:** `.env.example` — `HTTPCLIENT_BREAKER_NAME` удалён, формат `HTTPCLIENT_BACKENDS`
  с обязательным per-backend `base_url`; INFRA-HANDOFF-блок актуализирован.
  - Verify: `make check` → OK · Зависит от: A12
- [x] **A14:** Доки-синк (forward-only): CLAUDE.md (фасад pkg — одна дверь, таксономия, версии),
  rules `feature-architecture`/`tests-pipeline`, `docs/reference/architecture.md`,
  `.claude/skills/scaffold/references/backend-port.md`, `docs/stack/_templates/backends.md`.
  - Verify: `make plan-check` + `make status` → OK · Зависит от: A7, A10
- [x] **A15:** Полный прогон: `make check` + `make test-integration`; чекпоинт-фиксация.
  - Verify: `make check` → OK; `make test-integration` → PASS · Зависит от: A13, A14

**Infra impact.**
- WHAT: runtime-dep пин `pylibinfra` v0.3.0 → v0.6.0 · WHY: строгий httpclient + фикс
  `RedisEventIsolation` (v0.5.1, критичен для диалогов) · ACTION: пересборка образа в следующий
  релиз · WHO: инфра-админ · RISK: natskit v0.4 (dedup/DLQ) может потребовать пересоздания
  NATS-consumer'ов — уточняется в A2.
- WHAT: `.env.example` — удалён `HTTPCLIENT_BREAKER_NAME`; `HTTPCLIENT_BACKENDS` теперь требует
  per-backend `base_url` · WHY: env-bleed слал трафик не туда, breaker-name схлопывал метрики ·
  ACTION: привести env на VPS при rollout · WHO: инфра-админ · RISK: отсутствующий `base_url`
  валит старт (задуманный fail-fast).

**Чекпоинты.**
- **2026-08-27 · Все атомы закрыты.**
  - Закрыто: A1–A15 ✓ (пин v0.6.0 + aiogram 3.31; natskit v0.4 адаптирован, integration 4 passed;
    pkg-фасад errors/wire/idempotency/api + клиенты на model=; канон таксономии и .ftl-ключей в
    трёх фичах; полный FakeApiClient без type: ignore; fail-fast composition; 7 контрактов +
    banned-api дверь; mypy src+tests clean; make check: lock-check + cover-floor 85 (факт 90.6),
    108 passed).
  - Следующий шаг: коммит, закрытие секции (infra-impact → Backlog до release).
- **2026-08-27 · Кит выпущен раньше шаблона.**
  - Закрыто: план rework-httpclient-kit целиком (pylibinfra v0.6.0: 630eab6 + 821812f, тег
    запушен; gate кита зелёный: ruff/mypy src/359 unit) — секция удалена по канону.
  - Переоценил: path-override не нужен — A1 пинит rev v0.6.0 сразу; A13 сжат до env/handoff.
  - Следующий шаг: A1.

## Backlog

- INFRA-HANDOFF (не сдан — агрегировать в ближайший `make release`): (1) runtime-dep пин
  `pylibinfra` v0.3.0 → v0.6.0 — пересборка образа; natskit v0.4 сменил env-ручки:
  `NATS_JS_DLQ_ENABLED`/`NATS_JS_FLOW_CONTROL`/`NATS_JS_IDLE_HEARTBEAT` удалены, DLQ теперь
  `NATS_JS_DLQ_SUBJECT`, backoff — `NATS_JS_NAK_BACKOFF` (сек). (2) `HTTPCLIENT_BREAKER_NAME`
  удалён (имя breaker'а = имя бэкенда, только код); `HTTPCLIENT_BASE_URL` обязателен — пустой
  валит старт (задуманный fail-fast); `HTTPCLIENT_BACKENDS` требует per-backend `base_url`.
- Двойные HTTP-спаны httpclient (ручной span + `HTTPXClientInstrumentor`) — проверить на живом
  стеке, при подтверждении убрать ручной.
- Auth-hook httpclient сверх статических per-backend `headers` (токен-провайдер per-call).
