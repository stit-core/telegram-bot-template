---
name: feature-architecture
description: Слои и границы фичи (вертикальный срез гексагона). Terse-инварианты; «как и почему» — design/ARCHITECTURE.md §8 + design/FEATURE-BLUEPRINT.md. Грузится при работе с src/bot/features/.
paths:
  - "src/bot/features/**"
---

# Архитектура фичи

Полные скелеты файлов и направление зависимостей — `design/FEATURE-BLUEPRINT.md`; роль слоёв —
`design/ARCHITECTURE.md §8`. Здесь — что обязан соблюдать при правке `src/bot/features/`.

Фича = вертикальный срез одного сценария (зеркало go-домена). Эталон полного гексагона —
`profile/`; сокращённые (`start`/`lang`) опускают `gateway/ports/dto/views`; `notifications` —
не диалог-гексагон (NATS-router + `deliver_*`).

## Слои (стрелка зависимости — только «вниз»)

`dialogs.py` → `getters.py` | `handlers.py` → `views.py` → `usecase.py` → `policy.py` →
`ports.py` → `dto.py` | `state.py`. Это enforce'ит import-linter (контракт «Слои внутри фичи»,
`importlinter.toml`); `getters` и `handlers` — один слой, **друг друга не импортят**.

- **PURE-ядро** (`state` / `dto` / `errors` / `policy` / `ports`) не импортит `aiogram` /
  `aiogram_dialog` / `httpx` / `redis` / свой `gateway`. Запрещено import-linter'ом (контракт
  «Чистое ядро»). `state.py` тянет `aiogram.StatesGroup` **только** транзитом через
  `platform/dialogs/states` — это архитектура, не утечка.
- **I/O — это usecase, не метод модели.** Нужны порт/сеть/кэш → метод `*Usecase`. Чистое правило
  (без I/O, на вход уже загруженные данные) → `policy.py`, возвращает `shared.decision.Decision`.
- **`usecase` знает только Protocol-порты и `policy`** — не `httpx`/`aiogram`/`redis`/`gateway`.
  Порты узкие (ISP), объявлены в потребителе, возвращают локальные DTO фичи (anti-corruption).
- **`gateway.py` — единственный I/O**, поверх `platform/backend` (не сырой `httpx`). Мапит
  транспорт-ошибки (`BackendNotFound`/`BackendUnavailable`) в sentinel'ы `errors.py`.
- **`views.py` — единственное место** превращения доменной ошибки в user-текст (`error_text`);
  не-наша ошибка пробрасывается в recovery-middleware kit'а.

## Cross-feature — только через adapters/provider

- Импорт другой фичи разрешён **исключительно** в `adapters.py` и `provider.py` (контракт
  «Независимость фич», `ignore_imports`). Из ядра/presentation — никогда.
- Порт cross-feature (напр. `OnboardingReader`) объявляешь в **потребителе** (`ports.py`),
  адаптер в `adapters.py` мапит чужой usecase в свой порт-контракт. Связывает порт→реализацию
  только `provider.py` (DIP).

## Presentation и DI

- `getter` = данные (read, дёргает usecase, не gateway); `handler` = реакции/навигация (мутации,
  данные из аргументов виджета, не из getter). Детали инъекции — rule `dialog-architecture`.
- Фасад `__init__.py` экспортит ровно `Provider` + `dialog` (+ `cmd_spec`/`command_specs`) —
  внутренности наружу не торчат. `app.py`/`extensions.py` видят только это.

## Чек

- Логи — `pylibinfra.logkit.Logger` (не `print`/stdlib `logging`; забанено ruff T20 + banned-api).
- Комментарии — только WHY (rule `comments`).
- `policy`/`views`/валидаторы покрыты unit-тестами; flow — `dialog`-тестами (rule `tests-pipeline`).
- Новая инфра-механика (middleware/runtime) — не сюда, а PR в `tgbotkit` (rule `tgbotkit-boundary`).
- Перед claim «готово» — `make check` зелёный (ruff + import-linter + mypy + pytest).
