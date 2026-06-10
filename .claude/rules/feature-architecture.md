---
name: feature-architecture
description: Слои и границы фичи (вертикальный срез гексагона) + связь с pkg-клиентами. Terse-инварианты; «как и почему» — design/ARCHITECTURE.md §8. Грузится при работе с src/bot/features/ и src/bot/pkg/.
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

- **PURE-ядро** (`usecase` / `policy` / `state` / `dto` / `errors` / `ports`) не импортит
  `aiogram` / `aiogram_dialog` / `httpx` / `redis` / свой `infra/` (контракт «Чистое ядро»).
  Wire-модели pkg-клиентов (`bot.pkg.*`) и typed-ошибки `pylibinfra.httpclient` ядру
  **разрешены** — это язык портов; запрещён сырой транспорт. `state.py` тянет
  `aiogram.StatesGroup` **только** транзитом через `platform/dialogs/states` — это
  архитектура, не утечка.
- **I/O — это usecase, не метод модели.** Нужны порт/сеть/кэш → метод `*Usecase`. Чистое правило
  (без I/O, на вход уже загруженные данные) → `policy.py`, возвращает `shared.decision.Decision`.
- **`usecase` знает только Protocol-порты и `policy`** — не `httpx`/`aiogram`/`redis`. **Все**
  шаги wizard'а — методы usecase, включая passthrough вроде `set_services`; usecase возвращает
  результат-данные (`BookingUsecase.set_guests → GuestsStep(draft, address_required)`) и никогда
  не трогает `DialogManager`/экраны. Проверка доступа — `policy` внутри usecase (кидает
  Forbidden-ошибку; handler/getter её ловит).
- **Anti-corruption — в usecase, единственная точка маппинга:** typed-ошибки httpclient
  (`NotFoundError`/`ConflictError`/`UnavailableError`) → sentinel'ы `errors.py`; где нужно —
  wire-модель → доменный DTO (payments: `Offer` → `Order(Money)`).
- **`views.py` — единственное место** превращения доменной ошибки в user-текст (`error_text`);
  не-наша ошибка пробрасывается в recovery-middleware kit'а.

## Порты и реализации (ports → pkg | infra)

- Порт фичи — Protocol в `ports.py`: объявлен в потребителе, узкий (ISP), типизирован
  wire-моделями pkg-клиента. `provider.py` байндит порт → pkg-клиент **напрямую**
  (структурная совместимость Protocol, mypy проверяет) — отдельный адаптер не нужен.
- **HTTP-клиенты — `src/bot/pkg/http_client/`** (не сырой `httpx` в фиче): `internal/` — свой
  бэкенд (`profile.py: ProfileAPI` + wire-`User`; `booking.py: BookingAPI` +
  `BookingConfirmation`; `payments.py: PaymentsAPI` + `Offer`/`Charge`; `codec.py: parse` —
  `ValidationError` → `UnavailableError`); `external/` — клиенты сторонних API. Клиенты строятся
  поверх `pylibinfra.httpclient.ApiClient` (типизированный JSON-слой: get/post/put/patch/delete
  → декодированный JSON; typed-ошибки; Idempotency-Key). `provider.py`
  (`InternalApiProvider`, `CORE_BACKEND = "core"`) берёт именованный клиент из реестра
  `ApiClients.get(имя)`; имена и base_url — `BackendsConfig.backends` (`config.py`:
  `BackendsConfig{core: HttpConfig()}`, env `HTTPCLIENT_*`). `pkg` не знает про
  features/platform/aiogram (контракт «pkg не знает про бот»).
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
- Перед claim «готово» — `make check` зелёный (ruff + import-linter (5 контрактов) + mypy + pytest).
