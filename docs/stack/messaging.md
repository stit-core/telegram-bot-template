---
id: stack.messaging
kind: messaging
name: messaging
status: draft
---

# Messaging — NATS push-уведомления

События бэкенда → push в Telegram. Транспорт — `natskit`; механика подписки/доставки/drain — в
`tgbotkit` (`NotificationRunner`/`Notifier`/`Delivery`/`DeliveryDedup`). Шаблон описывает **какие
subjects** и **deliver_*** (event→сообщение/диалог). Если push-уведомлений нет — артефакт пустой,
`NatsProvider`/notifications не подключаются.

## Subscribed subjects
<Список subject'ов, на которые подписан бот, и что доставляет. Пример (reference `orders`):
| Stream | Subject | Durable | Deliver | Сообщение |
|---|---|---|---|---|
| orders | orders.paid | bot-orders-paid | OrderDeliverer.on_order_paid | «Оплата заказа N получена» |
Регистрация — `features/notifications/build_router` → `NotificationRouter.on(stream, subject,
durable, handler)`.>

## JetStream vs core
<**JetStream durable + explicit ack** — для уведомлений, которые нельзя потерять (заказы/платежи);
core-NATS — для эфемерных. `NATS_JETSTREAM_ENABLED`, `NATS_JS_STREAM_NAMES`. notifications активны
**только при включённом JetStream** (иначе `OptionalStreamBus`=None → runner пропустит).>

## Delivery (грабли фона)
<Фоновые апдейты доставки идут **вне обычного middleware** — `request_id`/локаль проставляет
`Delivery`-обёртка (грабли BgManager закрыты в kit'е). Дедуп — at-least-once (JetStream может
доставить дважды) → `DeliveryDedup.seen(<key>)`. Резолв адресата — `chat_id` по `link:chat:<ref>`
(пишет start при онбординге); нет линка → тихо пропустить. EDIT не гарантирован (сообщение могло
быть удалено). Опиши свои deliver_* и их дедуп-ключи.>

## Generates
<Что de-template родит:
- `NatsProvider()` в `app.py` + `NATS_*` в `.env.example` (если есть push)
- `features/notifications/` (NotificationRouter + deliver_*) + регистрация `NotifierBundle`
- `OptionalStreamBus` провайдер в `extensions.py` (gated по JetStream)
- cross-service subjects → INFRA-HANDOFF (бэкенд должен публиковать их)>
