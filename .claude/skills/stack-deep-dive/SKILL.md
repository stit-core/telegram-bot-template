---
name: stack-deep-dive
description: Углублённая интерактивная проработка платформенных артефактов бота в `docs/stack/` (service · runtime · storage · dialogs · backends · messaging · auth · observability · config · dependencies, опц. i18n) — единственная точка входа для **проектирования стека**. Ведёт сессию через серию структурированных раундов `AskUserQuestion` (без монологов и догадок), фиксирует рабочее состояние в собственной памяти `state/`. Активируй когда архитектор проектирует/добивает стек, говорит "/stack-deep-dive", "спроектируем стек", "добьём stack-артефакты", приносит сырьё (compose.yaml, текущий app.py) под платформенный разбор, или когда `/init-service` дошёл до шага стека. Точечные правки **уже стабильного** артефакта (поменялся env / добавился subject) идут через прямой Edit, не сюда.
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
| `storage` ⚠️ | Redis (**НЕ Memory**): key-builder `with_destiny`, TTL, `RedisEventIsolation`, что кладётся в FSM/dialog_data (только JSON), dedup, identity-link |
| `dialogs` ⚠️ | карта диалогов/флоу, корневой `LaunchMode.ROOT`, `/start`=`RESET_STACK`, error-handlers (`ErrorUX`), StatesGroup-инвентарь |
| `backends` | именованные бэкенды (`BackendsConfig`), base_url, таймауты, breaker, auth, идемпотентность мутаций |
| `messaging` | NATS-subjects/streams/durable для push-уведомлений, JetStream vs core |
| `auth` | identity-link tg↔backend, admin-allowlist (`APP_ADMIN_IDS`), initData-валидация (WebApp) |
| `observability` | метрики `tg_*`/`biz_tg_*`, трейс апдейта (`tg.update`), health/ready |
| `config` (роллап) | env/Vault-поверхность (`BOT_*`/`REDIS_URL`/`NATS_URL`/`HTTPCLIENT_*`/`OTEL_*`/`APP_*`), secret-карта |
| `dependencies` (роллап) | киты `pylibinfra`, внешние runtime-deps (Redis/NATS/бэкенды) и их деградация |
| `i18n` (опц.) | локали, движок (`fluent.runtime`/`.ftl`), middleware, дефолт-локаль, фича смены языка |

`storage` и `dialogs` — **критичные**: без них прод падает на первом деплое (Memory-storage теряет диалоги при рестарте/мультиинстансе; кривой State-граф валит `setup_dialogs`). Их `Generates` обязаны быть конкретны.

## Главный ритм: AskUserQuestion

Скилл — **интервьюер архитектора**, не редактор. Партнёр — архитектор бота (тот, кто принимает платформенные решения: runtime, киты, env, subjects, capacity); его решения дословно ложатся в артефакт, скилл их **не сочиняет**. Каждый шаг — раунд `AskUserQuestion` (до 4 вопросов за раунд) → ответ → пишем в артефакт через `Edit` → следующий раунд.

**Никаких альтернатив этому ритму нет.** В частности:

- ❌ Длинный prose-ответ «вот как я бы спроектировал X» вместо вопросов.
- ❌ «По умолчанию» применить решение, потому что «в других ботах так».
- ❌ Молча выставить «обычный» env (`BOT_MODE=polling`) — это решение архитектора, спрашиваем.
- ❌ Один `AskUserQuestion` с >4 вопросами — лимит инструмента, он режет молча.
- ❌ Скопить ответы «запишу в конце волны» — пиши после **каждого** раунда, иначе теряется при `/clear`.
- ✅ Сомневаешься, polling или webhook → лишний раунд вопросов, а не догадка.

Anti-pattern'ы и enum'ы — даёшь как опции; имена env, subject'ы, package path, числа capacity — только через свободную форму (Other). **Никогда** не предлагать конкретные env-имена/subject'ы как «правильный вариант» от себя.

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
8. **observability** — метрики `tg_*`/`biz_tg_*`, trace, health.
9. **i18n** (опц.) — локали, движок, middleware.
10. **config** (роллап) — required/optional env, секреты — собирает env'ы подключённых китов + решений 1–9.
11. **runtime** (роллап) — polling/webhook, инстансы, какие подсистемы поднимаются, shutdown.

Юзеру в начале: «иду фундамент → роллап, начну с service; скажи если хочешь прыгнуть в конкретный kind».

## Контракт `draft → stable`

Чек-лист после каждой правки (все ✅ → предложить промоушн через `AskUserQuestion`, **скилл не повышает сам**):

1. **Обязательные H2 заполнены** непустым осмысленным содержимым, без placeholder'ов.
2. **Секция `Generates` непуста и конкретна** — контракт для `de-template`: перечисляет конкретные пути в коде (`config.py`/`app.py`/`pkg/http_client/*`/`platform/*`) и/или env-имена. Пустая/`TBD` `Generates` = артефакт бесполезен движку.
3. **Cross-kind sync согласован.** Решения kit-артефактов (`backends`/`messaging`/`auth`/`observability`/`dependencies`/`storage`) роллапятся в `config` (env+секреты) и `runtime` (подсистемы, shutdown). `auth` добавил `APP_ADMIN_IDS` → он в `config § Required env`.
4. **Валидатор зелёный** — `make validate-stack-docs`.
5. **Тест-критерий kind'а подтверждён** в сессии.
6. **State чист по `**blocker**`.**
7. **(для `storage`/`dialogs`) специфичный критерий:** `storage` — Redis (не Memory), TTL заданы, `with_destiny` отмечен; `dialogs` — корневой ROOT назван, `/start`=RESET_STACK, error-handlers перечислены, нет двух Dialog на одну StatesGroup.

## Память `state/<kind>.md`

- Один файл на kind (стек — singleton); без вложений.
- Секции (любая опц.): `## Открытые вопросы` (опц. `**blocker**`), `## Платформенные решения`, `## Что копать дальше`.
- Все пусты → файл удалить. **Forward-only** (без «было/стало», дат сессий).
- Лежит в `.claude/skills/stack-deep-dive/state/` и **коммитится** — общая проектная память.

## Cross-kind sync

После правки kit-артефакта (`backends`/`messaging`/`auth`/`observability`/`dependencies`/`storage`) — скилл добавляет роллап в `config`/`runtime` черновиком и через `AskUserQuestion` показывает дифф «вот что добавилось — окей?»:

- `backends` → `config § Required` (`HTTPCLIENT_BASE_URL` / `*_BASE_URL` per именованный бэкенд, таймауты), `dependencies § External` (бэкенды).
- `storage` → `config § Required` (`REDIS_URL`), `runtime § Lifecycle` (`RedisEventIsolation` при webhook ≥2).
- `messaging` → `config § Required` (`NATS_URL`, subjects/streams), `runtime § Entrypoints` (поднимаем ли notifications-runner), `dependencies § External` (NATS).
- `auth` → `config § Required/Secrets` (`APP_ADMIN_IDS`, `BOT_TOKEN`).
- `observability` → `config § Optional` (`OTEL_*`), `dependencies § kit'ы` (telemetry/bizmetric).

## Завершение сессии

1. Перечислить затронутые артефакты (заведены/углублены/промоутнуты).
2. Перечислить нерешённые `**blocker**` (читая `state/`).
3. `make validate-stack-docs` — подтвердить зелёный.
4. Следующий шаг:
   - **Онбординг** (из `/init-service`): все stable → дальше `/de-template`.
   - **Отдельно** (стек жил, поменялся): артефакты — актуальный source of truth; правка задевает инфра-поверхность (env/секрет/NATS-subject/runtime-dep) → `/infra-handoff`.

## Запреты

- Не редактировать артефакты вслепую — всегда сначала `Read`.
- Не выдумывать платформенные решения. Anti-patterns как опции — да; имя env/subject/path/число — нет.
- Не оставлять `Generates` пустым/`TBD` — вход `de-template`.
- Не повышать `draft → stable` без явного подтверждения архитектора.
- Не понижать `stable → draft` сам.
- Не оставлять `storage`=Memory или `dialogs` без error-handlers — это гарантированный прод-инцидент.
- Не игнорировать cross-kind sync.
- Не аккумулировать историю в `state/` — forward-only.
- Не задавать >4 вопросов одним AskUserQuestion.
