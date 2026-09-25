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
<С дефолтами: `BOT_MODE` (polling/webhook) + `BOT_WEBHOOK_*`, `NATS_URL` + `NATS_JS_*`, `LOG_LEVEL`/
`LOG_FORMAT`/`LOG_SILENT`/`LOG_REDACT_*`, `APP_ADMIN_IDS`, `BOT_I18N_*`, `BOT_STATE_TTL`, `HTTP_ADDR`
(health-порт). Источник дефолтов — kit-конфиги; заданная пустая переменная = дефолт.>

## Secrets
<Что секрет (`BOT_TOKEN`, токены бэкендов). На проде секреты приходят через env из `.env` хаба
`<org>/infra` на VPS; в `.env.example` — только имена ключей, не значения (rule `infra-impact`).>

## *Config inventory
<Какие `*Config` собирает `AppConfigProvider` (асимметрия dishka — kit'ы не provide'ят свой Config):
logkit (+ `OptionalRedactConfig`)/cachekit/httpkit/httpclient (`BackendsConfig`)/natskit/tgbotkit +
`AppConfig` — все через `<kit>.new_config()`: невалидный ENV валит старт `<kit>.ConfigError`
(dishka валидирует DI-граф жадно, значения — при первом резолве).>

## Generates
<Что de-template родит:
- `.env.example` (required+optional с дефолтами, секреты — только имена)
- `config.py`: `AppConfig` + `AppConfigProvider` (все `*Config` через `new_config()`), `BackendsConfig`, i18n-каталог>
