---
id: stack.storage
kind: storage
name: storage
status: draft
---

# Storage — Redis (КРИТИЧНЫЙ)

> **КРИТИЧНЫЙ артефакт: без корректного Redis-storage прод падает на первом деплое.** Memory-
> storage теряет state при рестарте и не работает в мультиинстансе (webhook); отсутствие
> `with_destiny` key-builder ломает изоляцию FSM/dialog; несериализуемые данные падают в Redis.

Бот владеет **только своим state** в Redis (бизнес-данные — на бэкендах). Проводку Redis настраивает
`tgbotkit`; здесь — **значения и инварианты** хранения.

## Engine
<Redis (НЕ Memory!). `REDIS_URL`. Один Redis, три потребителя по префиксам (всё настраивает kit):
- aiogram `RedisStorage` — `fsm:*`, key-builder `with_destiny=True` (обязателен).
- aiogram_dialog — `aiogd:*`.
- cachekit — `cache:*` / `tg:update:*` (дедуп) / identity-link (см. ниже).
Пример: `redis://redis:6379/0`, без пароля в dev, ACL/TLS на проде.>

## Key namespaces (identity-link шаблона)
<Ключи, которые пишет бизнес-логика (формат — `platform/links.py`, общий для фич):
| Ключ | Назначение | Кто пишет | TTL |
|---|---|---|---|
| `link:tg:<id>` | tg_id → backend_user_id (identity-резолв) | при линковке аккаунта | <?> |
| `onboard:tg:<id>` | флаг пройденного онбординга | start.usecase | <?> |
| `link:chat:<ref>` | user_ref → chat_id (куда слать фон) | start (онбординг) | <?> |
Допиши свои продуктовые ключи здесь.>

## Serialization
<**Только JSON-примитивы** в `dialog_data`/`start_data`/`widget_data`: `datetime`→ISO, pydantic
`model_dump(mode="json")`. `Decimal`/ORM/datetime-объекты — нельзя (упадёт). Доменную сущность в
state не кладём — она за gateway, грузится getter'ом. Тесты на `JsonMemoryStorage` ловят
несериализуемое (rule `storage-serialization`).>

## TTL & isolation
<TTL обязательны (диалоговые контексты пишут `{}`, не удаляются сами → утечка). Значения TTL для
FSM/dialog/cache/link. Dedup апдейтов — атомарный `SET NX EX` (kit-middleware). Мультиинстанс
(webhook) — `RedisEventIsolation` (kit) — без неё конкурентные апдейты ломают dialog-стек.>

## Generates
<Что de-template родит:
- `REDIS_URL` в `.env.example`
- `CachekitProvider()` в `app.py` (всегда)
- key-builder `platform/links.py` под твои namespaces
- (webhook) пометка `RedisEventIsolation` в INFRA-HANDOFF (≥2 инстанса требуют один Redis)>
