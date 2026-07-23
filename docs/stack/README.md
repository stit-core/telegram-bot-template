# Stack artifacts

Дизайн платформы/стека бота — **первичный source of truth** и **вход для skill `de-template`**.
Где флоу диалогов (карта `dialogs.md` ниже) отвечает на «как пользователь идёт по сценарию», а
домены/дизайн живут в соседнем стратегии-репо, `docs/stack/` отвечает на «на какой платформе бот
крутится»: какой runtime (polling/webhook), какое хранилище, какие env, какие kit'ы pylibinfra,
какие NATS-subjects, как версионируется и деплоится образ.

Артефакты — singleton по kind, заполняются через `/stack-deep-dive`, валидируются
`make validate-stack-docs`.

## Kinds

| kind | файл | что описывает |
|---|---|---|
| `service` | `service.md` | идентичность: имя, package path, версионирование, образ |
| `runtime` | `runtime.md` | режим рантайма (polling/webhook), что крутится в процессе (диалоги/notifications/jobs), health |
| `storage` | `storage.md` | Redis: FSM/dialog storage, TTL, ключи, `with_destiny` |
| `dialogs` | `dialogs.md` | карта флоу: `StatesGroup`-инвентарь, корневой ROOT-диалог, error-handlers; per-feature `## Flow:` |
| `backends` | `backends.md` | HTTP-бэкенды (`pkg/http_client`): internal/external, base_url, именованные клиенты, идемпотентность |
| `messaging` | `messaging.md` | NATS-subjects (consumed подписчиками), JetStream, доставка, идемпотентность |
| `auth` | `auth.md` | identity (`BotIdentity`), роли, admin-allowlist, identity-link к бэкенду |
| `observability` | `observability.md` | логи (logkit → stdout), trace-correlation, биз-логи, health |
| `config` | `config.md` | required/optional env, секреты (через env), валидация, инвентарь `*Config` |
| `dependencies` | `dependencies.md` | пин `pylibinfra[tgbotkit]`, kit'ы, внешние runtime-deps, ёмкость |
| `i18n` *(опц.)* | `i18n.md` | каталог переводов, дефолт-локаль, resolver, `.ftl`-ресурсы |

Каждый артефакт обязан иметь секцию **Generates** — что из него родится в коде. Это контракт для
`de-template`: маппинг живёт рядом с источником, не отдельным файлом.

## Frontmatter

```yaml
id: stack.service      # stack.<name>
kind: service          # один из kinds выше
name: service          # == basename файла без .md
status: draft          # draft → stable (через валидатор)
```

## Workflow

1. Скопировать `_templates/<kind>.md` → `docs/stack/<kind>.md` (первый заход на kind).
2. `/stack-deep-dive` — заполнить волнами вопросов фундамент→роллап.
3. `make validate-stack-docs` зелёный + `Generates` непуст → промоушн `status: draft → stable`.
4. `/de-template` читает stable-артефакты и разворачивает фундамент по секциям `Generates`.

## Gate

`/de-template` не запускается, пока не все артефакты `stable` и валидатор не зелёный. ⚠️ `storage`
(Redis, не Memory) и `dialogs` (флоу + error-handlers) — критичны: без них прод падает. Зеркалит
дисциплину дизайна (стратегия-репо): код разворачивается только из stable-артефактов, не из draft.
