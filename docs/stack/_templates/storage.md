---
id: stack.storage
kind: storage
name: storage
status: draft
---

# Storage — Redis (FSM/dialog state)

⚠️ **Критичный артефакт.** Бот stateless по коду: весь state (FSM-состояния, dialog_data, dedup,
identity-link, кэш onboarding) живёт в Redis. Без реального Redis (не Memory) прод теряет диалоги
при рестарте.

## Backend
<`REDIS_URL` (дефолт-дев `redis://localhost:6379/0`). RedisStorage даёт kit (BotProvider) — шаблон
только указывает источник конфигурации.>

## Keys & TTL
<Префикс ключей, схема `with_destiny` (изоляция destiny для виджет-данных), TTL FSM-стейта
(`BOT_STATE_TTL`, дефолт 0 = вечно). Что копится и когда истекает.>

## Serialization invariant
<Всё в `dialog_data`/`start_data`/`widget_data` — только JSON-примитивы (нет `datetime`-объектов/
`Decimal`/ORM). Доменная сущность не хранится — грузится getter'ом каждый рендер. Rule
`storage-serialization`.>

## Generates
<Что de-template родит:
- storage-wiring (kit, через BotProvider) в `app.py`/`config.py`
- env: `REDIS_URL`, опц. `BOT_STATE_TTL`
- инвариант сериализации (rule, не код)>
