---
name: infra-handoff
description: Оформить INFRA-HANDOFF-блок для инфра-админа при изменении инфра-поверхности бота (env/секрет/webhook/cross-service-NATS-subject/runtime-dep). Активируй когда правишь config.py/.env*/Dockerfile/notification-subject/pyproject.toml-deps, когда make status показал Infra-touch, или юзер говорит "это задевает инфру", "что передать админу". Новая инфра-МЕХАНИКА (middleware/runtime/kit-helper) — это PR в tgbotkit, тоже сюда.
---

# Skill: infra-handoff

Процедура фиксации инфра-затрагивающего изменения. Зона репо — код→image; всё, что требует действия инфра-стороны **или** правки `pylibinfra`, должно уйти **явным структурированным сообщением**, а не остаться в голове. Правило-якорь — `.claude/rules/infra-impact.md` (грузится автоматически на инфра-файлах); этот skill — как именно оформить и куда положить.

## Когда применять

- `make status` → Infra-touch не `none` (cockpit чейнит сюда).
- Правишь: `config.py` / `.env.example*` / `Dockerfile` / `compose.dev.yml`; `features/notifications/**` или любую регистрацию NATS-subject; webhook/polling-режим, `allowed_updates`; `pyproject.toml` (новая runtime-зависимость / ревизия `pylibinfra`).
- Нужна **новая инфра-механика** (middleware, runtime-режим, новый helper kit'а, новая точка расширения) — её **нельзя написать в шаблоне** (rule `tgbotkit-boundary`); это PR в `pylibinfra/tgbotkit`, оформляется тем же блоком.
- Юзер: «это задевает инфру», «что передать админу», «нужен ли новый секрет».

## Когда НЕ применять

- Чисто внутренняя логика/тесты/рефактор фичи без смены env/контракта/зависимостей/механики.
- Code-default тюнинг без нового **обязательного** ENV (дефолт в коде → инфре делать нечего).
- Уже оформлен актуальный блок для этого же изменения — не дублируй.

## Классы инфра-изменений бота

| Класс | Примеры | Адресат |
|---|---|---|
| **env / секреты** | `BOT_TOKEN`, `WEBHOOK_SECRET`, `REDIS_URL`, `NATS_URL`, `HTTPCLIENT_*` / `*_BASE_URL` именованных бэкендов, `APP_ADMIN_IDS` | проект (compose env) |
| **runtime-режим** | `BOT_MODE=polling↔webhook`, инстансы (webhook ≥2 + `RedisEventIsolation`), `set_webhook` single-flight, `allowed_updates` | проект |
| **cross-service контракт** | новый NATS-subject/stream/durable для notification (бот ↔ бэкенд) | проект + владелец бэкенда |
| **runtime-deps / ёмкость** | новая зависимость в `pyproject.toml`, ревизия `pylibinfra[tgbotkit]`, Redis/NATS capacity | проект |
| **инфра-механика (→ PR в tgbotkit)** | новый middleware (throttle/auth), новый runner, новый helper (payments/i18n/webapp), новая точка расширения | `pylibinfra`-мейнтейнер |

Если ни один класс — это не инфра-изменение, выходи.

## Шаги

### 1. Классифицировать (таблица выше). Определить адресата

- **проект** (`<client-org>/infra`): env/секрет в compose `environment:` (`BOT_TOKEN`/`WEBHOOK_SECRET` и прочие значения кладутся здесь, конфиг через env), новый сервис-зависимость (Redis/NATS), scaling/режим, `make ship`.
- **`pylibinfra`-мейнтейнер**: новая инфра-механика — PR в `tgbotkit` (по образцу `/add-kit` / правки существующего kit'а). Шаблон при этом может временно нести механику локально и вынести её PR'ом (см. ARCHITECTURE §16).

### 2. Сформировать блок

```
=== INFRA HANDOFF · передай инфра-админу ===
WHAT   <имя/тип, default, required?>
WHY    <фича/причина — коммит/план-атом>
ACTION <конкретное действие инфра-стороны / суть PR в tgbotkit>
WHO    <проект | pylibinfra>
DECIDE <нужно решение (значение/выбор) или «дефолт N ок?»>
RISK   <последствие бездействия>
===
```

Конкретно. `WHAT: env BOT_MODE, default polling, required в проде=webhook` — годится. `WHAT: что-то с режимом` — нет. Значение секрета **не** писать (только имя ключа + «нужен»; значения секретов не эхо-ить и не коммитить, в `.env.example` — только имена).

Для механики: `WHAT: новый outer-middleware rate-limit на message+DIALOG_EVENT_NAME`, `ACTION: PR в pylibinfra/tgbotkit (middleware-цепочка), новая точка расширения ThrottleConfig`, `WHO: pylibinfra`.

### 3. Положить так, чтобы доехало до релиза

- **Чат:** покажи блок юзеру, явно: «передай инфра-админу out-of-band; это не делается из этого репо» (а для механики — «это PR в pylibinfra, не правка шаблона»).
- **Активный план:** добавь/дополни `**Infra impact.**` в активной секции `.claude/plans/roadmap.md`. `make release` агрегирует его в финальный INFRA-HANDOFF. Секция удаляется по закрытии (forward-only) → infra-impact обязан переехать в release-handoff **до** закрытия; если план закрывается раньше релиза — follow-up строкой в `## Backlog`.
- **Нет активного плана:** блок только в чат; проследи, что юзер подтвердил передачу, прежде чем пометить «готово».

### 4. Граница

Не выполняй `make ship` / `ssh <vps>` / правки чужого репо / merge PR в `pylibinfra`. Роль — сформировать и отдать сообщение. Дальше — проектная/мейнтейнер-сторона.

## Anti-patterns

- ❌ Пометить инфра-задачу «готово»/закоммитить без предъявленного блока.
- ❌ Написать новый middleware/runner в шаблоне вместо PR в `tgbotkit` (нарушает rule `tgbotkit-boundary`).
- ❌ «Допишу на релизе» — release агрегирует уже записанное; не записал в `**Infra impact.**` → потеряно.
- ❌ Значение секрета (`BOT_TOKEN`/`WEBHOOK_SECRET`) в блоке/чате (только имя ключа).
- ❌ Размытый WHAT/ACTION без конкретики — админ не примет решение.
- ❌ Самому деплоить/мержить PR в pylibinfra — чужая зона, чужие креды.
- ❌ Гнать блок на не-инфра-правку (шум обесценивает сигнал).
