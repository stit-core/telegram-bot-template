# Документация

Роутер по docs. Три аудитории + design source-of-truth.

## Потребителю шаблона
- [getting-started.md](getting-started.md) — пошаговый путь: форк → проектирование флоу → стек → `/de-template` → свой бот. **[META]** — удаляется при де-темплейтизации.

## Контрибьютору шаблона
- [contributing.md](contributing.md) — как устроена `.claude`-система (rules/skills/settings), что enforce'ится, как вмешаться, troubleshooting. **[META]**.

## Reference (переезжает в проект)
- [reference/architecture.md](reference/architecture.md) — слои фичи (гексагон), pkg-клиенты, composition root, граница с tgbotkit, non-goals.
- [reference/dialog-mapping.md](reference/dialog-mapping.md) — как флоу диалога (свой или из стратегии-репо) ложится в код фичи; потребляет `scaffold`.
- [reference/observability.md](reference/observability.md) — структурные логи в stdout (logkit), trace-correlation, health.
- [reference/release.md](reference/release.md) — релиз образа, handoff в infra, откат, версионирование.
- [reference/ecosystem.md](reference/ecosystem.md) — роль бота среди форков орги, как сюда приходят агенты (из хаба `<org>/infra` или прямым заходом), что репо берёт (дизайн из стратегии, `pylibinfra`, бэкенды) и отдаёт (образ + INFRA-HANDOFF); хендофф из стратегии.

## Design source-of-truth
- **Флоу диалогов** — проектируется скиллом `/dialog-deep-dive` в карту `docs/stack/dialogs.md`. Если у проекта есть **стратегия-репо** (`<org>/strategy`, форк `business-strategy-template`, sibling-checkout рядом) — дизайн приходит из его слоя `docs/projects/<slug>/telegram-bot-flow/<surface>/` (read-only); маппинг в код — [reference/dialog-mapping.md](reference/dialog-mapping.md).
- [stack/README.md](stack/README.md) — артефакты платформы/стека (вход для `/de-template`). Остаётся в этом репо.

Точка входа агента в репо — `CLAUDE.md` (ядро + роутер). Дневной флоу — skill `/smartdev`. Исчерпывающий референс по `aiogram_dialog` — `aiogram-dialog-docs/`.
