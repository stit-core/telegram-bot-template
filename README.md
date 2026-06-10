# telegram-bot-template

Тонкий шаблон Telegram-бота: **чистая бизнес-логика** на `aiogram_dialog` поверх
`pylibinfra[tgbotkit]`. Вся инфраструктура (Bot/Dispatcher/RedisStorage, middleware-цепочка,
webhook/polling runner, dishka-setup, error-UX, метрики апдейтов, generic-механика
i18n/notifications/payments/webapp) живёт в `pylibinfra`; в шаблоне — только фичи (диалоги,
usecase, ports, policy, state; клиенты API — в `pkg/http_client`), контент (`.ftl`-переводы)
и тонкая регистрация в точки расширения kit'а.

Зеркалит `go-backend-template`: доменно-гексагональная раскладка фичи, `.claude`-система,
`make`-гейты, Conventional Commits, forward-only.

## Быстрый старт

```bash
make setup     # dev-инструменты (uv) + git-хуки
make check     # канонический гейт: fmt + lint + import-linter + mypy + pytest (не integration)
make run       # локальный polling-бот (нужен BOT_TOKEN)
```

## Документация

- `design/` — авторитетный архитектурный дизайн (ARCHITECTURE / FEATURE-BLUEPRINT / ROADMAP / …).
- `docs/` — getting-started, contributing, reference, stack-артефакты.
- `aiogram-dialog-docs/` — исчерпывающий референс по `aiogram_dialog`.
- `.claude/` — агентная система (CLAUDE.md, skills, rules, agents).

## Стек

aiogram 3.28 · aiogram-dialog 2.6 · dishka · fluent.runtime · Redis · pylibinfra (httpclient/cachekit/
natskit/telemetry/logkit) · Python ≥ 3.12 · uv.
