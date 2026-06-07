# Getting started — от шаблона к своему боту

**[META]** Этот файл — для потребителя шаблона. Описывает путь от форка до бота, который
ничего не помнит про шаблон. Удаляется на шаге де-темплейтизации.

Принцип: **не правь фундамент руками — сначала спроектируй стек, потом дай скиллам развернуть.**
Документация в `docs/stack/` первична; код вторичен и разворачивается по ней. Вся инфра бота
живёт в `pylibinfra[tgbotkit]` — в шаблоне ты пишешь только бизнес-логику (фичи, диалоги, тексты).

## 0. Форк

1. Gitea → `telegram-bot-template` → **Use this template** → `<org>/<bot>`.
2. `git clone git@git.sftbmb.ru:<org>/<bot>.git && cd <bot>`.
3. Один раз на машину — доступ к приватной `pylibinfra` той же Gitea:
   `git config --global url."git@git.sftbmb.ru:".insteadOf "https://git.sftbmb.ru/"`
   (или PAT — см. `.gitea/workflows/ci.yml`, secret `PYLIBINFRA_TOKEN`).
4. `make setup` — `uv sync` (dev-инструменты) + git-хуки (commit-msg / pre-commit / pre-push).

> `pylibinfra` пинится по git-ref в `[tool.uv.sources]` (`pyproject.toml`) — как go-сервис на
> `go.mod`-версию. Сейчас pin на коммит `3eebcba` (первая ревизия с kit'ом `tgbotkit`);
> на проде свапни на релиз-тег (`tag = "vX.Y.Z"`), как только `pylibinfra` будет тегнут.

## 1. `/init-service`

Скилл-оркестратор ведёт весь онбординг: проектирование стека → де-темплейтизация → scaffold
фич → prune reference. Дальше шаги 2–6 — под его управлением. Без него — вручную в том же порядке.

## 2. Спроектируй стек — `/stack-deep-dive`

11 артефактов в `docs/stack/` (service / runtime / storage / dialogs / backends / messaging /
auth / observability / config / dependencies / i18n). См. [stack/README.md](stack/README.md).

- **`storage` и `dialogs` — критичные:** без них прод падает на первом деплое (Redis вместо
  Memory-storage; единый каталог `StatesGroup`, корневой `LaunchMode.ROOT`, `/start`=`RESET_STACK`,
  error-handlers). Заполни их первыми.
- Цель: `status: stable` по всем артефактам. Это вход для де-темплейтизации.

## 3. Разверни фундамент — `/de-template`

Читает stable-артефакты `docs/stack` и разворачивает фундамент по секциям **Generates**:
import-path (`bot` → твой пакет), README, `config.py` (значения env), `app.py`/`extensions.py`
композиция (какие kit-провайдеры, какие точки расширения), `.env.example`, нужные kit'ы
`pylibinfra`. Гибрид: механика (rename, README, env, prune, strip шаблонной меты) —
детерминирована; wiring composition root — reviewable diff поверх скелета.

## 4. Сгенерируй свои фичи — `/scaffold`

`/scaffold feature <name>` разворачивает вертикальный срез `features/<name>/` (полный гексагон:
`state/dto/errors/policy/ports/usecase/gateway/views/dialogs/getters/handlers/adapters/provider`)
+ `Provider` + регистрацию в `extensions.py` + `StatesGroup` в `platform/dialogs/states.py`.
Маппинг флоу диалога → файлы фичи — [reference/dialog-mapping.md](reference/dialog-mapping.md).
Другие варианты: `dialog` / `window` / `backend-port` / `middleware` / `job` / `notification`
(новый middleware/runtime — НЕ сюда, а PR в `tgbotkit`).

Делай это **до** удаления reference-фич (шаг 5) — иначе теряешь живой образец раскладки.

## 5. Удали reference-фичи

Когда свои фичи готовы, убери учебные `start` / `profile` / `payments` / `lang` /
`notifications` (полный набор архетипов: pure-онбординг / полный гексагон с бэкендом /
оплата Stars / i18n / NATS-доставка):
- `src/bot/features/{start,profile,payments,lang,notifications}/` (что не оставляешь);
- их регистрацию в `extensions.py` (`RouterBundle`/`CommandBundle`/`NotifierBundle`);
- их `StatesGroup` в `platform/dialogs/states.py`;
- их контракты в `importlinter.toml` (`containers`/`modules`);
- их `.ftl` в `locales/<lang>/<feature>.ftl` и ресурсы в `config.py` (`_I18N_RESOURCES`);
- их flow/backend-тесты.
`/de-template` подсказывает/выполняет этот чеклист.

## 6. Готово

Бот больше ничего не помнит про шаблон: свой пакет, README, свои фичи, стек, переводы. Дальше —
обычный дневной флоу через `/smartdev` (см. [contributing.md](contributing.md)). Запуск локально
— `make run` (polling, нужен `BOT_TOKEN`; `OTEL_STDOUT_ONLY=true` для dev). Релиз образа —
[reference/release.md](reference/release.md).

## Команды make

| `make <verb>` | Делает |
|---|---|
| `setup` | `uv sync` (dev) + git-хуки |
| `fmt` / `fmt-check` | `ruff format` (+`--check` для CI) |
| `lint` | `ruff check` + `lint-imports` (import-linter) |
| `typecheck` | `mypy src` |
| `test` / `test-integration` | pytest без integration/e2e / только integration (Docker) |
| `check` | **канонический gate:** fmt-check + lint + typecheck + test |
| `run` | локальный polling-бот |
| `status` | сводка состояния репо (ветка / drift / гейт) |
| `release` | `release VERSION=vX.Y.Z` — собрать+запушить образ + INFRA-HANDOFF |
| `lock` / `sync` | пересобрать / установить `uv.lock` |

Перед claim «готово» или push — `make check` зелёный.
