# Аудит _toolchain — ground-truth по тулчейну обоих репо

Дата прогона: 2026-06-07. Окружение: Python **3.13.5** в обоих `.venv` (`.python-version = 3.13`),
`uv` доступен, Docker для integration не поднимался.

## Что смотрел

- Гейт шаблона `telegram-bot-template` (`make check` целиком + покрытие `make test-cover`).
- Гейт `pylibinfra` (Makefile нет — гонял по отдельности через `uv`: ruff format/check, mypy, pytest+cov).
- Счётчики по `src` обоих репо: `# type: ignore`, `cast(`, `Any`, `# noqa`, `TODO/FIXME/XXX/HACK`, `print(`.
- Версии ключевых пинов из `uv.lock` обоих репо + корректность git-пина `pylibinfra`.
- Раскладку тестов и маркеров (что реально гоняется в гейте, что Docker-gated).

---

## Сильные стороны

### Шаблон — гейт зелёный целиком, без послаблений

`cd telegram-bot-template && make check` → **EXIT 0**, всё чисто:

- `ruff format --check` — 91 файл уже отформатирован.
- `ruff check .` — All checks passed (профиль строгий: `S`/bandit, `ASYNC`, `TID`, `T20`=запрет print, banned-api на `logging`).
- `lint-imports` (`importlinter.toml`) — **3/3 контракта KEPT, 0 broken** (87 файлов, 283 зависимости): «Слои внутри фичи (DIP)», «Независимость фич», «Чистое ядро не импортит инфру».
- `mypy src` (strict + pydantic-плагин) — Success, **71 source files**, no issues.
- `pytest -m "not integration"` — **32 passed** за ~2.3s.

### Шаблон — кодовая гигиена образцовая

Счётчики по `src/bot` (71 .py):

| метрика | шаблон |
|---|---|
| `# type: ignore` | **0** |
| `cast(` | **0** |
| `# noqa` | **0** |
| `TODO/FIXME/XXX/HACK` | **0** |
| `print(` | **0** (T20 держит) |
| `Any` (аннотации) | 20 |

Ни одного подавления типов/линтера, ни одного техдолг-маркера. Все 20 `Any` — на легитимных
границах: `dict[str, Any]` для JSON-тел backend (`platform/backend/client.py:25,30,35,45,63`),
`**kwargs: Any` в getter'ах aiogram_dialog (`features/*/getters.py`), `data.get("event_from_user")`
из middleware-контекста (`platform/identity/provider.py:29`). Это не «дыры», а transport/JSON-граница.

### pylibinfra — гейт зелёный

- `ruff format --check` — 253 файла отформатированы.
- `ruff check .` — All checks passed.
- `mypy src` (strict) — Success, **176 source files**, no issues.
- `pytest -m "not integration"` — **242 passed, 23 deselected** (integration), 13 warnings, ~6s.

### Версии рантайма синхронны между репо

Ключевые пины **совпадают байт-в-байт** в обоих `uv.lock` (бот тянет их транзитивом через
`pylibinfra[tgbotkit]`):

| пакет | версия | pyproject-ограничение |
|---|---|---|
| aiogram | **3.28.2** | `>=3.28,<4` |
| aiogram-dialog | **2.6.0** | `>=2.6,<3` |
| dishka | **1.10.1** | `>=1.10,<2` |
| redis | **8.0.0** | `>=8,<9` |
| httpx | **0.28.1** | `>=0.28,<1` |
| pydantic | **2.13.4** | `>=2.13,<3` |
| fluent-runtime | **0.4.0** | `>=0.4,<0.5` |
| ruff | **0.15.16** | `>=0.15` (оба) |
| fastapi | 0.136.3 | `>=0.136,<1` |
| structlog | 26.1.0 | `>=26.1,<27` |
| opentelemetry-sdk | 1.42.1 | `>=1.42,<2` |
| nats-py | 2.15.0 | `>=2.15,<3` |

### git-пин pylibinfra корректен и воспроизводим

Шаблон пинит `pylibinfra = { git = "...", rev = "3eebcba" }`. Проверено: `3eebcba` —
`feat(tgbotkit): новый kit` и совпадает с текущим `HEAD` pylibinfra; `git ls-tree 3eebcba` содержит
`src/pylibinfra/tgbotkit`. Пин указывает ровно на ревизию с tgbotkit, рабочее дерево pylibinfra
чистое (`git status` пусто). Lock в шаблоне фиксирует полный хеш
`3eebcba6076c2ecc92bdf7ea3394ba87ddd2c52e`.

---

## Находки

### [SEV=low | CAT=build | CONF=high] mypy разъезжается по мажорной версии между репо

`telegram-bot-template/uv.lock` фиксирует **mypy 1.20.2** (pyproject `mypy>=1.18,<2`), а
`pylibinfra/uv.lock` — **mypy 2.1.0** (pyproject `mypy>=2.1,<3`). Оба гейта зелёные, но **общий API
tgbotkit type-check'ается под разными мажорами mypy**: в шаблоне линия 1.x, в ките — 2.x. Риск —
расхождение поведения strict-проверок (mypy 2.0 нёс ужесточения дефолтов); зелёный mypy в ките не
гарантирует зелёный в шаблоне на том же коде и наоборот. Доказательство: `pyproject.toml:21`
(шаблон) vs `pylibinfra/pyproject.toml:90`. Fix: согласовать диапазон (поднять шаблон на `>=2.1,<3`)
и перелочить, либо явно зафиксировать в доке причину расхождения.

### [SEV=low | CAT=build | CONF=high] pylibinfra пинится на «голый» commit, не на release-тег

`telegram-bot-template/pyproject.toml:35-36` пинит инфру по `rev = "3eebcba"`, а комментарий
(строки 32-34) сам признаёт: единственный тег `v0.1.0` — это bootstrap ДО tgbotkit, тег на ревизии
с tgbotkit ещё не выпущен. Это рабочий forward-only TODO, не баг: пин воспроизводим (полный хеш в
lock), но контракт «бот пинится как go-сервис на версию» держится на loose-коммите вместо
семвер-тега — откат/диагностика версий инфры менее очевидны. Fix: тегнуть pylibinfra на ревизии с
tgbotkit и свапнуть `rev` → `tag`.

### [SEV=info | CAT=testing | CONF=high] В шаблоне нет ни одного integration/e2e-теста

Маркеры `integration`/`e2e` объявлены (`pyproject.toml:107-112`), но `pytest -m integration
--collect-only` → **0 собрано, 32 deselected**: все 32 теста гоняются в обычном `make check`. Это
не дыра в гейте (наоборот, весь сюит запускается без Docker), но `make test-integration` сейчас
гонять нечего — заявленный testcontainers-слой (redis/nats) в шаблоне пуст. Для сравнения:
pylibinfra имеет 23 integration-теста из 265. Покрытие шаблона 84% — это полный доступный сюит, а
не урезанный без Docker.

### [SEV=info | CAT=testing | CONF=high] Покрытие шаблона 84%, провалы — на UI/error-edge

`make test-cover`: **TOTAL 84%** (833 stmts, 113 miss, 58 branch). Зелёное ядро/policy/usecase;
просадки сконцентрированы на UI-рендере и error-хендлинге, которые тестируются flow-тестами лишь
частично:

| модуль | % | что не покрыто |
|---|---|---|
| `__main__.py` | 0% | entrypoint (3-8) — by design не тестируется |
| `features/profile/views.py` | 32% | `to_window` маппинг (24-32) |
| `platform/dialogs/errors.py` | 36% | глобальный error-handler веток (20-38) |
| `features/lang/usecase.py` | 47% | (15,18,21-24) |
| `features/payments/handlers.py` | 47% | handler-ветки (36-46,53-57,67-73) |
| `features/notifications/__init__.py` | 64% | wiring подписчика (18-22) |
| `features/payments/gateway.py` | 67% | mapping/ошибки gateway (23-37) |
| `features/profile/gateway.py` | 70% | (23-26,37-40) |

`platform/backend/client.py` — 86% (непокрыто: `52,55-56,62,70` — ветки декодирования/ошибок).
Это reference-фичи (start/profile/payments/lang/notifications), часть будет вырезана `/de-template`,
так что низкое покрытие views/handlers не критично, но error-handler `dialogs/errors.py:36%` —
инфра-сеть последней надежды, и она недотестирована.

### [SEV=info | CAT=types | CONF=high] pylibinfra — 13 type:ignore / 1 cast / 10 noqa, все обоснованы

Счётчики по `src/pylibinfra` (176 .py):

| метрика | pylibinfra |
|---|---|
| `# type: ignore` | 13 |
| `cast(` | 1 |
| `# noqa` | 10 |
| `Any` | 85 (из них 26 в tgbotkit, 18 в logkit) |
| `TODO/FIXME` | 0 |
| `print(` | 0 |

Все 13 `type: ignore` узко-кодированы и оправданы untyped-сторонними либами: `[import-untyped]` на
`asyncpg`/`testcontainers.*`/`yoyo` (`pgkit/*`, `testkit/*`), плюс точечные
`[no-untyped-call]`/`[arg-type]`/`[no-any-return]` (`pgkit/pool.py:54`, `httpkit/module.py:70`,
`pgkit/transactor.py:32-33`). `warn_unused_ignores = true` проходит → мёртвых ignore нет. Все 10
`noqa` — bandit/naming-подавления с обоснованием (`S105`/`S311`/`S104` в тест-хелперах и
jitter/bind, `N818` на Go-стиль sentinel-ошибках). 0 `print`, 0 техдолг-маркеров. Чисто для инфра-либы.

### [SEV=info | CAT=toolchain | CONF=high] pylibinfra не имеет ни Makefile, ни import-linter

В отличие от шаблона, у pylibinfra нет `Makefile` (гейт собирается вручную) и нет import-linter
(контракты слоистости между китами не форсятся машинно — только ruff+mypy+pytest). Для библиотеки
из 19 китов отсутствие контракта на cross-kit-изоляцию — потенциальная брешь дисциплины, но это вне
зоны toolchain-гейта как такового; фиксирую как факт. CONTRIBUTING.md в ките есть.

### [SEV=info | CAT=build | CONF=medium] Целевая версия py312 при рантайме py313

Оба `pyproject.toml`: `target-version = "py312"` / `python_version = "3.12"` при
`requires-python = ">=3.12"`, но оба `.venv` и `.python-version` — **3.13.5**. Это валидно (нижняя
граница проверяется консервативно), но гейт реально исполняется на 3.13, а типы/ruff целятся в 3.12
— py313-специфичные регрессии теоретически могут проскочить мимо линтера. Низкий риск, фиксирую.

---

## Ответ на вопросы заказчика (в области toolchain)

1. **Строить нормальных ботов?** Со стороны тулчейна — да. Гейт шаблона строгий и **полностью
   зелёный** (format+lint+import-linter 3/3+mypy strict+тесты), кодовая гигиена образцовая
   (0 ignore/cast/noqa/print/TODO в шаблоне). Инфра-либа тоже зелёная (242 теста). Барьер качества
   реальный, не декоративный.

2. **Гибкость с точки зрения тулчейна?** Пины жёсткие и синхронные (хорошо для воспроизводимости),
   контракт «бот ↔ ревизия инфры» через git-пин держится. Минус гибкости: бот завязан на **один**
   git-rev pylibinfra, а import-linter форсит изоляцию фич — это про дисциплину, не про тулчейн как
   таковой (см. архитектурные области аудита).

3. **Про несколько backend-клиентов** — это вопрос архитектуры `platform/backend`, не тулчейна; в
   моей области доказательств за/против негибкости нет. Замечу лишь: с точки зрения типов
   `platform/backend/client.py` весь на `dict[str, Any]` (JSON-граница), так что типобезопасность
   ответов разных API на этом слое отсутствует by design — это переносит цену гибкости на ручную
   валидацию в gateway-адаптерах.

**Итог области:** тулчейн обоих репо в хорошем состоянии, оба гейта проходят. Единственный реальный
сигнал — **разъезд mypy 1.x (шаблон) vs 2.x (kit)** на общем API tgbotkit, плюс пин инфры на
loose-commit вместо тега. Остальное — info/наблюдения.
