---
name: triage-failure
description: Разбор падения бота до корневой причины — красный тест, ruff, mypy, import-linter, startup-smoke (emit_startup / setup_dialogs, коллизии StatesGroup), бот не стартует, UnknownIntent/UnknownState у пользователей, присланный трейс. Багфикс любого размера ведётся здесь по TDD (RED→GREEN), не через plan; smartdev чейнит сюда на ATTENTION и красный make check.
---

# Skill: triage-failure

Дисциплинированный разбор падения. Цель — найти **корневую причину**, не замазать симптом, и
зафиксировать инвариант тестом.

**Red-арм cockpit'а:** `smartdev` переключает сюда на `ATTENTION: syntax` из `make status`, на
красный `make check`/тест (lint, mypy, import-linter, startup-smoke) или когда задача — багфикс.
Багфикс идёт сюда, а не в `plan`: строгая петля RED→GREEN→REFACTOR. Фича-работа тоже тест-first
(ведёт `smartdev §4`), но её разбор отказов — здесь.

## Когда применять

- «Тест X падает», «ruff/mypy выдаёт N ошибок», «import-linter красный».
- «Бот не стартует» / «`setup_dialogs` падает» / «коллизия StatesGroup».
- «У юзера `UnknownIntent`/`UnknownState`/`OutdatedIntent`».
- Юзер кидает stack trace / traceback / error message.

## Когда не применять

- Юзер просит новую фичу — это `plan` или прямая работа.
- Опечатка, видная с первой строки, — просто чини.
- Осознанная эволюция `StatesGroup` — это `state-migration`.

## Категории падений

| Тип | Признаки | Где смотреть |
|---|---|---|
| **import-linter** | `Contracts: ... BROKEN` — «Слои внутри фичи» / «Независимость фич» / «Чистое ядро» / «Handlers/getters без policy» / «pkg не знает про бот» / «HTTP-транспорт только в pkg» / «Presentation не ходит в pkg» | `uv run lint-imports --config importlinter.toml` — какой контракт и какая стрелка |
| **ruff** | `[ruff]`-коды (`T20`, `S`, `TID251` banned-api, `TID252`, `ASYNC`, `PT`) | `make lint` / `uv run ruff check .` — топ по коду |
| **mypy** | `error: ... [code]`, чаще Protocol-несовместимость pkg-клиента/адаптера и порта | `make typecheck` / `uv run mypy src tests` |
| **Unit test** | `FAILED tests/unit/... assert` | `uv run pytest tests/unit/test_X.py -q` |
| **Flow / dialog test** | падает прогон `BotClient` (текст/клавиатура не та) | `uv run pytest tests/flows/test_X.py -q` |
| **Startup-smoke** | `setup_dialogs`/`emit_startup` кидает на сборке — **дублирующиеся State, окно без `state=`, два Dialog на одну StatesGroup** | `tests/flows/test_composition.py` — `test_container_assembles_and_dialogs_collision_free` |
| **Stale-callback (runtime)** | у юзера `UnknownIntent`/`UnknownState`/`OutdatedIntent` после деплоя/TTL | error-handlers (`platform/dialogs/errors.py` = `ErrorUX`) + был ли вырезан живой State |
| **Storage-serialization** | падение при записи в Redis: `datetime`/`Decimal`/объект не JSON | что кладётся в `dialog_data`/`widget_data`/`start_data` |
| **Integration** | падает только под `make test-integration` (Docker) | testcontainers redis/nats, реальный StreamBus |

## 1. Воспроизвести минимально

Выясни (у юзера или сам): команда воспроизведения; локально, только под Docker
(`make test-integration`) или только в проде; ветка/коммит; когда последний раз работало. Гоняй
точечно, не `make test` на всём:

```bash
uv run pytest tests/unit/test_payments.py -q
uv run pytest tests/flows/test_profile_flow.py -q -x
uv run pytest -k "collision" -q          # startup-smoke композиции
```

## 2. TDD для багфиксов

Если это **баг** (а не lint/mypy/import-linter/drift), порядок важен:

1. **Напиши падающий тест**, воспроизводящий баг.
   - unit для policy/views/валидатора; flow (`BotClient`+`MockMessageManager`+`JsonMemoryStorage`)
     для сценария окна.
   - Тест падает **по той же причине**, что и прод-баг, — иначе тестируешь другое.
   - Мокай **порт** (фейк порта в unit-тесте usecase) или границу бэкенда (`FakeApiClient` из
     `tests/_fakes/backend.py` в flow-тестах), не транспорт; httpx/respx — только в `tests/pkg/`.
     Кнопки локай по `callback_data`/тексту.
2. `uv run pytest tests/.../test_new.py -q` → red. Подтверди, что red — твой, а не тест-инфра.
3. **Только теперь** правь продакшен-код.
4. `uv run pytest tests/.../test_new.py -q` → green.
5. `make test` → весь набор green (не сломал соседей).
6. Коммит — когда юзер попросит: тест и фикс одним `fix(<scope>): <one-liner>`.

## 3. Не-баг-флоу (lint / mypy / import-linter / startup-smoke)

| Случай | Действие |
|---|---|
| **import-linter «Чистое ядро»** | `usecase`/`policy`/`state`/`dto`/`ports`/`errors`/`views`/`adapters` импортит `httpx`/`aiogram`/`aiogram_dialog`/`redis`/свой `infra/`. HTTP — в pkg-клиент (`pkg/http_client/`), ядру — Protocol-порты; wire-модели и typed-ошибки `bot.pkg.http_client.*` ядру разрешены, `pylibinfra.httpclient` напрямую — нет (ruff TID251). |
| **import-linter «Слои внутри фичи»** | стрелка «вверх» (напр. `usecase → handlers`) или `getters`↔`handlers` импортят друг друга. Они один слой — общее в `views`/`state`. |
| **import-linter «Независимость фич»** | прямой импорт другой фичи из ядра/presentation. Только `adapters.py`/`provider.py` (порт + адаптер — `scaffold` backend-port). |
| **import-linter «Handlers/getters без policy»** | handler/getter зовёт `policy` напрямую. Доменное решение — метод usecase; handler получает результат-данные и мапит на экран/текст. |
| **import-linter «pkg не знает про бот»** | модуль в `bot.pkg` импортит `bot.features`/`bot.platform`/`aiogram`. pkg — переиспользуемые клиенты; бизнес — в фиче. |
| **import-linter «HTTP-транспорт только в pkg» / «Presentation не ходит в pkg»** | `httpx` в фиче/платформе или `dialogs`/`getters`/`handlers` импортят `bot.pkg`. Данные — через usecase → порт → pkg-клиент. |
| **ruff T20 / banned-api** | `print`/`logging` напрямую → `pylibinfra.logkit.Logger` (в usecase инжектится, см. profile); `pylibinfra.httpclient` вне pkg → `bot.pkg.http_client`. В тестах T20 и TID251 выключены. |
| **ruff S (bandit)** | подозрительный паттерн; если оправдан — `# noqa: S<NNN>  # <причина>`, не глуши скопом. |
| **mypy Protocol-несовместимость** | pkg-клиент/адаптер не совпадает сигнатурой с портом (`ports.py`). Выровняй имена/типы методов; mypy strict проверяет структурно на байнде в `provider.py`. |
| **startup-smoke (`setup_dialogs`/`emit_startup`)** | коллизия/пропуск State: дубль `state=` на два окна; State объявлен по месту, а не в `platform/dialogs/states.py`; два `Dialog` на одну StatesGroup; окно без `state=`. Чини в `states.py`+`dialogs.py`, прогони `pytest -k collision`. Удалил живой State → это `state-migration`, верни deprecation. |
| **storage-serialization** | в `dialog_data`/`widget_data`/`start_data` попал не-JSON (`datetime`→ISO-строка, pydantic→`model_dump(mode="json")`). `JsonMemoryStorage` в flow-тестах ловит это — добавь тест. |

Типичная цепочка причин для flow-теста: getter не отдаёт ключ, который читает `Format` → `KeyError`
при рендере (rule `dialog-architecture`).

## 4. Stale-callback у пользователя (`UnknownIntent`/`UnknownState`/`OutdatedIntent`)

Это runtime-симптом, не красный гейт. Две причины:
- **Норма после рестарта/TTL**: kit ловит и зовёт `ErrorUX` (`platform/dialogs/errors.py`) →
  подсказка `/start`. Проверь, что `AppErrorUX.on_unknown_intent`/`on_unknown_state` отвечают на
  callback (гасят «часики») и не трогают сообщение (могло быть удалено).
- **Регресс от деплоя**: вырезали/переименовали живой State → у юзеров в открытых диалогах нет на
  что приземлиться. Это `state-migration` (deprecation вместо удаления) — верни State, пометь
  deprecated. Прод-логи — в хабе: `make logs SVC=bot` в `<org>/infra`.

## 5. Граф переходов как диагностика

Падение про навигацию (не туда ведёт кнопка, тупик, недостижимое окно) — построй граф через
`preview-flow` (`render_transitions`) и посмотри глазами: лишнее ребро, недостижимый State, цикл без
выхода. Требует `aiogram_dialog[tools]` + graphviz (см. skill `preview-flow`).

## 6. Корневая причина в инфре (`tgbotkit`/kit)

- Баг в `tgbotkit`/другом kit'е `pylibinfra` → не лечи workaround'ом у себя без обсуждения. Скажи
  юзеру, предложи временный shim с `# TODO` + reference; фикс инфры — PR в `pylibinfra` через
  `infra-handoff`.
- Flaky-тест не глуши `@pytest.mark.skip` — проверь, не глобальное ли state-загрязнение
  (module-level `Dialog`-синглтоны детачатся `_parent_router = None` между тестами — см.
  `tests/_fakes/harness.py`).

## 7. Когда застрял

После двух неудачных попыток или когда каждая правка ломает другое — не наращивай патчи. Откати
свои эксперименты до состояния, где воспроизводится исходный red (чужие незакоммиченные изменения
не трогай), и скажи юзеру: гипотеза, чем её проверял, что получилось и чего не хватает. Причина всё
ещё неясна — research-spike через `plan`.

## 8. Верификация фикса

```bash
uv run pytest tests/.../test_X.py -q
make lint        # ruff + import-linter
make typecheck
```

Перед коммитом — `make check`. Тот же дефект нашёлся в соседних фичах — скажи юзеру; фикс —
отдельной задачей, не в этом коммите.

## Anti-patterns

- ❌ «Перепиши тест, чтобы проходил» — это сокрытие, не фикс.
- ❌ `@pytest.mark.skip` для flaky — корневая причина не уйдёт, всплывёт в проде.
- ❌ `--no-verify`, чтобы запушить красное: его блокирует `permissions.deny`, а гейт pre-push
  существует ровно для этого.
- ❌ `# type: ignore` / `# noqa` без кода правила и причины вместо реального фикса.
- ❌ Фикс бага без RED-теста.
- ❌ Удалить живой State, чтобы «убрать» `UnknownState` — сломаешь больше. → `state-migration`.
- ❌ Большой «while we're at it» при фиксе бага. Баг-фикс = маленький коммит; большое — отдельный план.
