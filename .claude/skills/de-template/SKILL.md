---
name: de-template
description: Развернуть форк telegram-bot-template в самостоятельный проект по stable-артефактам docs/stack — имя проекта/пакета, README, .env.example, app.py/config.py wiring, prune reference-фич (start/profile/payments/lang/notifications). Активируй когда юзер форкнул шаблон и говорит "/de-template", "разверни фундамент", "де-темплейтизируй", "убери шаблонную мету", "сделай из шаблона свой проект", или когда init-service дошёл до развёртывания (стек спроектирован и stable). Движок skill-only: и механика, и wiring — reviewable edits под этой процедурой. НЕ запускать на каноническом репозитории шаблона.
---

# Skill: de-template (движок развёртывания)

Превращает форк шаблона в проект, который ничего не помнит про `telegram-bot-template`. Читает **stable** `docs/stack` и разворачивает фундамент по секциям `Generates` артефактов. Свои фичи разворачиваются отдельно (`scaffold feature`), не здесь. Движок **skill-only**: нет committed-скрипта — и детерминированная механика (rewrite/prune/env), и doc-driven wiring идут как **reviewable edits** под этой процедурой; механика — по точным командам ниже, wiring — диффом поверх скелета, который юзер ревьюит.

Запускается **один раз** на форке. Финал — зелёный `make check` (вкл. startup-smoke) и проект без следов шаблона.

## Когда применять

- "/de-template" / "разверни фундамент" / "сделай из шаблона свой проект"
- `init-service` дошёл до развёртывания (стек sproectирован, валидатор зелёный)

## Когда НЕ применять

- Стек ещё не `stable` — сначала `stack-deep-dive` (gate ниже).
- Проект уже де-темплейтизирован (своё имя проекта, reference-фичи удалены) — обычный день через `/smartdev`.
- **Канонический репозиторий шаблона** — никогда (guard ниже). Только форк/копия.

## Gate (проверить ДО любых правок)

1. **Не канонический шаблон.** `[project] name` в `pyproject.toml` всё ещё `telegram-bot-template` И каталог — не временная копия/форк → СТОП. Запуск на самом шаблоне его уничтожит. Спроси юзера явно подтвердить, что это форк/тест-копия.
2. **Стек stable.** Сначала проверь, что kind-файлы существуют (на пустом `docs/stack` валидатор даёт ложный OK):
   ```bash
   for k in service runtime storage dialogs backends messaging auth observability config dependencies; do
     test -f "docs/stack/$k.md" || echo "STOP: docs/stack/$k.md нет — стек не спроектирован (/stack-deep-dive)"
   done
   make validate-stack-docs
   ```
   Все артефакты `status: stable`, `Generates` непусты — вход движка. ⚠️ `storage` и `dialogs` обязаны быть stable с конкретной `Generates` (без них прод падает).
3. **State stack-deep-dive чист по `**blocker**`.**
   ```bash
   grep -RlE '\*\*blocker\*\*' .claude/skills/stack-deep-dive/state/ 2>/dev/null \
     && echo "STOP: открытые blocker'ы в state stack-deep-dive — добей их сначала" \
     || echo "OK: state чист"
   ```

## Phase A — детерминированная механика

По точным командам; результат предсказуем. Каждый шаг — отдельный reviewable дифф.

### A.1 Имя проекта / package namespace

> Шаблон зависит от `pylibinfra[tgbotkit]` — **эту зависимость не трогаем** (она остаётся). Меняется только идентичность форка: `[project] name`, его метаданные и (если в `docs/stack/service.md § Generates` решено) внутренний namespace `bot` → свой.

- `[project] name` и `description` в `pyproject.toml` — из `docs/stack/service.md`.
- Если решено переименовать пакет `src/bot/` → `src/<pkg>/` (опционально; многие форки оставляют `bot` как внутренний namespace): переименуй каталог и перепиши импорты одной заменой:
  ```bash
  OLD=bot
  NEW=<package из docs/stack/service.md>   # только если переименовываем
  git mv src/$OLD src/$NEW
  git grep -lF "$OLD." -- 'src' 'tests' | xargs sed -i "s#\b$OLD\.#$NEW.#g"
  # importlinter.toml: root_package = "bot" → "<NEW>"; containers/source_modules с bot.* → <NEW>.*
  ```
- Проверь `uv sync` и `uv run python -c "import <pkg>"` — импорты резолвятся.

### A.2 README-шапка

Из `docs/stack/service.md` (имя, назначение): замени шаблонную шапку `README.md` на проектную. Убери «шаблон»/«template»/«форкни». Ссылки на `docs/reference/*` оставь (общие).

### A.3 `.env.example`

Из `docs/stack/config.md § Generates` (required+optional env с дефолтами) приведи `.env.example` к фактическому контракту проекта: `BOT_TOKEN`, `BOT_MODE`, `WEBHOOK_*` (если webhook), `REDIS_URL`, `NATS_URL`, `HTTPCLIENT_BASE_URL` (+ `*_BASE_URL`/`HTTPCLIENT_BACKENDS` при нескольких бэкендах), `OTEL_*`, `APP_ADMIN_IDS`, `BOT_I18N_*`. Секреты — только имена ключей (значения не коммить; `.claude/rules/env-local.md`).

### A.4 Strip шаблонной меты

- Удали `docs/getting-started.md` ([META] «как форкнуть шаблон»).
- `docs/contributing.md` ([META] про `.claude`-систему) — **оставь** (система наследуется форком); переформулируй «шаблон» → имя проекта при желании.
- Сбрось `.claude/plans/roadmap.md` к пустому fork-start (шапка + пустые `## Active`/`## Backlog`).
- `docs/reference/*` (architecture/dialog-mapping/observability/release/ecosystem) — **оставь** (наследуется форком; reference переезжает в проект); `getting-started.md` удаляется, см. выше.

### A.5 Prune reference-фич

`start`/`profile`/`payments`/`lang`/`notifications` — учебные образцы. Удаляются по полному чеклисту — см. **`references/prune.md`** (что оставить почти всегда: `start` как корневой ROOT и `lang`, если нужен i18n). Делай **после** того как свои фичи спроектированы (флоу через `/dialog-deep-dive`) и сгенерированы (`scaffold feature`) — иначе теряешь живой образец гексагона.

## Phase B — doc-driven wiring

Артефакты `runtime`/`storage`/`dialogs`/`backends`/`messaging`/`auth`/`observability` разворачиваются как **reviewable diff поверх скелета** — `app.py` (единый composition root: `ExtensionProvider` — точки расширения tgbotkit `RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/resolver — и `build_container` — список провайдеров), `config.py` (`*Config`, `BackendsConfig`, i18n-каталоги, дефолт-локаль), `pkg/http_client/*`, `platform/*`. Процедура и маппинг `Generates`→код — см. **`references/wiring.md`**.

## Verify

```bash
make check           # ruff + import-linter + mypy + pytest
uv run pytest -k collision   # startup-smoke: setup_dialogs без коллизий StatesGroup
```

Зелёный `make check` + чистый startup-smoke на развёрнутом форке — главный критерий движка. (У бота нет `make build` go-style — критерий «компилируется» = контейнер собирается и `setup_dialogs` проходит.)

## Anti-patterns

- ❌ Запуск на каноническом шаблоне (см. Gate) — уничтожает шаблон.
- ❌ Трогать зависимость `pylibinfra[tgbotkit]` — она остаётся, меняется только идентичность форка.
- ❌ Старт до `stable`-артефактов (особенно `storage`/`dialogs`) — движку не из чего разворачивать.
- ❌ Prune reference-фич раньше, чем свои спроектированы/сгенерированы.
- ❌ Удалить ВСЕ фичи, оставив бота без корневого ROOT-диалога — `/start` некуда вести.
- ❌ Wiring «по памяти» вместо `Generates`-секций — артефакты source of truth.
- ❌ Коммит значений секретов в `.env.example` (только имена ключей).

## См. также

- `references/prune.md` — удаление reference-фич (полный чеклист).
- `references/wiring.md` — doc-driven wiring артефактов в `app.py`/`config.py`/`pkg/http_client/*`.
- `docs/stack/README.md` — контракт артефактов и их `Generates`.
- `.claude/skills/init-service/SKILL.md` — оркестратор, чейнит сюда.
