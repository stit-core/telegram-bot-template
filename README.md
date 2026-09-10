<div align="center">

# telegram-bot-template

### Тонкий шаблон Telegram-бота: чистая бизнес-логика на aiogram_dialog

Шаблон Telegram-бота экосистемы stit: aiogram 3.31 + aiogram-dialog 2.6 + dishka, поверх
[`pylibinfra[tgbotkit]`](https://git.stit.tech/stit-core/pylibinfra) (Bot/Dispatcher,
RedisStorage, middleware, webhook/polling runner, error-UX, структурные логи, i18n/notifications/
payments/webapp). Observability, тесты и релиз — встроены; вы пишете фичи (диалоги), не обвязку.

[![License](https://img.shields.io/badge/license-Apache--2.0-2563eb)](LICENSE)
[![Часть stit](https://img.shields.io/badge/stit-открытые_шаблоны-6366f1)](https://git.stit.tech/stit-core/stit-public)
[![Python](https://img.shields.io/badge/Python-≥3.12-3776AB)](#что-внутри)
[![aiogram](https://img.shields.io/badge/aiogram-3.31_+_aiogram__dialog_2.6-0088cc)](#что-внутри)
[![DI](https://img.shields.io/badge/DI-dishka-8b5cf6)](#что-внутри)
[![Observability](https://img.shields.io/badge/observability-structured_logs-22c55e)](#что-внутри)

</div>

---

## Место в экосистеме

```
business-strategy-template (<org>/strategy)   ← дизайн диалогов проектируется здесь
        │  scaffold диалогов по stable-артефактам telegram-bot-flow/<surface>/
        ▼
telegram-bot-template (<org>/<bot>)  ← вы здесь   ──► stit-core/pylibinfra[tgbotkit]
        │  build + push image
        ▼
project-infra-template-compose (<org>/infra)   ← деплой образа
```

Корп control-plane (registry образов) —
[`corp-infra-template`](https://git.stit.tech/stit-core/corp-infra-template). Подробнее —
[`docs/reference/ecosystem.md`](docs/reference/ecosystem.md).

**Два пути — без вендор-лока.** Registry и адреса внешних сервисов (бэкенды, Redis, NATS) указывают
либо на наш **managed** (`*.stit.tech`), либо на **ваш self-hosted**. Всё конфигурируется через env,
не зашито в код; архитектура одинакова.

## Использовать как шаблон

В Gitea помечен `template: true`. **Полный путь** от форка к своему боту —
[`docs/getting-started.md`](docs/getting-started.md): форк → `/init-service` → проектирование флоу
(`/dialog-deep-dive`; дизайн — из стратегии-репо, если он есть) → стека (`/stack-deep-dive`) →
`/de-template` → scaffold фич → бот, который ничего не помнит про шаблон.

Быстрый старт (чтобы собралось):

```bash
# 1. Use this template → <org>/<bot>, склонировать
# 2. (один раз на машину) доступ к приватным модулям той же Gitea:
git config --global url.git@git.stit.tech:.insteadOf https://git.stit.tech/
# 3. зелёный gate:
make setup && make check
# 4. запустить онбординг:
cp .env.example .env   # заполнить (минимум BOT_TOKEN)
claude                 # → /init-service
```

Имя проекта, README, фундамент и удаление reference-фич делает флоу `/init-service` →
`/de-template` по заполненным `docs/stack/`. Не правьте фундамент руками до этого.

## Что внутри

- **Presentation** — `aiogram_dialog`: Dialog/Window, getter'ы (read), handler'ы (реакции), i18n
  через Fluent (`.ftl`).
- **Фича — вертикальный срез** `features/<name>/`: гексагон (`ports`/`usecase`/`policy`/`state`/
  `errors` + presentation), порт типизирован wire-моделью pkg-клиента (DIP без адаптера).
- **HTTP к бэкендам** — `pkg/http_client/` (API-классы поверх `pylibinfra.httpclient`, typed-ошибки).
- **DI** — `dishka`. Один runtime-процесс: диалоги + notifications-подписчики + jobs в одном боте
  (отдельного worker-образа нет, бот stateless — state в Redis).
- **Платформа** — [`pylibinfra[tgbotkit]`](https://git.stit.tech/stit-core/pylibinfra):
  Bot/Dispatcher/RedisStorage, middleware, webhook/polling runner, error-handlers, структурные логи,
  health-пробы `/ready`, generic-механика i18n/notifications/payments/webapp.
- **Дизайн флоу** — артефакты в соседнем стратегии-репо; маппинг в код —
  [`docs/reference/dialog-mapping.md`](docs/reference/dialog-mapping.md).
- **Тесты** — unit, flow (`BotClient` + фейк порта), integration (testcontainers redis/nats),
  startup-smoke (коллизии `StatesGroup`).
- **Gate** — `make check` = ruff format/check + import-linter + mypy (src+tests) + lock-check +
  pytest с полом покрытия (pre-push хук).

## Команды

`make help` — полный список. Канонический gate — **`make check`**. Полный гайд агента —
[`CLAUDE.md`](CLAUDE.md); точка входа в сессию — `/smartdev`.

```bash
make check     # ruff/import-linter/mypy/lock-check/pytest+cover-floor (gate перед push)
make run       # локальный polling-бот (нужен BOT_TOKEN)
make test-integration   # тесты с Docker (testcontainers redis/nats)
make release VERSION=vX.Y.Z   # образ в registry (skill /release)
```

## Документация

Карта — [`docs/README.md`](docs/README.md):
- Потребителю — [`getting-started.md`](docs/getting-started.md); контрибьютору —
  [`contributing.md`](docs/contributing.md).
- Reference — [architecture](docs/reference/architecture.md) ·
  [dialog-mapping](docs/reference/dialog-mapping.md) ·
  [observability](docs/reference/observability.md) · [release](docs/reference/release.md) ·
  [ecosystem](docs/reference/ecosystem.md).
- Design SoT — флоу из стратегии-репо · [`docs/stack/`](docs/stack/README.md).
- [`aiogram-dialog-docs/`](aiogram-dialog-docs/) — исчерпывающий референс по `aiogram_dialog`.

## Release

Зона репо: **код → image в registry, STOP.** Деплой — другие репо. Одна команда `make release
VERSION=vX.Y.Z` (skill `/release`). Полностью — [`docs/reference/release.md`](docs/reference/release.md).

## Часть экосистемы stit

Это один из открытых шаблонов stit (Apache-2.0) — фундамент «-1 уровня», берите бесплатно и
владейте. Карта всех шаблонов и точка входа — **[витрина stit](https://git.stit.tech/stit-core/stit-public)**.
Нужна команда, стандарт или поддержка — **[наш подход и контакты (vision)](https://git.stit.tech/stit/vision)**.

## Лицензия

**Apache-2.0** — см. [`LICENSE`](LICENSE).
