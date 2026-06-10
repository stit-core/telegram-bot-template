# Getting started — от шаблона к своему боту

**[META]** Этот файл — для потребителя шаблона. Описывает путь от форка до бота, который ничего не
помнит про шаблон. Удаляется на шаге де-темплейтизации.

Принцип: **не правь фундамент руками — сначала спроектируй, потом дай скиллам развернуть.** Дизайн
первичен; код вторичен и разворачивается по нему.

## 0. Форк

1. Gitea → `telegram-bot-template` → **Use this template** → `<org>/<bot>`.
2. `git clone git@git.stit.tech:<org>/<bot>.git && cd <bot>`.
3. Один раз на машину — доступ к приватным модулям той же Gitea:
   `git config --global url.git@git.stit.tech:.insteadOf https://git.stit.tech/`.
4. `make setup` — pinned dev-tools (uv) + git-хуки.

> `pylibinfra` пинится по git-ref в `[tool.uv.sources]`; если `tgbotkit` ещё не тегнут — ревизия
> указывает на коммит с kit'ом. `git.stit.tech` — managed-хост; self-hosted форк живёт на своей
> Gitea (подставь её хост в clone-URL и `insteadOf`).

## 1. `/init-service`

Скилл-оркестратор ведёт весь онбординг: проектирование флоу → проектирование стека → де-темплейт →
scaffold фич → прун reference. Дальше шаги 2–6 — под его управлением. Нужно знать в 1–2 фразах,
**что бот делает**.

## 2. Спроектируй флоу диалогов — `/dialog-deep-dive`

Прежде чем разворачивать платформу — зафиксируй пользовательские сценарии как флоу: диалоги, окна,
переходы, getter-данные, состояния виджетов, `StatesGroup`. Это source-of-truth presentation **до**
кода (карта `docs/stack/dialogs.md`).

- **Если есть стратегия-репо** (`<org>/strategy`, форк `business-strategy-template`, склонирован
  рядом — `../strategy`) и в нём для bot-поверхности заполнен слой `telegram-bot-flow/<surface>/` —
  дизайн **уже спроектирован** аналитиком (брать `stable`). `/dialog-deep-dive` тогда транслирует
  его в карту флоу (read-only, в стратегию не пишем), не интервьюирует с нуля. Контракт —
  `docs/reference/ecosystem.md`.
- Reference-фичи (`start`/`profile`/...) — учебные образцы раскладки; удаление — шаг 6.

## 3. Спроектируй стек — `/stack-deep-dive`

- Артефакты в `docs/stack/` (service · runtime · storage · dialogs · backends · messaging · auth ·
  observability · config · dependencies, опц. i18n). См. [stack/README.md](stack/README.md).
- В `service.md` запиши имя проекта/package path — по ним `de-template` переименует, `scaffold`
  найдёт фичи.
- Цель: `status: stable` + `make validate-stack-docs` зелёный. ⚠️ `storage` (Redis) и `dialogs`
  (флоу из шага 2) — критичны. Это вход де-темплейтизации.

## 4. Разверни фундамент — `/de-template`

- Читает stable-артефакты `docs/stack` и разворачивает фундамент по секциям `Generates`: имя
  проекта/пакета, README, `.env.example`, wiring `app.py`/`config.py`/`pkg/http_client`. Зависимость
  `pylibinfra[tgbotkit]` остаётся. Фичи он не трогает — только платформу.
- Гибрид: механика (имя, README, env, strip меты) — детерминирована; wiring — reviewable diff.

## 5. Сгенерируй свои фичи — `/scaffold feature`

По каждому stable-флоу из шага 2 разверни код фичи: `/scaffold feature <name>` разворачивает
вертикальный срез `features/<name>/` (гексагон), Provider, регистрацию в `app.py`, `StatesGroup` в
`platform/dialogs/states.py`; бэкенд-данные — pkg-клиент (`scaffold backend-port`). Маппинг флоу →
код — [reference/dialog-mapping.md](reference/dialog-mapping.md). Делай **до** удаления reference
(шаг 6) — иначе теряешь живой образец гексагона.

## 6. Удали/переделай reference-фичи

Когда свои фичи сгенерированы — убери учебные `profile`/`payments`/`lang`/`notifications` и
**переделай** `start` под своё меню (чеклист — `de-template references/prune.md`):
- `start` обычно НЕ удаляется целиком — переписывается под корневой `LaunchMode.ROOT` + своё меню
  (бот без ROOT-диалога не имеет точки входа).
- `payments`/`notifications`/`lang` — прунятся, если бот без платежей/push/i18n; иначе адаптируются.

## 7. Готово

`make check` зелёный + startup-smoke (`pytest -k collision`) чистый → бот больше ничего не помнит про
шаблон: своё имя, свои фичи, стек, deps. Дальше — обычный дневной флоу через `/smartdev` (устройство
`.claude`-системы — `docs/contributing.md`). Релиз образа — `docs/reference/release.md`.
