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

**Current focus:** Фаза 0 закрыта (C1/C2/H1/M7). Следующее по `audit/roadmap.md` — Фаза 1
(надёжность под нагрузкой/на сбоях) до прода с платежами/уведомлениями.

## Active

_(пусто — заведи секцию через `/plan`)_

## Backlog

- **Метрика успешной выдачи** `payments_total{stage=paid,result=ok}` + лог промаха доставки —
  чтобы регрессии путей платежей/уведомлений перестали быть невидимыми (хвост Фазы 0).
- Фаза 1 аудита (`audit/roadmap.md`) — rate-governor, JetStream failure-path/DLQ, реальный drain,
  fail-open на Redis/NATS, SecretStr, PII-redact, throttle. Обязательна до прода с платежами/уведомл.
- Свапнуть пин `pylibinfra` с коммита `2ba22fd` на release-тег `vX.Y.Z`, когда `pylibinfra`
  будет тегнут на ревизии с `tgbotkit` (`pyproject.toml` → `[tool.uv.sources]`).
