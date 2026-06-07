---
name: triage-failure
description: Red-арм cockpit'а — структурированный разбор красного теста / ruff / mypy / import-linter / startup-smoke (emit_startup / setup_dialogs — коллизии StatesGroup). TDD-first для багфиксов (RED→GREEN). smartdev чейнит сюда на ATTENTION; багфикс идёт сюда, НЕ в plan. Активируй когда юзер пишет "тест падает", "ruff/mypy ругается", "import-linter красный", "бот не стартует", "UnknownIntent/UnknownState", "почему упало", "разбери failure", "вот трейс".
---

# Skill: triage-failure

Дисциплинированный разбор падения. Цель — найти **корневую причину**, не замазать симптом, и зафиксировать инвариант тестом.

**Red-арм cockpit'а:** `smartdev` переключает сюда, когда `make status`/`make check` дал `ATTENTION:` (red-тест / lint / mypy / import-linter / startup-smoke) или задача — багфикс. Багфикс **никогда не идёт в `plan`** — он идёт сюда, по строгой петле RED→GREEN→REFACTOR. Фича-работа тоже дефолтно тест-first (ведёт `smartdev §4`), но её разбор отказов — здесь.

## Когда применять

- "Тест X падает"
- "ruff/mypy выдаёт N ошибок", "import-linter красный"
- "Бот не стартует" / "`setup_dialogs` падает" / "коллизия StatesGroup"
- "У юзера `UnknownIntent`/`UnknownState`/`OutdatedIntent`"
- Юзер кидает stack trace / traceback / error message

## Когда НЕ применять

- Юзер просит implement новую фичу — это `plan` или прямая работа.
- Лёгкая опечатка, видно с первой строки — просто чини, не разводи процедуру.
- Эволюция `StatesGroup` (осознанная) — это `state-migration`, не triage.

## Категории падений

| Тип | Признаки | Где смотреть |
|---|---|---|
| **import-linter** | `Contracts: ... BROKEN`, нарушение «Слои внутри фичи» / «Независимость фич» / «Чистое ядро» | `uv run lint-imports --config importlinter.toml` — какой контракт и какая стрелка |
| **ruff** | `[ruff]`-коды (`T20`, `S`, `TID252`, `ASYNC`, `PT`) | `make lint` / `uv run ruff check .` — топ по коду |
| **mypy** | `error: ... [code]`, чаще Protocol-несовместимость адаптера и порта | `make typecheck` / `uv run mypy src` |
| **Unit test** | `FAILED tests/unit/... assert` | `uv run pytest tests/unit/test_X.py -q` |
| **Flow / dialog test** | падает прогон `BotClient` (текст/клавиатура не та) | `uv run pytest tests/flows/test_X.py -q` |
| **Startup-smoke** | `setup_dialogs`/`emit_startup` кидает на сборке — **дублирующиеся State, окно без `state=`, два Dialog на одну StatesGroup** | `tests/flows/test_composition.py` — `test_container_assembles_and_dialogs_collision_free` |
| **Stale-callback (runtime)** | у юзера `UnknownIntent`/`UnknownState`/`OutdatedIntent` после деплоя/TTL | error-handlers (`platform/dialogs/errors.py` = `ErrorUX`) + был ли вырезан живой State |
| **Storage-serialization** | падение при записи в Redis: `datetime`/`Decimal`/объект не JSON | что кладётся в `dialog_data`/`widget_data`/`start_data` |
| **Integration** | падает только под `make test-integration` (Docker) | testcontainers redis/nats, реальный StreamBus |

## Шаги

### 1. Воспроизвести минимально

Спроси или посмотри сам:
- Как воспроизводится? Команда?
- Локально или только в CI?
- На какой ветке / коммите? Когда последний раз работало?

Гоняй точечно, не `make test` на всём:
```bash
uv run pytest tests/unit/test_payments.py -q
uv run pytest tests/flows/test_profile_flow.py -q -x
uv run pytest -k "collision" -q          # startup-smoke композиции
```

### 2. Прочитать сообщение целиком

Не первую строку — **целиком**. В Python traceback самое полезное — внизу (последний кадр + тип исключения), у pytest — блок `assert` с diff `expected`/`got`, у import-linter — какая стрелка нарушила какой контракт. Читай до конца.

### 3. Сформулировать гипотезу

Одно проверяемое предложение «X падает потому что Y». Примеры:
- "test_profile_flow падает потому что getter не отдаёт ключ `status`, а `Format` его требует → `KeyError` при рендере."
- "import-linter красный потому что `usecase.py` импортит `httpx` напрямую — должно идти через `gateway` (контракт «Чистое ядро»)."
- "mypy ругается потому что `HttpProfileGateway.update_name` не совпадает сигнатурой с `ports.BackendGateway` — адаптер структурно не удовлетворяет порту."
- "`setup_dialogs` падает потому что два окна объявили `state=ProfileSG.VIEW` (дубль) либо State объявлен по месту вместо `platform/dialogs/states.py`."

Несколько гипотез — выбирай самую дешёвую в проверке.

### 4. TDD для багфиксов (обязательно)

Если это **баг** (а не lint/mypy/import-linter/drift):

1. **Напиши падающий тест**, воспроизводящий баг.
   - unit для policy/views/валидатора; flow (`BotClient`+`MockMessageManager`+`JsonMemoryStorage`) для сценария окна.
   - Тест падает **по той же причине**, что и прод-баг — иначе тестируешь другое.
   - Мокай **порт** (`FakeBackendClient`/фейк-gateway), не транспорт. Кнопки локай по `callback_data`/тексту.
2. `uv run pytest tests/.../test_new.py -q` → red. Подтверди, что red — твой red, не тест-инфра.
3. **Только теперь** правь продакшен-код.
4. `uv run pytest tests/.../test_new.py -q` → green.
5. `make test` → весь набор green (не сломал соседей).
6. Коммит: оба файла одним `fix(<scope>): <one-liner>`.

### 5. Не-баг-флоу (lint / mypy / import-linter / startup-smoke)

| Случай | Действие |
|---|---|
| **import-linter «Чистое ядро»** | `usecase`/`policy`/`state`/`dto` импортит `httpx`/`aiogram`/`aiogram_dialog`/`redis`/свой `gateway`. Вынеси I/O в `gateway.py`, оставь ядру только Protocol-порты. |
| **import-linter «Слои внутри фичи»** | стрелка «вверх» (напр. `usecase → handlers`) или `getters`↔`handlers` импортят друг друга. Они один слой — общее в `views`/`state`. |
| **import-linter «Независимость фич»** | прямой импорт другой фичи из ядра/presentation. Только `adapters.py`/`provider.py` (порт + адаптер — `scaffold` backend-port). |
| **ruff T20 / banned-api** | `print`/`logging` напрямую → `pylibinfra.logkit.Logger` (в usecase инжектится, см. profile). В тестах T20 выключен. |
| **ruff S (bandit)** | подозрительный паттерн; если оправдан — `# noqa: S<NNN>  # <причина>`, не глуши скопом. |
| **mypy Protocol-несовместимость** | адаптер/gateway не совпадает сигнатурой с портом. Выровняй типы; mypy strict проверяет структурно. |
| **startup-smoke (`setup_dialogs`/`emit_startup`)** | коллизия/пропуск State: дубль `state=` на два окна; State объявлен по месту, а не в `platform/dialogs/states.py`; два `Dialog` на одну StatesGroup; окно без `state=`. Чини в `states.py`+`dialogs.py`, прогони `pytest -k collision`. Удалил живой State → это `state-migration`, верни deprecation. |
| **storage-serialization** | в `dialog_data`/`widget_data`/`start_data` попал не-JSON (`datetime`→ISO-строка, pydantic→`model_dump(mode="json")`). `JsonMemoryStorage` в flow-тестах ловит это — добавь тест. |

### 6. Stale-callback у пользователя (`UnknownIntent`/`UnknownState`/`OutdatedIntent`)

Это runtime-симптом, не падение CI. Две причины:
- **Норма после рестарта/TTL**: kit ловит и зовёт `ErrorUX` (`platform/dialogs/errors.py`) → подсказка `/start`. Проверь, что `AppErrorUX.on_unknown_intent`/`on_unknown_state` отвечают на callback (гасят «часики») и не трогают сообщение (могло быть удалено).
- **Регресс от деплоя**: вырезали/переименовали живой State → у юзеров в открытых диалогах нет на что приземлиться. Это `state-migration` (deprecation вместо удаления) — верни State, пометь deprecated.

### 7. Граф переходов как диагностика (preview-graph)

Если падение про навигацию/переходы (не туда ведёт кнопка, тупик, недостижимое окно) — построй граф через `preview-flow` (`render_transitions`) и посмотри глазами: лишнее ребро, недостижимый State, цикл без выхода. Требует `aiogram_dialog[tools]`+graphviz (см. skill `preview-flow`).

### 8. Если корневая причина в инфре (`tgbotkit`/kit)

- Баг в `tgbotkit`/другом kit'е `pylibinfra` → не лечи workaround'ом у себя без обсуждения. Скажи юзеру, предложи временный shim с `# TODO` + reference; фикс инфры — PR в `pylibinfra` через `infra-handoff`.
- Не помечай flaky-тест `@pytest.mark.skip` — проверь, не глобальное ли state-загрязнение (module-level `Dialog`-синглтоны детачатся `_parent_router = None` между тестами — см. `tests/_fakes/harness.py`).

### 9. Когда застрял

Признаки: 2+ попытки не помогли; каждая ломает другое; гипотеза не сужается.

Действия:
1. Откатись (`git stash`) к чистому red-state.
2. Сформулируй вслух юзеру: «Думаю X, но проверка через Y даёт Z. Не хватает Q.»
3. Делегируй subagent `explorer`: «найди все места, где регистрируется/читается `<State>`/`<порт>`» — вернёт сжатую сводку.
4. Если всё равно — `plan` skill: TDD-research-spike.

### 10. Верификация фикса

```bash
uv run pytest tests/.../test_X.py -q
make lint        # ruff + import-linter
make typecheck
```
Перед коммитом — `make check`.

## Что искать дополнительно

- Не пропущен ли тест на смежный сценарий (edge case B рядом с A)?
- Не баг ли это паттерна (если в одной фиче getter без дефолта ключа — нет ли в других)?
- Стоит ли добавить инвариант в `policy`-тест / startup-smoke?

## Anti-patterns

- ❌ «Перепиши тест чтобы проходил» — это сокрытие, не фикс.
- ❌ `@pytest.mark.skip` для flaky — корневая причина не уйдёт, всплывёт в проде.
- ❌ `--no-verify` чтобы запушить красное — заблокировано хуком, и правильно.
- ❌ `# type: ignore` / `# noqa` без причины-комментария вместо реального фикса.
- ❌ Фикс без теста для баг-фикса. TDD не опциональна для багов.
- ❌ Удалить живой State, чтобы «убрать» `UnknownState` — сломаешь больше. → `state-migration`.
- ❌ Большой «while we're at it» при фиксе бага. Баг-фикс = маленький коммит. Большое — отдельный план.
