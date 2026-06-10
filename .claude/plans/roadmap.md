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
mypy + pytest). См. `.claude/CLAUDE.md`.

**Current focus:** активной задачи нет. Шаблон на архитектуре pkg/http_client + строгие handlers
(pylibinfra пин `b713602`).

## Active

## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `.claude/CLAUDE.md`.

**Current focus:** активной задачи нет. Шаблон на архитектуре pkg/http_client + строгие handlers
(pylibinfra пин `b713602`).

## Active

### flatten-template-architecture — pkg/http_client, строгие handlers, app.py как единый composition root
**Создан:** 2026-06-10 · **Статус:** in-progress

**Контекст.** Решения зафиксированы с пользователем (сессия 2026-06-10): (1) `src/bot/pkg/http_client/
{internal,external}` — полноценные API-клиенты (`ProfileAPI`/`BookingAPI`/`PaymentsAPI`, пути +
pydantic wire-модели) поверх kit-`ApiClient` имени `core` (один base_url — реальная топология);
`external/` — `.gitkeep`. (2) Порт фичи остаётся (Protocol, фейки в тестах), но типизируется
моделями pkg; `gateway.py` умирает, provider байндит порт→pkg-клиент; kit-ошибки→доменные мапит
usecase. (3) `platform/backend/` удаляется. (4) `extensions.py` сливается в `app.py`. (5) Handlers
строго: ВСЕ шаги wizard'а через usecase (включая passthrough), формат-валидация — виджет, бизнес-
правила и доступ — usecase (кидает typed-ошибку), handler мапит результат/ошибку на экран/текст;
`handlers|getters → policy` запрещён import-linter'ом. (6) `infra/` в фиче — для не-HTTP реализаций
портов (кэш `start`).

**Не входит в скоуп.** Новые фичи/флоу, мульти-бот, изменение `.ftl`-контента (кроме текстов
ошибок, если переезжают), правки tgbotkit, реальный второй бэкенд в `external/`.

**Открытые вопросы.**
- [x] Q1–Q7: место pkg / гранулярность клиентов / anti-corruption / extensions / объём kit-PR /
  строгость handlers / доступ — решены пользователем (см. Контекст).

**Атомы.**

#### Phase 1 — фундамент
- [x] **B1:** пин `pylibinfra` → rev из A5 (`pyproject.toml` + `make lock`); старый код ещё на
  `BackendClient` — kit аддитивен.
  - **Done:** пин `b713602`, `make lock`/`make sync`; `make check` → green
- [x] **B2:** каркас `src/bot/pkg/http_client/`: `internal/profile.py|booking.py|payments.py`
  (API-классы: пути, wire-модели, поверх kit-`ApiClient` «core»), `external/.gitkeep`,
  `provider.py` (DI: core-клиент → API-классы). Эндпойнты/семантика идемпотентности — из
  текущих `gateway.py` фич.
  - **Done:** `src/bot/pkg/` + `tests/pkg/` (conftest + 3 файла); `uv run pytest tests/pkg -q`
    → 11 passed. DI-провязка сразу (dishka валидирует граф жадно): `config.py` → `BackendsConfig`
    (core ← `HTTPCLIENT_*`), `app.py` → `ApiClientsProvider()` + `http_client.Provider()`

#### Phase 2 — фичи на pkg + строгие handlers
- [x] **B3:** `profile`: порт → модели pkg, удалить `gateway.py`, маппинг ошибок в usecase,
  handlers/getters без policy; тесты фичи на фейке порта.
  - **Done:** ports/usecase/views/provider переписаны, `gateway.py`+`dto.py` удалены,
    `tests/_fakes/harness.py` отдаёт pkg-API поверх фейка, +`tests/unit/test_profile_usecase.py`;
    `pytest -k profile` → 28 passed; `make check` → green
- [x] **B4:** `booking`: то же + usecase-шаги wizard'а (`set_services/set_guests/set_address/submit`
  → результат-данные с `next`-семантикой, например `address_required`), handlers только мапят.
  - **Done:** usecase-шаги (включая passthrough set_services), `GuestsStep.address_required`,
    handlers без policy, тексты ошибок шагов в policy-reason → views; +`test_booking_usecase.py`;
    `pytest -k booking` → 13 passed
- [x] **B5:** `payments`: то же (offers/orders/charges → `PaymentsAPI`).
  - **Done:** порт = wire-методы PaymentsAPI; конвертация Offer→Order(Money) и маппинг ошибок —
    в usecase (Order/dto.py живёт — пример осмысленного доменного DTO); фейки трёх юнит-сюит
    переведены; `pytest -k "payments or getters"` → 33 passed
- [x] **B6:** `start`/`lang`: `start/gateway.py` → `start/infra/store.py` (`CacheOnboardingStore`);
  проверить handlers обеих фич на policy-утечки.
  - **Done:** `start/infra/store.py`; найдена и убрана утечка `start/getters.py → policy.greeting_key`
    (решение уехало в `StartUsecase.greeting_key`); слой `state` опущен под `dto` в importlinter
    (GuestsStep оборачивает BookingDraft); `make check` → green

#### Phase 3 — снос лесов
- [x] **B7:** удалить `platform/backend/`; `extensions.py` слить в `app.py` (ExtensionProvider
  внутри composition root), удалить `extensions.py`.
  - **Done:** `platform/backend/` и `extensions.py` удалены, app.py = единый composition root
    (HttpClientProvider kit'а больше не регистрируется — единственный клиент идёт именованным
    «core» через ApiClientsProvider); composition-smoke зелёный
- [x] **B8:** `importlinter.toml`: слои фичи без gateway (+`infra/`), «чистое ядро» разрешает
  модели pkg (но не `httpx`), новый контракт `handlers|getters ↛ policy`, `pkg ↛ features|aiogram`.
  - **Done:** 5 контрактов, все KEPT; контракт «handlers без policy» проверен негативно
    (старый handlers.py ломает lint); `make lint` → green
- [x] **B9:** тесты-инфраструктура: `tests/_fakes/backend.py` → фейки pkg-клиентов;
  `tests/backend/` → `tests/pkg/`; полный гейт.
  - **Done:** `FakeApiClient` (заглушка kit-ApiClient), harness отдаёт pkg-API поверх него,
    `tests/backend/` удалён (transport-граница покрыта `tests/pkg/`); `make check` → 97 passed

#### Phase 4 — документация в новое состояние (forward-only)
- [ ] **B10:** rules: `feature-architecture` (слои: pkg вместо gateway, infra/), `dialog-architecture`
  (handlers без policy, usecase возвращает данные), `tgbotkit-boundary` (без platform/backend,
  без extensions.py).
  - Verify: grep `BackendClient|platform/backend|extensions.py|gateway.py` по `.claude/rules/` → 0 · Зависит от: B9
- [ ] **B11:** skills: `scaffold` (references/backend-port.md → api-client.md: новый клиент в pkg +
  порт; feature/wiring-references), `de-template` wiring-референсы.
  - Verify: grep то же по `.claude/skills/` → 0 совпадений · Зависит от: B10
- [ ] **B12:** docs: `reference/architecture.md`, `reference/dialog-mapping.md`, `reference/ecosystem.md`,
  `docs/stack/`, `getting-started`, корневой `README.md`, `.claude/CLAUDE.md` (карта «где что»).
  - Verify: grep то же по `docs/ README.md .claude/CLAUDE.md` → 0; `make check` → green · Зависит от: B10

**Infra impact.** Ожидаемо «—» (бэкенд один, base_url прежний); если конфиг именованных клиентов
переименует env (`HTTPCLIENT_*`) — оформить INFRA-HANDOFF при B1 (rule `infra-impact`).

**Чекпоинты.**
- **2026-06-10 · код-фазы закрыты, осталась документация.**
  - Закрыто: B1–B9 ✓ (`make check` зелёный на каждом шаге)
  - Обнаружено: `docs/` и `design/`, на которые ссылаются CLAUDE.md/rules, в репо НЕ существуют —
    B12 сводится к README.md + .claude/CLAUDE.md (+ чистка ссылок на несуществующие docs-пути
    по месту); dishka валидирует DI-граф жадно → провязка pkg-провайдеров случилась в B2/B3
  - Следующий шаг: B10–B12 (rules / skills / README+CLAUDE.md)

## Backlog

- Ссылки на `docs/**` и `design/**` в CLAUDE.md/rules/skills указывают на каталоги, которых нет в
  репо — решить: завести доки или вычистить ссылки (карта «где что» в CLAUDE.md, getting-started,
  stack-deep-dive Generates).
- **Метрика успешной выдачи** `payments_total{stage=paid,result=ok}` + лог промаха доставки —
  чтобы регрессии путей платежей/уведомлений перестали быть невидимыми (хвост Фазы 0).
- `.env.example` шаблона: `LOG_REDACT_ENABLED` (хвост 1.7); опц. провязать `OptionalConn`, чтобы
  health-probe в polling проверял и NATS.
- INFRA-HANDOFF Фазы 1 (при релизе/деплое): polling биндит health-порт (`HTTP_*`), новые env-ручки
  (`NATS_JS_MAX_DELIVER/BACKOFF/FLOW_CONTROL/IDLE_HEARTBEAT/DLQ_ENABLED`, `NATS_MAX_RECONNECTS=-1`,
  `BOT_FLOOD_ENABLED`, `BOT_RATE_GLOBAL`, `BOT_RATE_PER_CHAT`, `BOT_RETRY_AFTER_ATTEMPTS`), DLQ-сабжект
  `dlq.<subject>`. Опц. Фазы 2: `BOT_STATE_TTL` (TTL FSM-стейта, дефолт 0=вечно). Опц. Фазы 3:
  `HTTPCLIENT_BREAKER_NAME` (имя breaker'а для per-API метрик). Дефолтный label breaker-метрик
  `http_client_breaker_*{name}` у бота теперь `core` (имя именованного бэкенда) — поправить фильтры
  дашбордов, если завязаны на `httpclient`. payments-adv (подписки/возвраты) требует включённых Stars subscriptions/refunds у бота в
  BotFather — не env, deploy-замечание. Передать инфра-админу через `/release` handoff.
- Свапнуть пин `pylibinfra` с коммита `5f2d124` на release-тег `vX.Y.Z`, когда `pylibinfra`
  будет тегнут на ревизии с `tgbotkit` (`pyproject.toml` → `[tool.uv.sources]`).
