---
name: background-updates
description: Фоновая доставка (notifications/jobs) идёт мимо обычной middleware-цепочки — request_id/грабли BgManager закрыты в tgbotkit.Delivery; локаль deliver_* резолвит сам и рендерит через Delivery.localize. Шаблон пишет только бизнес. Terse; «как и почему» — docs/reference/architecture.md § Фоновые апдейты. Грузится при правке notification*/deliver*-файлов.
paths:
  - "**/notification*.py"
  - "**/deliver*.py"
---

# Фоновые апдейты (доставка)

Push из событий бэкенда (NATS) и периодика **не приходят как обычный Update** — у них нет
incoming-апдейта, поэтому они идут мимо outer-middleware (request_id, dedup, locale-resolve).
Эти грабли закрыты в `tgbotkit.Delivery`/`NotificationRunner`; шаблон пишет только бизнес-маппинг
`event → сообщение/диалог`. Фоновые dialog-апдейты внутри kit идут через `propagate_event("update")`.

## Инварианты

- **Отправляй через `Delivery`** (аргумент `deliver_*`), не через сырой `BgManager`/`bot.*`.
  `Delivery` закрывает `request_id` (фон вне middleware), пустой стек → safe, EDIT не гарантирован,
  throttle. **Локаль фон НЕ резолвит автоматически** (нет I18nMiddleware): `deliver_*` берёт её сам
  (`LocalePrefStore.get(user_id)`) и рендерит ключ через `Delivery.localize(locale, key, args)`.
  Сырой `BgManager` мимо `Delivery` — нет.
- **Идемпотентность обязательна** (JetStream durable = at-least-once): `token = await
  dedup.reserve(<event-key>)` ДО отправки (`None` — дубль или доставка уже идёт у соседа → выход)
  → `commit(key, token)` после успеха → `release(key, token)` на сбое. `commit` вернул `False` —
  резерв истёк на медленной доставке и ушёл соседнему воркеру: запиши warn
  (`notifications.reservation_lost`), не глотай. Ключ стабильный по событию
  (`order-paid:<order_id>`), не по времени. Сбой доставки **пробрасывай** (не глотать) — `JsBus`
  сделает `nak`, а снятый `release` резерв даст redelivery повторить. «Вряд ли задвоится» — не
  аргумент. (Тот же токенный `reserve/commit/release` у `ChargeGuard`/`RefundGuard` для
  successful/refunded_payment.)
- **`deliver_*` — быстрый**: дедуп → резолв `chat_id` → резолв локали → `localize` → отправка.
  Тяжёлое (батч, рендер) — в usecase/job, не в обработчике доставки.
- **`chat_id` резолвится по link tg→chat** (его пишет онбординг, напр. `start.mark_onboarded`);
  нет link (пользователь не онбордился) — **тихо пропустить**, не падать, не слать в `tg_id`.
- Какие `stream`/`subject`/`durable` и `deliver_*` — здесь (`build_router` →
  `router.on(stream, subject, durable, handler)`); механика подписки/ack/`drain` на shutdown —
  в kit, не дублировать.
- `notifications` — не диалог-гексагон (вне трёх import-linter-контрактов); это NATS-router +
  `deliver_*`. Фасад отдаёт `build_router(cache, redis, log)` в `NotifierBundle` (через
  `ExtensionProvider`, т.к. нужны `cache`+`redis`+`log` из контейнера).

## Чек

- Тест доставки мокает `Delivery` (фейк `tests/_fakes/delivery.py`), Redis/кэш — `MemoryRedis`/
  `MemoryCache` lib'ы; проверяет «второе событие не доставлено», «нет link → не отправлено»,
  «сбой доставки → проброс + `release` → повтор доставляет» и «истёкший резерв → warn» (фейк
  умеет инъецировать сбой, `Tickable` двигает TTL; rule `tests-pipeline`).
- Новый/изменённый NATS-subject (контракт с бэкендом) → INFRA-HANDOFF (rule `infra-impact`).
- Нужна новая фоновая механика (новый вид runner'а, middleware на фон) — PR в `tgbotkit`
  (rule `tgbotkit-boundary`), не правка шаблона.
