# Дизайн telegram-bot-template

Проектная документация профессионального шаблона Telegram-бота для экосистемы sftbmb:
**aiogram 3.28 + aiogram_dialog 2.6 + dishka + pylibinfra**.

> **Сквозной принцип.** Бот — фронтенд: вся бизнес-логика на бэкендах (HTTP API / события NATS),
> своё у бота — только его state. **Вся инфраструктура бота скрыта в `pylibinfra`** (новый kit
> `tgbotkit`), а в шаблоне — **только бизнес-логика**, которая дёргает то, что предоставляет
> pylibinfra. Зеркалим конвенции `go-backend-template`.

---

## Двух-репозиторная модель

```
pylibinfra (ИНФРА)                        telegram-bot-template (БИЗНЕС)
  tgbotkit: Bot/Dispatcher/Storage,    ◄──   features/<feature>/ (диалоги, usecase,
          middleware, webhook/polling depends      gateway, policy, state)
          runner, dishka-setup,               locales/ (.ftl-тексты)
          error-UX, tg_*-метрики,             app.py (~30 строк) → BotRunner
          i18n/notify/pay механика            config.py (значения)
  + httpkit/cachekit/natskit/...
```

Инфра выносится **двумя PR в pylibinfra** (новый `tgbotkit` + доработка `httpkit`) — см.
[ARCHITECTURE.md §16](ARCHITECTURE.md).

---

## Как читать

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — авторитетный синтез: видение, двух-репо модель, что
   скрыто в `tgbotkit`, тонкий composition root, анатомия фичи, интеграция с бэкендом, state,
   встроенные подсистемы (i18n/notifications/payments/webapp), деплой, два PR. **Начинать отсюда.**
2. **[FEATURE-BLUEPRINT.md](FEATURE-BLUEPRINT.md)** — устройство фичи file-by-file: рабочие скелеты
   всех файлов (`state/dto/errors/policy/ports/gateway/usecase/views/dialogs/getters/handlers/
   adapters/provider`) на примере `profile`, плюс минимальная `start` и платёжная `payments`.
3. **[CLAUDE-SYSTEM.md](CLAUDE-SYSTEM.md)** — план `.claude`-системы (skills/rules/agents).
4. **[STACK-AND-TOOLING.md](STACK-AND-TOOLING.md)** — версии, тулинг, CI, Dockerfile.
5. **[ROADMAP.md](ROADMAP.md)** — фазовый план (pylibinfra PR → тонкий шаблон) + открытые вопросы.
6. **[`_research/`](_research/)** — 18 исследовательских артефактов (детальная подложка).

---

## Executive summary

- **Инфра в `pylibinfra/tgbotkit`:** bootstrap бота, Dispatcher, RedisStorage-проводка
  (`with_destiny`+isolation), цепочка middleware (request-id/dedup/throttle/RED/recovery),
  webhook(httpkit)/polling runner, dishka-setup, `setup_dialogs`, error-handlers, graceful shutdown,
  `tg_updates_*` метрики, generic-механика i18n/notifications/payments/webapp. `aiogram` —
  опциональная extra `pylibinfra[tgbotkit]` («framework ≠ продукт», как FastAPI в httpkit).
- **Шаблон = чистая бизнес-логика:** `features/<feature>/` (вертикальные срезы, зеркало go-доменов:
  `state·dto·errors·policy·ports·usecase·gateway·dialogs·getters·handlers·views·provider·adapters`),
  контент (`.ftl`), тонкий `app.py` (~30 строк: провайдеры → `BotRunner`), `config.py`.
- **Точки расширения tgbotkit:** `RouterBundle`/`CommandBundle`/`NotifierBundle`/`list[PeriodicJob]`/
  `ErrorUX`/i18n-каталоги — шаблон декларирует, рантайм в kit'е.
- **SOLID:** DIP/ISP/SRP через `Protocol`-порты (`BackendGateway`); ядро не импортит
  `httpx`/`aiogram`/`redis`. Enforce: import-linter + mypy strict.
- **Встроено из коробки:** i18n (`fluent.runtime`), push-уведомления (JetStream durable + `Notifier`),
  платежи (Stars/XTR, pre_checkout 10с), WebApp (валидация initData).
- **Тесты:** unit → flows (`BotClient`+`MockMessageManager`) → backend (`respx`+fake-gateway) →
  integration (testcontainers). Мокаем порт, не транспорт.

---

## Ключевые архитектурные решения

| # | Решение | Почему |
|---|---|---|
| 1 | **Вся инфра — в `pylibinfra/tgbotkit`**; шаблон = чистая бизнес-логика | директива; шаблон тонкий, инфра переиспользуема всеми ботами орга |
| 2 | `aiogram`/`aiogram_dialog`/`fluent` — в extra `pylibinfra[tgbotkit]` | «framework ≠ продукт»; небот-консьюмеры их не тянут |
| 3 | Точки расширения — dishka type-wrapper-бандлы | шаблон подключает бизнес, не трогая инфру |
| 4 | Бот хранит только свой state, данные — за `BackendGateway` | принцип «бот=фронтенд» |
| 5 | Вертикальные срезы-фичи, внутри — слои | зеркало go-доменов; cross-feature граница |
| 6 | Порты — `typing.Protocol`, адаптеры в `provider.py` | DIP/ISP; mypy структурно; тривиальный мок |
| 7 | Webhook поверх httpkit/FastAPI (PR-B), consume'ится tgbotkit | корп-консистентность (otel/health/middleware) |
| 8 | i18n=`fluent.runtime`; notifications=JetStream+`Notifier` | совместимость с I18NFormat; гарантия доставки + грабли BgManager закрыты |
| 9 | Reference-фичи `start`/`profile`/`payments`/`notifications`, удаляемые `/de-template` | образцы архетипов |
| 10 | import-linter (3 контракта) + mypy strict | аналог depguard — границы фич и чистого ядра |

---

## Статус

Дизайн-фаза (с рефайнментом под директиву «вся инфра в pylibinfra»): **18 исследовательских
артефактов** + синтез в 4 авторитетных документа. **Открытые вопросы — в [ROADMAP.md](ROADMAP.md).**
Следующий шаг после согласования: PR-A/PR-B в `pylibinfra` (`tgbotkit`), затем сборка тонкого шаблона.
