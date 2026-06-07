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
mypy + pytest). См. `.claude/CLAUDE.md`.

**Current focus:** Фазы 0 и 1 закрыты в ките (шаблон пинит `298f005`). Идёт Фаза 2 — сеть
качества/корректности (`audit/roadmap.md`). Мульти-бот вне скоупа.

## Active

### phase2-quality-net

Закрыть Фазу 2 `audit/roadmap.md` — убрать «ложный зелёный» и тихие конфиг-ловушки. Микс TPL+KIT
(KIT-правки прямо в соседний `pylibinfra`, затем перепин). Пункты:
- `2.1` integration-слой (TPL+KIT): 2–3 теста на боевом redis/nats (DeliveryDedup TTL reserve/commit,
  guard TTL, JetStream nak→redelivery, golden на потерю). Сейчас 0 integration в шаблоне.
- `2.2` error-пути (TPL): gateway-маппинг, глобальный `AppErrorUX`, `payments/handlers`.
- `2.3` `[tool.pydantic-mypy]` `init_typed`+`init_forbid_extra` (TPL+KIT) — ловит JSON→DTO-ошибки.
- `2.4` state-TTL (KIT+TPL): `BOT_STATE_TTL` → `RedisStorage` + `cache.set(ttl=)` для onboard/link/locale.
- `2.5` мёртвый конфиг (KIT): `BOT_SHUTDOWN_DRAIN` (polling-drain in-flight), `write_timeout`,
  `max_conn_lifetime`, bruteforce `window` — реализовать ИЛИ удалить поле+docstring.
- `2.6` локаль фоновых уведомлений (KIT+TPL): locale-канал в `Delivery` + ключ `notifications-*` в `.ftl`.
- `2.7` согласовать мажор mypy (шаблон → `>=2.1,<3`), перелочить.

**Gate:** оба репо зелёные (`make check` / `uv run …`). Коммит/пуш — по явной просьбе.

## Backlog

- **Метрика успешной выдачи** `payments_total{stage=paid,result=ok}` + лог промаха доставки —
  чтобы регрессии путей платежей/уведомлений перестали быть невидимыми (хвост Фазы 0).
- `.env.example` шаблона: `LOG_REDACT_ENABLED` (хвост 1.7); опц. провязать `OptionalConn`, чтобы
  health-probe в polling проверял и NATS.
- INFRA-HANDOFF Фазы 1 (при релизе/деплое): polling биндит health-порт (`HTTP_*`), новые env-ручки
  (`NATS_JS_MAX_DELIVER/BACKOFF/FLOW_CONTROL/IDLE_HEARTBEAT/DLQ_ENABLED`, `NATS_MAX_RECONNECTS=-1`,
  `BOT_FLOOD_ENABLED`, `BOT_RATE_GLOBAL`, `BOT_RATE_PER_CHAT`, `BOT_RETRY_AFTER_ATTEMPTS`), DLQ-сабжект
  `dlq.<subject>`. Передать инфра-админу через `/release` handoff.
- Свапнуть пин `pylibinfra` с коммита `298f005` на release-тег `vX.Y.Z`, когда `pylibinfra`
  будет тегнут на ревизии с `tgbotkit` (`pyproject.toml` → `[tool.uv.sources]`).
