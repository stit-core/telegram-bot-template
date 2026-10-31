---
name: infra-handoff
description: Оформить INFRA-HANDOFF-блок для хаба <org>/infra, когда изменение бота требует действия инфра-стороны (env/секрет, webhook/режим рантайма, cross-service NATS-subject, runtime-зависимость или ревизия pylibinfra), либо новая инфра-механика (middleware, runner, kit-helper, точка расширения) — это PR в pylibinfra/tgbotkit. Используй при правке config.py/.env*/Dockerfile/pyproject.toml/notification-подписок, когда make status показал Infra-touch, и когда юзер спрашивает, задевает ли изменение инфру или что передать админу.
---

# Skill: infra-handoff

Процедура фиксации инфра-затрагивающего изменения. Зона репо — код → image; всё, что требует
действия хаба `<org>/infra` **или** правки `pylibinfra`, уходит **явным структурированным
сообщением**, иначе изменение молча разъедется с прод-окружением. Правило-якорь —
`.claude/rules/infra-impact.md` (грузится само на инфра-файлах); этот skill — как оформить блок и
куда его положить.

## Когда применять

- `make status` → Infra-touch не `none` (cockpit чейнит сюда).
- Правишь: `config.py` / `.env.example` / `Dockerfile` / `compose.dev.yml`; `features/notifications/**`
  или любую регистрацию NATS-subject; webhook/polling-режим, `allowed_updates`; `pyproject.toml`
  (новая runtime-зависимость / ревизия `pylibinfra`).
- Нужна **новая инфра-механика** (middleware, runtime-режим, новый helper kit'а, новая точка
  расширения) — в шаблоне её не пишут (rule `tgbotkit-boundary`); это PR в `pylibinfra/tgbotkit`,
  оформляется тем же блоком.
- Юзер: «это задевает инфру», «что передать админу», «нужен ли новый секрет».

## Когда не применять

- Чисто внутренняя логика/тесты/рефактор фичи без смены env/контракта/зависимостей/механики.
- Code-default тюнинг без нового **обязательного** ENV (дефолт в коде → хабу делать нечего).
- Актуальный блок для этого же изменения уже оформлен — не дублируй.

## Классы инфра-изменений бота

| Класс | Примеры | Адресат |
|---|---|---|
| **env / секреты** | `BOT_TOKEN`, `BOT_WEBHOOK_SECRET`, `REDIS_URL`, `NATS_URL`, `HTTPCLIENT_*` / `*_BASE_URL` именованных бэкендов, `APP_ADMIN_IDS` | хаб (`.env` на VPS) |
| **runtime-режим** | `BOT_MODE=polling↔webhook`, `BOT_WEBHOOK_*`, инстансы (webhook ≥2 + `RedisEventIsolation`), `set_webhook` single-flight, `allowed_updates` | хаб |
| **cross-service контракт** | новый NATS-subject/stream/durable для notification (бот ↔ бэкенд) | хаб + владелец бэкенда |
| **runtime-deps / ёмкость** | новая зависимость в `pyproject.toml`, ревизия `pylibinfra[tgbotkit]`, Redis/NATS capacity | хаб |
| **инфра-механика (→ PR в tgbotkit)** | новый middleware (ban-gate, maintenance), новый runner, новый helper (payments/i18n/webapp), новая точка расширения | мейнтейнер `pylibinfra` |

Ни один класс не подходит — это не инфра-изменение, выходи.

## Шаги

### 1. Классифицировать (таблица выше) и определить адресата

- **хаб** (`<org>/infra`): новая env-ручка бота — `${VAR}` в compose-фрагменте бота и в
  `.env.example` хаба, значение (в т.ч. секрет) — в `.env` на VPS; новый сервис-зависимость
  (Redis/NATS), scaling/режим; выкатка — `make bump SVC=bot` (новые ручки дописываются до бампа).
- **мейнтейнер `pylibinfra`**: новая инфра-механика — PR в `tgbotkit` (скилл `/add-kit` в
  `pylibinfra` или правка существующего kit'а). Шаблон может временно нести механику локально и
  вынести её PR'ом (rule `tgbotkit-boundary`) — это явный долг в `## Handoff` плана.

### 2. Сформировать блок

```
=== INFRA HANDOFF · передай в хаб <org>/infra ===
WHAT   <имя/тип, default, required?>
WHY    <фича/причина — коммит/план-атом>
ACTION <конкретное действие инфра-стороны / суть PR в tgbotkit>
WHO    <хаб | pylibinfra>
DECIDE <нужно решение (значение/выбор) или «дефолт N ок?»>
RISK   <последствие бездействия>
===
```

Конкретно. `WHAT: env BOT_MODE, default polling, required в проде=webhook` — годится. `WHAT: что-то
с режимом` — нет: по размытому WHAT/ACTION админ не примет решение. Значение секрета не пиши —
только имя ключа + «нужен» (значения секретов не эхо-ить и не коммитить, в `.env.example` — только
имена).

Для механики: `WHAT: новый outer-middleware maintenance-гейт на dp.update`, `ACTION: PR в
pylibinfra/tgbotkit (цепочка dp.update + конфиг гейта)`, `WHO: pylibinfra`.

### 3. Положить так, чтобы доехало до релиза

- **Чат:** покажи блок с адресатом. Пришёл из корня проекта — верни блок сессии корня вместе с
  результатом фазы; прямой заход — попроси юзера передать его инфра-админу (для механики — «это PR в
  pylibinfra, не правка шаблона»).
- **Активный план:** добавь/дополни раздел `## Handoff` активного плана
  (`.claude/plans/<slug>.md`) — `make release` собирает его в финальный INFRA-HANDOFF. Закрытый
  план удаляется (forward-only), поэтому handoff уходит в релиз или хабу до закрытия; план
  закрывается раньше релиза — строка в `.claude/plans/backlog.md` (её к релизному блоку прикладывают вручную, skill `release`).
- **Нет активного плана:** блок только в чат; проследи, что передача подтверждена, прежде чем
  пометить «готово».

### 4. Граница

`make ship` / `make bump` / `ssh <vps>` / правки чужого репо / merge PR в `pylibinfra` — не зона
этого репо: роль — сформировать и отдать сообщение, дальше действует хаб или мейнтейнер.

## Anti-patterns

- ❌ Пометить инфра-задачу «готово»/закоммитить без предъявленного блока.
- ❌ Написать новый middleware/runner в шаблоне вместо PR в `tgbotkit` (rule `tgbotkit-boundary`).
- ❌ «Допишу на релизе» — release агрегирует уже записанное; не записал в `## Handoff` →
  потеряно.
- ❌ Значение секрета (`BOT_TOKEN`/`BOT_WEBHOOK_SECRET`) в блоке/чате — только имя ключа.
- ❌ Самому деплоить/мержить PR в pylibinfra — чужая зона, чужие креды.
- ❌ Гнать блок на не-инфра-правку — шум обесценивает сигнал.
