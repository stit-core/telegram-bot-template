---
id: stack.config
kind: config
name: config
status: draft
---

# Config — env и секреты

Материализованная таблица всех env (тип, default, sensitive, Vault). Конфиг = app-сторона
(`config.py: AppConfig`) + kit-сторона (все `*Config` собирает `AppConfigProvider` — dishka-
асимметрия: kit'ы НЕ provide'ят свои Config, их регистрирует caller). Все читают env через
pydantic-settings; на проде секреты подаёт vault-agent в env. Новый env дописывается сюда тем же PR.

## Required env
<Без них бот не стартует. Таблица `| Env | Тип | Назначение | Где живёт |`. Эти переменные едут в
INFRA-HANDOFF. Минимум (reference):
| Env | Тип | Назначение | Где живёт |
|---|---|---|---|
| `BOT_TOKEN` | secret | токен от @BotFather | tgbotkit.Config |
| `REDIS_URL` | url | FSM/dialog/cache/link | cachekit.Config |
| `HTTPCLIENT_BASE_URL` | url | бэкенд | httpclient.Config |
| (webhook) `BOT_WEBHOOK_BASE_URL`/`BOT_WEBHOOK_SECRET` | url/secret | приём вебхуков | tgbotkit.Config |>

## Optional env
<С code-default; переопределяй при необходимости. Группируй по префиксу подсекциями:
### Bot (`BOT_*`): `BOT_MODE=polling`, `BOT_PARSE_MODE=HTML`, `BOT_DEDUP_ENABLED`, `BOT_THROTTLE_RPS`,
`BOT_I18N_DEFAULT_LOCALE`.
### App (`APP_*`): `APP_ADMIN_IDS` (csv tg_id).
### NATS (`NATS_*`): `NATS_URL`, `NATS_JETSTREAM_ENABLED`, `NATS_JS_STREAM_NAMES` (если notifications).
### Backend (`HTTPCLIENT_*`): `HTTPCLIENT_TIMEOUT`.
### Telemetry/log (`OTEL_*`/`LOG_*`): `OTEL_SERVICE_NAME`, `OTEL_STDOUT_ONLY`, `LOG_LEVEL`.>

## Secrets
<Vault-класс: таблица `| Env | Тип | Назначение | Vault-ключ |`. Имя ключа и факт «нужен» — НЕ
значение; кто выдаёт (корп-Vault/проект). Минимум: `BOT_TOKEN`, `BOT_WEBHOOK_SECRET` (webhook),
`OTEL_TOKEN` (prod-OTLP), бэкенд-токен (если есть). Прокатка значений — зона infra-репо.>

## Validation & release-checklist
<pydantic-settings fail-fast на старте (обязательность/формат). ### Release-checklist: перед
релизом сверять — новые env дописаны в таблицы выше, sensitive лежат в Vault, infra-template
подхватывает их через vault-agent (см. INFRA-HANDOFF).>

## Generates
<Что de-template родит:
- `config.py` (`AppConfig` + `AppConfigProvider` со всеми *Config)
- `.env.example` (required+optional с дефолтами)
- seed для INFRA-HANDOFF (required env + секреты)>
