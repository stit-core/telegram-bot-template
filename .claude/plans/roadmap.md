# Roadmap

Единственный артефакт планирования проекта — этот файл. Подпапок, `<slug>.md`, архивов и
changelog'ов нет: они расходятся с правдой и мешают.

**Planning-first.** Изменение идёт через план — секцию в `## Active` ниже. Прямая правка без
плана допустима только для truly-atomic (опечатка, один очевидный файл) и багфиксов (→ skill
`/triage-failure`, RED-first). Отклонение от плана — осознанное и проговаривается с юзером.

**Жизненный цикл.** `planning → in-progress → blocked? → done`. По `done` секция задачи удаляется
целиком — история остаётся в `git log`. Незакрытый follow-up переезжает в `## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `CLAUDE.md`.

**Current focus:** активной задачи нет. Шаблон на архитектуре `pkg/http_client` + строгие handlers
(pylibinfra пин `b713602`). `docs/` — go-backend-модель (reference + `stack/_templates`); дизайн
диалогов — вход из стратегии-репо (`telegram-bot-flow/<surface>/`), `design/` нет.

## Active

## Backlog

- **Метрика успешной выдачи** `payments_total{stage=paid,result=ok}` + лог промаха доставки —
  чтобы регрессии путей платежей/уведомлений перестали быть невидимыми (хвост Фазы 0).
- `.env.example` шаблона: `LOG_REDACT_ENABLED` (хвост 1.7); опц. провязать `OptionalConn`, чтобы
  health-probe в polling проверял и NATS.
- INFRA-HANDOFF Фазы 1 (при релизе/деплое): polling биндит health-порт (`HTTP_*`), новые env-ручки
  (`NATS_JS_MAX_DELIVER/BACKOFF/FLOW_CONTROL/IDLE_HEARTBEAT/DLQ_ENABLED`, `NATS_MAX_RECONNECTS=-1`,
  `BOT_FLOOD_ENABLED`, `BOT_RATE_GLOBAL`, `BOT_RATE_PER_CHAT`, `BOT_RETRY_AFTER_ATTEMPTS`), DLQ-сабжект
  `dlq.<subject>`. Опц. Фазы 2: `BOT_STATE_TTL` (TTL FSM-стейта, дефолт 0=вечно). Опц. Фазы 3:
  `HTTPCLIENT_BREAKER_NAME` (имя breaker'а для per-API метрик). Дефолтный label breaker-метрик
  `http_client_breaker_*{name}` у бота теперь `core` (имя именованного бэкенда) — поправить фильтры
  дашбордов, если завязаны на `httpclient`. payments-adv (подписки/возвраты) требует включённых Stars
  subscriptions/refunds у бота в BotFather — не env, deploy-замечание. Передать инфра-админу через
  `/release` handoff.
- Свапнуть пин `pylibinfra` на release-тег `vX.Y.Z`, когда `pylibinfra` будет тегнут на ревизии с
  `tgbotkit` (`pyproject.toml` → `[tool.uv.sources]`).
