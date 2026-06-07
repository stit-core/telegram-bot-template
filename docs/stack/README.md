# Stack artifacts

Дизайн платформы/стека бота — **первичный source of truth** и **вход для skill `de-template`**.
11 singleton-артефактов (по одному на kind), заполняются через `/stack-deep-dive`, промоутятся в
`status: stable`.

Где фичи отвечают на «какая бизнес-логика», `docs/stack/` отвечает на «на какой платформе она
крутится»: какой runtime (polling/webhook), какой Redis, какие диалоги, какие бэкенды/subjects,
как версионируется и деплоится образ. Поскольку **вся инфра в `pylibinfra[tgbotkit]`**, эти
артефакты описывают в основном **значения конфига** kit'ов и **регистрацию** бизнес-точек, а не
саму инфра-проводку.

> Это **шаблонные** артефакты: на каноническом шаблоне они — структура + плейсхолдеры + пример.
> Потребитель форка заполняет их под свой бот (skill `/stack-deep-dive`).

## Kinds

| kind | файл | что описывает | критичность |
|---|---|---|---|
| `service` | `service.md` | идентичность: имя, пакет, версионирование, образ | |
| `runtime` | `runtime.md` | polling vs webhook, инстансы, graceful shutdown | |
| `storage` | `storage.md` | Redis (НЕ Memory!), префиксы, TTL, сериализация, isolation | **критичный** |
| `dialogs` | `dialogs.md` | карта диалогов/флоу, `StatesGroup`, `LaunchMode.ROOT`, error-handlers | **критичный** |
| `backends` | `backends.md` | бэкенды: base_url, таймауты, breaker, auth, идемпотентность | |
| `messaging` | `messaging.md` | NATS-subjects (push-уведомления), JetStream vs core | |
| `auth` | `auth.md` | identity-link tg↔backend, admin-allowlist, initData-валидация | |
| `observability` | `observability.md` | метрики `tg_*`/`biz_tg_*`, трейс апдейта, health | |
| `config` | `config.md` | env/Vault-поверхность, secret-карта | |
| `dependencies` | `dependencies.md` | внешние зависимости и их деградация | |
| `i18n` | `i18n.md` | локали, движок (fluent), middleware, дефолт-локаль | |

**`storage` и `dialogs` — критичные:** без них прод **падает на первом деплое** (Memory-storage
вместо Redis теряет state и не работает мультиинстанс; отсутствие единого `StatesGroup`/корневого
`LaunchMode.ROOT`/error-handlers ломает живые кнопки). Заполняй их первыми.

## Frontmatter

```yaml
id: stack.service      # stack.<name>
kind: service          # один из 11 выше
name: service          # == basename файла без .md
status: draft          # draft → stable
```

## Секция Generates

Каждый артефакт обязан иметь секцию **Generates** — что из него родится в коде/конфиге. Это
контракт для `de-template`: маппинг живёт рядом с источником, не отдельным файлом.

## Workflow

1. `/stack-deep-dive` — заполнить артефакты волнами вопросов (начни со `storage`+`dialogs`).
2. Промоушн `status: draft → stable`.
3. `/de-template` читает stable-артефакты и разворачивает фундамент (config/app/extensions, env,
   prune reference, нужные kit-провайдеры) по секциям `Generates`.
4. `/scaffold` разворачивает фичи по флоу диалогов (см. `docs/reference/dialog-mapping.md`).

## Gate

`/de-template` не запускается, пока не все артефакты `stable`. Код разворачивается только из
stable-артефактов, не из draft.
