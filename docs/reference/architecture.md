# Architecture

Слои фичи (гексагон), pkg-клиенты, composition root, граница с tgbotkit. Path-scoped правила
(`.claude/rules/*`) держат terse-инварианты и ссылаются сюда за «как и почему».

## Слои фичи

Каждая фича `src/bot/features/<name>/` — изолированный вертикальный срез одного сценария
(bounded context). Стрелки импортов — внутрь (presentation → usecase → ports; никогда наоборот):

```
<feature>/
├── __init__.py   фасад: экспортит Provider + dialog (+ cmd_spec/command_specs) — всё, что видит app.py
├── ports.py      Protocol-порты сценария (PURE); типизированы wire-моделями pkg-клиента (DIP)
├── usecase.py    оркестрация; знает ТОЛЬКО порты + policy; anti-corruption (kit-ошибки → sentinel)
├── policy.py     чистые решения (PURE) → Decision (allow/deny + reason)
├── errors.py     sentinel-ошибки фичи (наследуют shared.FeatureError)
├── state.py      алиас StatesGroup + pydantic-модель dialog_data (только JSON-примитивы)
├── dialogs.py    Dialog/Window — presentation как разметка (Format/I18NFormat, виджеты, getter)
├── getters.py    данные в окно — дёргают usecase (read), @inject, **kwargs, дефолты ключей
├── handlers.py   реакции (клик/ввод) — usecase (мутация) + навигация (manager.switch_to/done/start)
├── views.py      результат/ошибка usecase → данные виджетов + user-текст (PURE)
├── provider.py   dishka Provider (Scope.REQUEST): порт→pkg-клиент (DIP), сборка usecase
├── adapters.py   cross-feature anti-corruption (опц.) — единственное место импорта другой фичи
└── infra/        не-HTTP реализации портов (опц., напр. start/infra/store.py — кэш onboarding)
```

| Тип кода | Где |
|---|---|
| Presentation (окна/переходы) | `dialogs.py` |
| Данные окна (read) | `getters.py` → usecase |
| Реакции (клик/ввод, мутация) | `handlers.py` → usecase |
| Маппинг результат/ошибка → текст | `views.py` (PURE) |
| Логика сценария | `usecase.py` |
| Чистые решения | `policy.py` → `Decision` |
| Порты (Protocol) | `ports.py` |
| Sentinel-ошибки | `errors.py` |
| FSM-состояния, контракт dialog_data | `state.py` (+ каталог `platform/dialogs/states.py`) |
| DI-связка портов с реализациями | `provider.py` (+ `adapters.py` для cross-feature) |

## Чистое ядро и anti-corruption

`usecase`/`policy`/`state`/`dto`/`ports`/`errors`/`views`/`adapters` — **чистое ядро**: не
импортит `httpx`/`aiogram`/`redis`/свой `infra/` напрямую (import-linter, контракт «чистое
ядро»). Wire-модели и typed-ошибки — язык портов, но только через `bot.pkg.http_client`
(«одна дверь»: `pylibinfra.httpclient` вне pkg запрещён ruff banned-api); порт типизирован
моделью pkg-клиента, поэтому `ProfileAPI` удовлетворяет порт **структурно**, без адаптера.
Единственная точка anti-corruption — `usecase`: typed-ошибки HTTP-границы мапятся в sentinel'ы
`errors.py` по канону «специфичные + catch-all» (`NotFoundError`/`ConflictError` → доменные,
замыкающий `except ApiError` → `*Unavailable`), не в presentation. `views.error_text` отдаёт
`.ftl`-ключ; рендер — `bot.shared.i18n.render` + `I18N_FORMAT_KEY` в getter/handler.

`handlers`/`getters` **не зовут** `policy` (import-linter): доменное решение приходит результатом
usecase. `policy` возвращает `Decision` (общий `shared/decision.py`), usecase решает, бросать ли
sentinel.

## pkg-клиенты (`src/bot/pkg/http_client/`)

HTTP к бэкендам — только через pkg-клиенты, не `httpx` из фичи:

```
http_client/
├── __init__.py   фасад: Provider + CORE_BACKEND
├── errors.py     таксономия typed-ошибок (реэкспорт кита) — дверь фич к ошибкам бэкенда
├── wire.py       WireModel — база wire-моделей (extra="forbid", frozen, без бизнес-дефолтов)
├── idempotency.py  idempotency_key(op, *parts) — канон ASCII-ключа (sha256)
├── api.py        JsonApi — Protocol поверхности ApiClient (клиенты и тест-фейк зависят от него)
├── provider.py   InternalApiProvider (Scope.APP): API-классы поверх именованного ApiClient «core»
├── internal/     наши бэкенды — API-классы (пути + wire-модели, декод через model=)
│   └── profile.py / booking.py / payments.py — ProfileAPI/BookingAPI/PaymentsAPI + wire-модели
└── external/     сторонние API (.gitkeep)
```

Топология реальная: один internal-бэкенд «core» (profile/booking/payments — один base_url
`HTTPCLIENT_*`); имя бэкенда = ключ `BackendsConfig` = имя circuit-breaker'а. Декларация
бэкенда — `BackendConfig` с обязательным `base_url`: незаполненный валит контейнер на старте
(fail-fast, ловится composition-тестом), глобальные `HTTPCLIENT_*` в декларации других бэкендов
не наследуются. Мутации ретраятся kit'ом только с `Idempotency-Key`; ключ клиент считает сам
(`idempotency.idempotency_key`). `pkg` не знает про `features`/`platform`/`aiogram`
(import-linter, контракт «pkg не знает про бот»). Новый internal-бэкенд: модуль в `internal/`,
имя-константа, `@provide` в `provider.py`, `BackendConfig` в `config.py`. Процедура —
`scaffold backend-port`.

## Composition root (`src/bot/app.py`)

Единственное место сборки. Бот **ничего не проводит в рантайм руками** — он **декларирует** блоки
в точки расширения kit'ов:

- `ExtensionProvider(Provider)` — точки расширения: `routers` → `RouterBundle` (Dialog'и фич),
  `commands` → `CommandBundle` (`CommandSpec`: команда / pre_checkout / successful_payment),
  `notifiers` → `NotifierBundle` (NATS-подписчики), `error_ux` → `ErrorUX`, `resolver` →
  `OptionalLocaleResolver` (ChainResolver: явный выбор локали ≻ language_code), `stream_bus` →
  `OptionalStreamBus` (None без JetStream → runner пропускает notifications), `probes` →
  `healthkit.Probes` (`tgbotkit.probe`, `tgbotkit.redis_probe`, `natskit.probe` — их гоняет
  `/ready`).
- `build_container()` — `make_async_container`: инфра (pylibinfra-провайдеры `LogkitProvider`,
  `ClockProvider`, `CachekitProvider`, `ApiClientsProvider`, `NatsProvider`,
  `HttpProvider(autostart=False)`, `BotProvider`, `AiogramProvider`) + `AppConfigProvider` (все
  `*Config` через `<kit>.new_config()`) + pkg (`http_client.Provider`) + платформа
  (`IdentityProvider`) + фичи (`<feature>.Provider`) + `ExtensionProvider`. Порядок значим
  (последний побеждает): kit'ы дают дефолты своих Optional*/кортежей (`LogkitProvider` — redact,
  `HttpProvider` — пробы, `BotProvider` — bundles/ErrorUX/Optional*), поэтому
  `AppConfigProvider` и `ExtensionProvider` идут ПОСЛЕ них. `Logger` даёт `LogkitProvider`,
  `Clock` — `ClockProvider`: kit'ы чужих общих типов дефолтами не подменяют.
- `run()` — лог `starting` (версия/коммит сборки), резолв `BotRunner`, `runner.run()`. Runner
  занимает HTTP-порт, владеет жизненным циклом и на shutdown зовёт `container.close()`; сорванный
  старт (невалидный ENV, недоступный Redis/NATS) закрывает контейнер сам.

Вся инфра-проводка (storage/middleware/`setup_dishka`/`setup_dialogs`/polling|webhook/HTTP-порт/
graceful shutdown) — в kit'е.

| Блок | Точка регистрации (`app.py`, если не указано иное) |
|---|---|
| `Dialog` фичи | `RouterBundle` (метод `routers`) |
| dispatcher-level хендлер (команда, pre_checkout, successful_payment) | `CommandBundle` через `CommandSpec` (метод `commands`) |
| NATS-подписчик | `NotifierBundle` (метод `notifiers`) |
| dishka Provider фичи | `build_container()` |
| pkg-клиент нового API | `@provide` в `pkg/http_client/provider.py` (+ `BackendsConfig` в `config.py`) |
| `StatesGroup` | `platform/dialogs/states.py` (единый каталог) |
| ErrorUX / resolver локали / stream-bus / health-пробы | методы `ExtensionProvider` |

Фасад фичи `__init__.py` экспортит ровно `Provider` + `dialog` (+ `cmd_spec`/`command_specs`) —
это всё, что видит `app.py`.

## Платформа и shared

- `platform/dialogs/states.py` — **единый каталог** StatesGroup всех фич (разрыв циклов импорта;
  эволюция — только deprecation, rule `state-lifecycle`).
- `platform/dialogs/errors.py` — `AppErrorUX`: на устаревших кнопках (`UnknownIntent`/`UnknownState`
  после рестарта/TTL) гасит «часики» callback'а и подсказывает `/start`.
- `platform/identity/` — `BotIdentity` (REQUEST-scope: `tg_id` + `backend_user_id` + `role`),
  резолвится из Update.
- `shared/decision.py` — `Decision` (allow/deny + reason), общий тип policy; `shared/errors.py` —
  `FeatureError` (база sentinel'ов; recovery/ErrorUX отличает доменную ошибку от настоящего сбоя).

## Фоновые апдейты (notifications/jobs)

Отдельного worker-процесса нет: NATS-подписчики и периодические jobs поднимаются **в том же
процессе** через точки расширения. Фоновая доставка идёт мимо обычной middleware-цепочки —
request_id/локаль/грабли BgManager закрыты в `tgbotkit.Delivery` (rule `background-updates`).
Уведомление — всегда идемпотентно (NATS at-least-once).

## Граница с pylibinfra (tgbotkit)

Переиспользуемое/инфраструктурное (middleware, runner, новый вид рантайма, generic-обёртка) —
**кандидат в `pylibinfra/tgbotkit`, не в этот репо**. Не плодить полукалеки здесь. Бизнес-логика —
сюда; платформенный примитив — upstream (PR через `infra-handoff`). Так шаблон остаётся тонким
слоем, а улучшения едут всем ботам сразу. Инвариант для агента — `CLAUDE.md § Стиль кода`,
rule `tgbotkit-boundary`.

## import-linter (7 контрактов) + banned-api

`importlinter.toml`: (1) слои внутри фичи (DIP, стрелка внутрь); (2) независимость фич (cross-feature
только через `adapters.py`/`provider.py`); (3) чистое ядро не импортит инфру напрямую
(`httpx`/`aiogram`/`redis`/свой `infra/`); (4) `handlers`/`getters` без `policy`; (5) `pkg` не знает
про `features`/`platform`/`aiogram`; (6) `httpx` — только в `pkg`; (7) presentation
(`dialogs`/`getters`/`handlers`) не ходит в `pkg` (данные — через usecase). «Одна дверь к бэкенду»
(`pylibinfra.httpclient` только через `bot.pkg.http_client`) — ruff banned-api TID251
(import-linter не запрещает подпакеты внешних пакетов).

## Non-goals (осознанно не делаем)

- **Инфра-проводка в шаблоне** — Bot/Dispatcher/storage/middleware/runner живут в `tgbotkit`; здесь
  только регистрация в точки расширения.
- **Свой HTTP-клиент/middleware/runner** — это PR в `pylibinfra`, не локальная полукалека.
- **Не-JSON в `dialog_data`/`start_data`** — `datetime`/`Decimal`/ORM падут в Redis; только
  JSON-примитивы.
- **Удаление живого `State` «на месте»** — ломает открытые диалоги (`UnknownState`); только
  deprecation через `state-migration`.
- **Доменное решение в presentation** — ветвление/валидация в usecase/policy; окно показывает и
  маршрутизирует.

Это present-state policy (триггер пересмотра — обсуждение с владельцем), не история.
