---
id: stack.runtime
kind: runtime
name: runtime
status: draft
---

# Runtime — что крутится в процессе

Вся проводка рантайма — в `tgbotkit.BotRunner`; здесь — **выбор режима** и что подключается.

## Mode (polling vs webhook)
<`BOT_MODE=polling|webhook`. Выбор и почему:
- **polling** — 1 инстанс, long-polling, HTTP-сервера нет. Дефолт для dev и простого прода.
- **webhook** — поверх httpkit (ingress/TLS), ≥2 инстанса (`RedisEventIsolation`), single-flight
  `set_webhook`, health `/health`+`/ready`. Для высокой нагрузки / нескольких реплик.
Пример: `webhook`, 2 реплики за nginx-ingress, `BOT_WEBHOOK_BASE_URL=https://bot.example.com`.>

## Entrypoints (что регистрируется в BotRunner)
<Что подключает шаблон через точки расширения (`extensions.py`):
- `RouterBundle` — фиче-диалоги (список диалогов).
- `CommandBundle` — команды и dispatcher-level хендлеры (`/start`, `pre_checkout`, `/language`, …).
- `NotifierBundle` — NATS→Telegram подписчики (если есть notifications; иначе пусто).
- периодические джобы (`timerkit`) — если есть.
Пример: routers=[start, profile, payments, lang]; commands=[/start, pre_checkout, paid, /language].>

## Lifecycle
<Порядок: dishka-контейнер → `container.get(Tracer)` (telemetry.init) → `container.get(BotRunner)`
→ `runner.run()`. Внутри runner'а: storage+isolation, middleware-цепочка, `setup_dishka`,
`setup_dialogs` (последним), `emit_startup` (smoke), polling|webhook.>

## Shutdown
<Graceful shutdown (в kit'е): drain in-flight апдейтов → `container.close()` (telemetry-flush) →
`bot.session.close()`. NATS-подписчики (notifications) — `drain()` на shutdown. Что важно
дренировать в твоём боте (незавершённые платежи/доставки).>

## Generates
<Что de-template родит:
- значение `BOT_MODE` в `.env.example` + (webhook) `BOT_WEBHOOK_*`
- какие kit-провайдеры в `app.py` (NatsProvider только если есть notifications; httpkit — webhook)
- состав `RouterBundle`/`CommandBundle`/`NotifierBundle` в `extensions.py`
- (webhook) число реплик в INFRA-HANDOFF>
