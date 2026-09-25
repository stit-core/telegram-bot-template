---
name: stack-deep-dive
description: Проектирование платформы бота — интерактивная проработка артефактов docs/stack (service · runtime · storage · dialogs · backends · messaging · auth · observability · config · dependencies, опц. i18n) раундами AskUserQuestion до status stable с непустой секцией Generates; единственная точка входа для проектирования стека, рабочая память — state/ скилла. Используй, когда архитектор проектирует или добивает стек (/stack-deep-dive), приносит сырьё под платформенный разбор (compose-файл, текущий app.py/config.py) или /init-service дошёл до шага стека. Точечная правка уже stable-артефакта (поменялся env, добавился subject) — прямой Edit, не сюда.
---

# Skill: stack-deep-dive

Проектирование платформы бота. Превращает минимальные драфты артефактов `docs/stack/` (frontmatter + placeholder-H2) в полные `status: stable` артефакты с непустой секцией **Generates** в каждом.

Где диалоги/флоу (скилл `/dialog-deep-dive`) отвечают «какой пользовательский сценарий», этот скилл — «на какой платформе бот крутится»: polling vs webhook, Redis-проводка, какие бэкенды, NATS-subjects push-уведомлений, identity-link, как версионируется и деплоится **один** образ.

Это **source of truth и вход для `de-template`**. Секция `Generates` каждого артефакта описывает, что из него родится в коде (`config.py`-env, точки расширения `ExtensionProvider` в `app.py`, `pkg/http_client/*`-клиенты, `platform/*`-провайдеры, нужные kit'ы `pylibinfra`). Канон артефактов и обязательных H2 — `docs/stack/README.md`. Скилл их не дублирует, а исполняет.

В онбординг-флоу `init-service` чейнит сюда после проектирования флоу диалогов, затем — `de-template`.

## Бот-набор kind'ов

| kind | содержание |
|---|---|
| `service` | имя бота, module/package path, назначение, владелец, SLO, версионирование (один образ) |
| `runtime` | **polling vs webhook**, инстансы (webhook ≥2 + `RedisEventIsolation`), graceful shutdown, какие фоновые подсистемы поднимаются (notifications-runner, jobs) |
| `storage` ⚠️ | Redis (**не** Memory): key-builder `with_destiny`, TTL, `RedisEventIsolation`, что кладётся в FSM/dialog_data (только JSON), dedup, identity-link |
| `dialogs` ⚠️ | карта диалогов/флоу, корневой `LaunchMode.ROOT`, `/start`=`RESET_STACK`, error-handlers (`ErrorUX`), StatesGroup-инвентарь |
| `backends` | именованные бэкенды (`BackendsConfig`), base_url, таймауты, breaker, auth, идемпотентность мутаций |
| `messaging` | NATS-subjects/streams/durable для push-уведомлений, JetStream vs core |
| `auth` | identity-link tg↔backend, admin-allowlist (`APP_ADMIN_IDS`), initData-валидация (WebApp) |
| `observability` | логи (logkit → stdout), бизнес-логи, health/ready-эндпоинты (httpkit) |
| `config` (роллап) | env-поверхность (`BOT_*`/`REDIS_URL`/`NATS_URL`/`HTTPCLIENT_*`/`APP_*`), secret-карта |
| `dependencies` (роллап) | киты `pylibinfra`, внешние runtime-deps (Redis/NATS/бэкенды) и их деградация |
| `i18n` (опц.) | локали, движок (`fluent.runtime`/`.ftl`), middleware, дефолт-локаль, фича смены языка |

`storage` и `dialogs` — **критичные**: без них прод падает на первом деплое (Memory-storage теряет диалоги при рестарте/мультиинстансе; кривой State-граф валит `setup_dialogs`). Их `Generates` обязаны быть конкретны.

## Главный ритм: AskUserQuestion

Скилл — **интервьюер архитектора**, не редактор. Партнёр — архитектор бота: платформенные решения (runtime, киты, env, subjects, capacity) принимает он, их дословно фиксирует артефакт, а скилл их не сочиняет — даже «обычные» (`BOT_MODE=polling`) или «как в других ботах». Каждый шаг — раунд `AskUserQuestion` (до 4 вопросов — лимит инструмента) → ответ → запись в артефакт через `Edit` сразу после раунда, чтобы ответы пережили `/clear` → следующий раунд. Сомнение (polling или webhook?) — повод для ещё одного раунда, а не для догадки или монолога «как бы я спроектировал».

Anti-pattern'ы и enum'ы даёшь как опции; имена env, subject'ы, package path, числа capacity — свободной формой (Other): конкретное имя от себя как «правильный вариант» подменило бы решение архитектора.

## Точки входа

| вызов | поведение |
|---|---|
| `/stack-deep-dive` | сводка состояния артефактов + AskUserQuestion: что углубить / что заводить |
| `/stack-deep-dive <kind>` | завести/углубить артефакт (режим A — нет файла, C — есть) |
| `/stack-deep-dive <свободный текст / приложение>` | сырьё (compose.dev.yml, текущий app.py/config.py, заметка про env) → разбор (режим B) |

## Что делать сразу при запуске

1. Прочитать `docs/stack/README.md` — освежить канон (kinds, обязательные H2, контракт `Generates`).
2. Args пустые — сводка + `AskUserQuestion` с выбором.
3. Args = kind — определить режим (A/C), вести по нему.
4. Args = сырьё — режим B.

## Сводка состояния

1. `ls docs/stack/` — какие файлы есть.
2. Для каждого: frontmatter (`status`, `kind`) + H2; заполненность обязательных секций.
3. Прогнать `make validate-stack-docs`. Зелёный + все stable → выйти. ⚠️ Перед валидатором проверь, что kind-файлы **существуют** — на пустом `docs/stack/` (только `_templates/`+README) валидатор даёт ложный OK.
4. Прочитать `state/` — `## Открытые вопросы`; `**blocker**` приоритетны.
5. Сжатая карта в чат (таблица kind | status | H2 заполнено | дыры).
6. Через `AskUserQuestion` — что копать дальше.

## Inside-out волны (порядок копания)

Запоминается в скилле, у архитектора не спрашивается. Фундамент → производное; роллапы (`config`, `runtime`) — последними:

1. **service** — идентичность: имя, package path, версионирование, один образ.
2. **dependencies** — какие киты `pylibinfra`, внешние runtime-deps (Redis/NATS/бэкенды), ёмкость.
3. **storage** ⚠️ — Redis: key-builder `with_destiny`, TTL, isolation, что в dialog_data.
4. **backends** — бэкенды, base_url, таймауты, breaker, auth, идемпотентность.
5. **dialogs** ⚠️ — карта флоу, корневой ROOT, error-handlers, StatesGroup-инвентарь.
6. **messaging** — push-subjects/streams/durable, JetStream vs core.
7. **auth** — identity-link, admin-allowlist, initData.
8. **observability** — логи, бизнес-логи, health/ready-эндпоинты.
9. **i18n** (опц.) — локали, движок, middleware.
10. **config** (роллап) — required/optional env, секреты — собирает env'ы подключённых китов + решений 1–9.
11. **runtime** (роллап) — polling/webhook, инстансы, какие подсистемы поднимаются, shutdown.

Юзеру в начале: «иду фундамент → роллап, начну с service; скажи если хочешь прыгнуть в конкретный kind».

## Контракт `draft → stable`

Чек-лист после каждой правки (все ✅ → предложить промоушн через `AskUserQuestion`, **скилл не повышает сам**):

1. **Обязательные H2 заполнены** непустым осмысленным содержимым, без placeholder'ов.
2. **Секция `Generates` непуста и конкретна** — контракт для `de-template`: перечисляет конкретные пути в коде (`config.py`/`app.py`/`pkg/http_client/*`/`platform/*`) и/или env-имена. Пустая/`TBD` `Generates` = артефакт бесполезен движку.
3. **Cross-kind sync согласован.** Решения kit-артефактов (`backends`/`messaging`/`auth`/`observability`/`dependencies`/`storage`) роллапятся в `config` (env+секреты) и `runtime` (подсистемы, shutdown). `auth` добавил `APP_ADMIN_IDS` → он в env-секции `config` (`Required`/`Optional` — по наличию дефолта).
4. **Валидатор зелёный** — `make validate-stack-docs`.
5. **State чист по `**blocker**`.**
6. **(для `storage`/`dialogs`) специфичный критерий:** `storage` — Redis (не Memory), TTL заданы, `with_destiny` отмечен; `dialogs` — корневой ROOT назван, `/start`=RESET_STACK, error-handlers перечислены, нет двух Dialog на одну StatesGroup. Без этого прод падает на первом деплое.

## Память `state/<kind>.md`

- Один файл на kind (стек — singleton); без вложений.
- Секции (любая опц.): `## Открытые вопросы` (опц. `**blocker**`), `## Платформенные решения`, `## Что копать дальше`.
- Все пусты → файл удалить. **Forward-only** (без «было/стало», дат сессий).
- Лежит в `.claude/skills/stack-deep-dive/state/` и **коммитится** — общая проектная память.

## Cross-kind sync

После правки kit-артефакта (`backends`/`messaging`/`auth`/`observability`/`dependencies`/`storage`) — скилл добавляет роллап в `config`/`runtime` черновиком и через `AskUserQuestion` показывает дифф «вот что добавилось — окей?»:

- `backends` → env `config` (`HTTPCLIENT_BASE_URL` / `*_BASE_URL` per именованный бэкенд, таймауты), `dependencies § External runtime-deps` (бэкенды).
- `storage` → env `config` (`REDIS_URL`), `runtime § Health & lifecycle` (`RedisEventIsolation` при webhook ≥2).
- `messaging` → env `config` (`NATS_URL`, `NATS_JS_*`), `runtime § In-process` (поднимаем ли notifications-runner), `dependencies § External runtime-deps` (NATS).
- `auth` → env `config` (`APP_ADMIN_IDS`) и `config § Secrets` (`BOT_TOKEN`).
- `observability` → `runtime § Health & lifecycle` (health-порт `HTTP_ADDR` занят в любом режиме: `/health`, `/ready`).

## Завершение сессии

1. Перечислить затронутые артефакты (заведены/углублены/промоутнуты).
2. Перечислить нерешённые `**blocker**` (читая `state/`).
3. `make validate-stack-docs` — подтвердить зелёный.
4. Следующий шаг:
   - **Онбординг** (из `/init-service`): все stable → дальше `/de-template`.
   - **Отдельно** (стек жил, поменялся): артефакты — актуальный source of truth; правка задевает инфра-поверхность (env/секрет/NATS-subject/runtime-dep) → `/infra-handoff`.

## Границы

Статус артефакта меняет только архитектор: промоушн `draft → stable` — после его явного «да» в
`AskUserQuestion`, понижение `stable → draft` — тоже по его решению; скилл предлагает, но не
переключает сам.
