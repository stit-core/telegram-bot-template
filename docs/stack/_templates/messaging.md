---
id: stack.messaging
kind: messaging
name: messaging
status: draft
---

# Messaging — NATS (входящие события → уведомления)

## Subjects (consumed)
<Какие доменные события бот слушает (subject → подписчик → действие: сообщение/диалог). Бот —
консьюмер: он не публикует доменные события, он на них реагирует (notifications). Источник
subject'ов — `notification.md` стратегии-репо (`trigger: event:<ctx>.<Event>`).>

## JetStream & delivery
<Включён ли JetStream (без него notifications выключены — `OptionalStreamBus` = None, runner их
пропускает). Durable/stream, `NATS_JS_*` (max-deliver/backoff/DLQ). Доставка — `tgbotkit.Delivery`
(локаль/request_id мимо middleware-цепочки, rule `background-updates`).>

## Idempotency
<Ключ дедупликации на каждого подписчика (NATS at-least-once → повтор не шлёт второе сообщение).
Где хранится отметка обработанного (Redis/dedup).>

## Generates
<Что de-template/scaffold родят:
- `features/notifications/` (router + `deliver`) + регистрация `NotifierBundle` в `app.py`
- `OptionalStreamBus` (JetStream-гейт) в `ExtensionProvider`
- env: `NATS_URL`, `NATS_JS_*`, DLQ-subject>
