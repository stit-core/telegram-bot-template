---
id: stack.config
kind: config
name: config
status: draft
---

# Config — env и секреты

## Required env
<Что обязательно для старта: `BOT_TOKEN` (секрет), `REDIS_URL`, `HTTPCLIENT_BASE_URL` (если есть
бэкенд). Без них бот не поднимется.>

## Optional env
<С дефолтами: `BOT_MODE` (polling/webhook) + `WEBHOOK_*`, `NATS_URL` + `NATS_JS_*`, `LOG_*`,
`APP_ADMIN_IDS`, `BOT_I18N_*`, `BOT_STATE_TTL`, `HTTP_*` (health). Источник дефолтов — kit-конфиги.>

## Secrets
<Что секрет (`BOT_TOKEN`, токены бэкендов). На проде секреты приходят через env (деплой-репо
`<org>/infra`); в `.env.example` — только имена ключей, не значения (rule `infra-impact`).>

## *Config inventory
<Какие `*Config` собирает `AppConfigProvider` (асимметрия dishka — kit'ы не provide'ят свой Config):
logkit/cachekit/httpclient/natskit/tgbotkit + `AppConfig`. Что валидируется при старте
(dishka валидирует DI-граф жадно).>

## Generates
<Что de-template родит:
- `.env.example` (required+optional с дефолтами, секреты — только имена)
- `config.py`: `AppConfig` + `AppConfigProvider` (все `*Config`), `BackendsConfig`, i18n-каталоги>
