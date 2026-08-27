---
name: feature-architecture
description: Слои и границы фичи (вертикальный срез гексагона) + связь с pkg-клиентами. Terse-инварианты; «как и почему» — docs/reference/architecture.md § Слои фичи. Грузится при работе с src/bot/features/ и src/bot/pkg/.
paths:
  - "src/bot/features/**"
  - "src/bot/pkg/**"
---

# Архитектура фичи

Фича = вертикальный срез одного сценария (зеркало go-домена). Эталоны полного гексагона —
`profile/`, `booking/`, `payments/`; сокращённые (`start`/`lang`) опускают часть слоёв;
`notifications` — не диалог-гексагон (NATS-router + `deliver_*`). HTTP-клиенты бэкендов живут
**не в фиче**, а в `src/bot/pkg/http_client/` (см. «Порты и реализации»).

## Слои (стрелка зависимости — только «вниз»)

`dialogs.py` → `getters.py` | `handlers.py` → `views.py` → `usecase.py` → `policy.py` →
`ports.py` → `dto.py` → `state.py` (`state` — нижний слой). Это enforce'ит import-linter
(контракт «Слои внутри фичи», `importlinter.toml`); `getters` и `handlers` — один слой,
**друг друга не импортят**. `infra/` в слоях не участвует — его импортирует только `provider.py`.

- **PURE-ядро** (`usecase` / `policy` / `state` / `dto` / `errors` / `ports` / `views` /
  `adapters`) не импортит `aiogram` / `aiogram_dialog` / `httpx` / `redis` / свой `infra/`
  (контракт «Чистое ядро»). Wire-модели и typed-ошибки pkg (`bot.pkg.http_client.*`) ядру
  **разрешены** — это язык портов; `pylibinfra.httpclient` напрямую запрещён везде, кроме
  pkg/composition root (ruff banned-api — «одна дверь»). `state.py` тянет
  `aiogram.StatesGroup` **только** транзитом через `platform/dialogs/states` — это
  архитектура, не утечка.
- **I/O — это usecase, не метод модели.** Нужны порт/сеть/кэш → метод `*Usecase`. Чистое правило
  (без I/O, на вход уже загруженные данные) → `policy.py`, возвращает `shared.decision.Decision`.
- **`usecase` знает только Protocol-порты и `policy`** — не `httpx`/`aiogram`/`redis`. **Все**
  шаги wizard'а — методы usecase, включая passthrough вроде `set_services`; usecase возвращает
  результат-данные (`BookingUsecase.set_guests → GuestsStep(draft, address_required)`) и никогда
  не трогает `DialogManager`/экраны. Проверка доступа — `policy` внутри usecase (кидает
  Forbidden-ошибку; handler/getter её ловит).
- **Anti-corruption — в usecase, единственная точка маппинга:** typed-ошибки HTTP-границы
  (`bot.pkg.http_client.errors`) → sentinel'ы `errors.py` по канону «специфичные + catch-all»:
  `NotFoundError`/`ConflictError` → доменные, замыкающий `except ApiError` → `*Unavailable`
  (ничего не протекает в recovery); где нужно — wire-модель → доменный DTO (payments:
  `Offer` → `Order(Money)`).
- **`views.py` — единственное место** маппинга доменной ошибки в сообщение: `error_text`
  отдаёт **`.ftl`-ключ**, рендер — в presentation (`bot.shared.i18n.render` +
  `I18N_FORMAT_KEY`), тексты — в `locales/` (ru/en); не-наша ошибка пробрасывается в
  recovery-middleware kit'а.

## Порты и реализации (ports → pkg | infra)

- Порт фичи — Protocol в `ports.py`: объявлен в потребителе, узкий (ISP), типизирован
  wire-моделями pkg-клиента. `provider.py` байндит порт → pkg-клиент **напрямую**
  (структурная совместимость Protocol, mypy проверяет) — отдельный адаптер не нужен.
- **HTTP-клиенты — `src/bot/pkg/http_client/`** (не сырой `httpx` в фиче): `internal/` — свой
  бэкенд (`profile.py: ProfileAPI` + wire-`User`; `booking.py: BookingAPI` +
  `BookingConfirmation`; `payments.py: PaymentsAPI` + `Offer`/`Charge`); `external/` — клиенты
  сторонних API. База пакета: `errors.py` — реэкспорт таксономии кита (дверь фич к ошибкам),
  `wire.py: WireModel` — база wire-моделей (`extra="forbid"`, `frozen`, без бизнес-дефолтов),
  `idempotency.py: idempotency_key(op, *parts)` — канон ASCII-ключа (sha256), `api.py: JsonApi`
  — Protocol поверхности клиента (фейк реализует его без type: ignore). Клиенты строятся поверх
  `pylibinfra.httpclient.ApiClient` через `model=` (декод прямо в wire-модель; несоответствие →
  `ContractError`); мутации ретраятся kit'ом только с `Idempotency-Key`. `provider.py`
  (`InternalApiProvider`, `CORE_BACKEND = "core"`) берёт именованный клиент из реестра
  `ApiClients.get(имя)`; имена и base_url — `BackendsConfig.backends` (`config.py` собирает
  `BackendConfig` с обязательным `base_url` — пустой валит старт, fail-fast). `pkg` не знает
  про features/platform/aiogram (контракт «pkg не знает про бот»).
- **Не-HTTP реализации портов — `features/<имя>/infra/`** (пример —
  `start/infra/store.py: CacheOnboardingStore` поверх cachekit).

## Cross-feature — только через adapters/provider

- Импорт другой фичи разрешён **исключительно** в `adapters.py` и `provider.py` (контракт
  «Независимость фич», `ignore_imports`). Из ядра/presentation — никогда.
- Порт cross-feature (напр. `OnboardingReader`) объявляешь в **потребителе** (`ports.py`),
  адаптер в `adapters.py` мапит чужой usecase в свой порт-контракт. Связывает порт→реализацию
  только `provider.py` (DIP).

## Presentation и DI

- `getter` = данные (read, дёргает usecase, не порт/клиент); `handler` = реакции/навигация
  (мутации, данные из аргументов виджета, не из getter). `handlers`/`getters` **не импортят
  `policy`** (контракт «Handlers/getters без policy») — доменные решения приходят результатом
  usecase. Детали инъекции — rule `dialog-architecture`.
- Фасад `__init__.py` экспортит ровно `Provider` + `dialog` (+ `cmd_spec`/`command_specs`) —
  внутренности наружу не торчат. `app.py` (composition root, `ExtensionProvider`) видит только это.

## Чек

- Логи — `pylibinfra.logkit.Logger` (не `print`/stdlib `logging`; забанено ruff T20 + banned-api).
- Комментарии — только WHY (rule `comments`).
- Новый HTTP-вызов — метод pkg-клиента + respx-тест в `tests/pkg/`, не сырой `httpx` в фиче.
- `policy`/`views`/валидаторы покрыты unit-тестами; flow — `dialog`-тестами (rule `tests-pipeline`).
- Новая инфра-механика (middleware/runtime) — не сюда, а PR в `tgbotkit` (rule `tgbotkit-boundary`).
- Перед claim «готово» — `make check` зелёный (ruff + import-linter (7 контрактов) +
  mypy src+tests + lock-check + pytest с полом покрытия).
