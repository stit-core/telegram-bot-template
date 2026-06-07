---
name: background-updates
description: Фоновая доставка (notifications/jobs) идёт мимо обычной middleware-цепочки — request_id/локаль/грабли BgManager закрыты в tgbotkit.Delivery, шаблон пишет только бизнес. Terse; «как и почему» — design/ARCHITECTURE.md §11. Грузится при правке notification*/deliver*-файлов.
paths:
  - "**/notification*.py"
  - "**/deliver*.py"
---

# Фоновые апдейты (доставка)

Push из событий бэкенда (NATS) и периодика **не приходят как обычный Update** — у них нет
incoming-апдейта, поэтому они идут мимо outer-middleware (request_id, dedup, span, locale-resolve).
Эти грабли закрыты в `tgbotkit.Delivery`/`NotificationRunner`; шаблон пишет только бизнес-маппинг
`event → сообщение/диалог`. Фоновые dialog-апдейты внутри kit идут через `propagate_event("update")`.

## Инварианты

- **Отправляй через `Delivery`** (аргумент `deliver_*`), не через сырой `BgManager`/`bot.*`.
  `Delivery` закрывает: фон вне middleware → `request_id`/локаль руками, пустой стек → safe,
  EDIT не гарантирован, throttle. Сырой `BgManager` мимо `Delivery` — нет.
- **Идемпотентность обязательна** (JetStream durable = at-least-once): `reserve(<event-key>)` ДО
  отправки → `commit` после успеха → `release` на сбое. Ключ стабильный по событию
  (`order-paid:<order_id>`), не по времени. Сбой доставки **пробрасывай** (не глотать) — `JsBus`
  сделает `nak`, а снятая `release`-резервация даст redelivery повторить. «Вряд ли задвоится» — не
  аргумент. (Тот же `reserve/commit/release` у `ChargeGuard` для successful_payment.)
- **`deliver_*` — быстрый**: дедуп → резолв `chat_id` → отправка. Тяжёлое (батч, рендер) — в
  usecase/job, не в обработчике доставки.
- **`chat_id` резолвится по link tg→chat** (его пишет онбординг, напр. `start.mark_onboarded`);
  нет link (пользователь не онбордился) — **тихо пропустить**, не падать, не слать в `tg_id`.
- Какие `stream`/`subject`/`durable` и `deliver_*` — здесь (`build_router` →
  `router.on(stream, subject, durable, handler)`); механика подписки/ack/`drain` на shutdown —
  в kit, не дублировать.
- `notifications` — не диалог-гексагон (вне трёх import-linter-контрактов); это NATS-router +
  `deliver_*`. Фасад отдаёт `build_router(cache, redis)` в `NotifierBundle` (через
  `ExtensionProvider`, т.к. нужны `cache`+`redis` из контейнера).

## Чек

- Тест доставки мокает `Delivery` (фейк `tests/_fakes/delivery.py`) + дедуп; проверяет «второе
  событие не доставлено», «нет link → не отправлено» и «сбой доставки → проброс + `release` →
  повтор доставляет» (фейк умеет инъецировать сбой; rule `tests-pipeline`).
- Новый/изменённый NATS-subject (контракт с бэкендом) → INFRA-HANDOFF (rule `infra-impact`).
- Нужна новая фоновая механика (новый вид runner'а, middleware на фон) — PR в `tgbotkit`
  (rule `tgbotkit-boundary`), не правка шаблона.
