---
title: "telegram-bot-template — дорожная карта реализации"
description: "Фазовый план: сначала инфра в pylibinfra (tgbotkit + httpkit PR), затем тонкий шаблон чистой бизнес-логики. + открытые решения."
status: design
lang: ru
---

# Дорожная карта реализации

Директива «вся инфра в pylibinfra» делает порядок таким: **сначала kit в `pylibinfra`**, затем
**тонкий шаблон**. Возможен временный bootstrap-в-шаблоне (Фаза -1) с последующим выносом.

---

## Трек I — pylibinfra (инфра). Делается в репо `pylibinfra`

### PR-B — доработка `httpkit` (`_research/15`)
- [ ] `build_app(lifespan=)`, `Server(autostart=False)` + `dishka_lifespan(container)` (закрытие
      контейнера после yield) — закрывает GAP из `_research/06`.
- [ ] `SharedSecretConfig` + `shared_secret_guard()` (generic 403-guard, constant-time, fail-closed).
- **Gate:** аддитивно, back-compat; `_research/15` оценка ~120–180 строк + тесты.

### PR-A — новый kit `tgbotkit` (`_research/18`), через skill `/add-kit`
- [ ] extra `pylibinfra[tgbotkit]` с `aiogram`/`aiogram-dialog`/`fluent.runtime` (новые deps — **согласовать
      с владельцем pylibinfra**, обоснование «framework ≠ продукт»).
- [ ] `BotProvider` + `tgbotkit.Config` (`BOT_*`): `Bot`/`Dispatcher`/`RedisStorage`-фабрики
      (`with_destiny`+`RedisEventIsolation` поверх cachekit), session+ретраи.
- [ ] Стандартная outer-middleware-цепочка (request-id → dedup `update_id` → throttle → RED+span →
      recovery), навешивание и на `DIALOG_EVENT_NAME`; error-handlers `Unknown*`→reset (UX через
      `ErrorUX`-Protocol).
- [ ] `BotRunner.run(routers, commands, notifiers, jobs, …)`: `setup_dishka` + `setup_dialogs`
      (последним) + `emit_startup` + polling/webhook (webhook поверх httpkit) + graceful shutdown.
- [ ] Точки расширения: `RouterBundle`/`CommandBundle`/`NotifierBundle`/`list[PeriodicJob]`/`ErrorUX`.
- [ ] Подсистемы (generic-механика): i18n (`I18NFormat`+`install_i18n`+`LocaleResolver`+`CatalogLoader`,
      движок `fluent` за Protocol `Translator`); notifications (`NotificationRunner`+`Router.on`+
      `Notifier`+`DeliveryDedup`); payments (`answer_pre_checkout` timeout-guard + dedup +
      `tg_payments_*`); webapp (initData-валидатор — или оставить в шаблоне `platform/webapp/`).
- [ ] Observability апдейтов (`tg_updates_*`), testkit-сабпакет, строка в README §Пакеты.
- **Gate:** ruff+mypy+pytest зелёные в pylibinfra; релиз `vX.Y.Z`.

---

## Трек II — telegram-bot-template (бизнес). Делается в этом репо

### Фаза 0 — Фундамент
- [ ] `pyproject.toml` (dependency: `pylibinfra[tgbotkit] @ git+…@vX.Y.Z`; dev: ruff/mypy/import-linter/
      pytest/respx/`pylibinfra[testkit]`), `.python-version`, `uv.lock`.
- [ ] Тулинг-конфиги (`[tool.ruff]`/`[tool.mypy strict]`/`[tool.pytest]`), `importlinter.toml`.
- [ ] `Makefile`, git-hooks, `Dockerfile` (multi-stage uv, ssh-mount), `compose.dev.yml`,
      `.gitea/workflows/ci.yml`.
- **Gate:** `make check` зелёный на скелете.

### Фаза 1 — Тонкий composition root
- [ ] `config.py` (`AppConfig` + `AppConfigProvider` со всеми `*Config`), `app.py` (~30 строк:
      провайдеры → `BotRunner.run`), `__main__.py`.
- **Gate:** бот поднимается через `BotRunner` (polling), `emit_startup` проходит, метрики/логи идут.

### Фаза 2 — Платформа (бизнес-общее)
- [ ] `platform/identity/` (Update→BotIdentity), `platform/backend/` (общий клиент поверх httpclient
      + транспорт-ошибки), `platform/dialogs/` (states.py, common.py, ErrorUX).
- **Gate:** identity/gateway-обвязка покрыта тестами.

### Фаза 3 — Reference-фичи
- [ ] `features/start/` (pure-онбординг, `LaunchMode.ROOT`, `/start`=`RESET_STACK`).
- [ ] `features/profile/` (полный гексагон: ports/gateway/usecase/policy/dialogs/getters/handlers/
      views/provider/adapters; cross-feature к `start`).
- **Gate:** unit(policy) + flows(BotClient) + backend(mock gateway); import-linter держит границы.

### Фаза 4 — Встроенные подсистемы (контент/бизнес поверх tgbotkit-механики)
- [ ] i18n: `locales/<lang>/<feature>.ftl`, фича смены языка, дефолт `ru`.
- [ ] `features/notifications/` (`deliver_*` event→сообщение/диалог, `register(router)`, заполнение
      `link:acct→chat_id`).
- [ ] `features/payments/` (policy/usecase/gateway/dialogs + dispatcher-level pre_checkout/on_paid).
- [ ] `platform/webapp/` (initData-валидатор + identity-link + gateway).
- **Gate:** flow-тесты на каждый сценарий; pre_checkout 10с / дедуп / не-доверять-клиенту проверены.

### Фаза 5 — `.claude`-система и доки
- [ ] `CLAUDE.md`, skills (см. [CLAUDE-SYSTEM.md](CLAUDE-SYSTEM.md)), bot-rules, agents, roadmap.
- [ ] `docs/` (getting-started, contributing, reference/*, stack/* + `dialog-mapping.md`),
      `settings.json`.
- **Gate:** `/de-template` корректно разворачивает форк (prune reference-фич).

---

## Открытые вопросы

1. **Имя kit'а:** `tgbotkit` (рекомендация: `bot`=aiogram-bootstrap, как `http`=FastAPI) vs `tgkit`/
   `aiogramkit`.
2. **Новые deps в pylibinfra:** согласовать `aiogram`/`aiogram-dialog`/`fluent.runtime` в extra
   `[tgbotkit]` с владельцем pylibinfra (CLAUDE.md требует обсуждать новые import'ы).
3. **Последовательность:** ждать мержа PR-A/PR-B и строить тонкий шаблон **vs** Фаза -1 (временный
   bootstrap в шаблоне → вынос в tgbotkit PR'ом, чтобы не блокироваться).
4. **initData-валидатор:** в `tgbotkit.webapp` (generic) vs в шаблоне `platform/webapp/`
   (Telegram-vendor-специфика). Рекомендация: спроектировать в шаблоне, поднять в kit при
   переиспользовании.
5. **Глубина reference-фич:** `start`+`profile`+`payments`+`notifications` (рекомендация) vs больше/
   меньше архетипов.
6. **anti-spam:** Redis-счётчик в tgbotkit-throttle (дёшево) vs `bruteforcekit` (тянет Postgres —
   против «боту Postgres не нужен»).
