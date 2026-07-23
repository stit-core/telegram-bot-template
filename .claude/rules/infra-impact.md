---
name: infra-impact
description: Изменение инфра-поверхности (env/секрет/webhook/NATS-subject/runtime-dep) ОБЯЗАНО породить INFRA-HANDOFF-блок до claim «готово»/коммита. Процедура — skill infra-handoff. Грузится при правке config.py/.env*/Dockerfile/notification*.
paths:
  - "src/bot/config.py"
  - ".env*"
  - "Dockerfile"
  - "**/notification*.py"
---

# Infra-impact

Репо останавливается на image-in-registry; деплой, env и секреты — проектный infra (compose env).
Изменение, **требующее действия инфра-стороны**, молча разъедется с прод-окружением, если его не
зафиксировать. Процедура и формат блока — skill `infra-handoff` (это soft-механизм: правило + skill,
гарантия — в твоей дисциплине).

**Железобетонно:** тронул инфра-поверхность → до claim «готово»/коммита оформи `INFRA-HANDOFF`-блок
и **попроси юзера передать инфра-админу** out-of-band. Не молчи, не «потом».

## Что считается инфра-поверхностью

| Класс | Триггер | Кому |
|---|---|---|
| **Env/секреты** | новый/изменённый required env (`BOT_*`/`APP_*`/`REDIS_URL`/`NATS_*`/`HTTPCLIENT_*`), читаемый приложением; новый required секрет (`BOT_TOKEN`/`BOT_WEBHOOK_SECRET`-класс) | проект (compose env) |
| **Webhook/runtime-режим** | `BOT_MODE` polling↔webhook, `BOT_WEBHOOK_*` (base_url/path/secret), число инстансов, graceful-параметры | проект (ingress/TLS, ≥2 инстанса, single-flight set_webhook) |
| **Cross-service контракт** | новый/изменённый NATS `stream`/`subject`/`durable` для событий бэкенда; breaking-изменение payload `deliver_*` | проект + владелец события |
| **Runtime-deps/ёмкость** | новая внешняя зависимость (включить JetStream, новый бэкенд `*_BASE_URL`); смена `pylibinfra`-ревизии в `pyproject`; изменения Dockerfile (база/extra) | проект |

Не-инфра: внутренняя бизнес-логика, тесты, рефактор без смены env/контракта/зависимостей,
code-default тюнинг без нового обязательного ENV.

## Куда кладётся (чтобы доехало до релиза)

1. **В чат** — блок юзеру с явным «передай инфра-админу out-of-band».
2. **В активный план** — подсекция `**Infra impact.**` в `### `-секции `.claude/plans/roadmap.md`;
   `make release` агрегирует её в финальный handoff. План forward-only — infra-impact обязан
   переехать в release-handoff **до** закрытия секции (skill `plan`).

Нет активного плана (мелкая правка) — блок только в чат, проследи фиксацию передачи.

## Инварианты

- Блок — **до** claim/коммита, не после. Один блок на одно цельное изменение. Конкретика: имя
  переменной, дефолт, required-флаг, точное действие, адресат (корп vs проектный infra).
- ❌ Молча закоммитить required env / webhook-переключение / cross-service-subject без блока.
- ❌ Откладывать «на релиз» — там агрегируется уже записанное; не записал → потерял.
- ❌ Самому `make ship`/`ssh`/`set_webhook` — не зона репо.
- ❌ **Значение секрета** в блок/чат — только имя ключа + факт «нужен» (значения секретов не коммить и не эхо-ить; в `.env.example` — только имена).
- Новая инфра-**механика** (а не значение) — это вообще не правка шаблона, а PR в `tgbotkit`
  (rule `tgbotkit-boundary`), тоже через `infra-handoff`.

## Сигналы, что ты здесь

- Правишь файл под `paths:` этого правила (оно само в контексте).
- `make status` → infra-touch не `none` / `make release` напомнил про пустой `**Infra impact.**`.
