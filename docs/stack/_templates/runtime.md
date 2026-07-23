---
id: stack.runtime
kind: runtime
name: runtime
status: draft
---

# Runtime — что и как крутится

## Mode
<Режим рантайма: polling (дев/простой прод) или webhook (прод за reverse-proxy). `BOT_MODE` +
`WEBHOOK_*` (URL, path, secret) при webhook. Выбор задаёт runner kit'а — шаблон только декларирует.>

## In-process
<Что поднимается в ОДНОМ процессе (отдельного worker-образа нет): обработка апдейтов (диалоги),
NATS-подписчики (notifications), периодические jobs. Всё через точки расширения `ExtensionProvider`.>

## Health & lifecycle
<Health-probe (httpkit `/health`; в polling биндится health-порт `HTTP_*`). Graceful shutdown —
в kit'е (`container.close()` → закрытие ресурсов). Что проверяет infra (`make ps` → healthy).>

## Generates
<Что de-template родит:
- `app.py` `run()` (резолв `BotRunner` → run)
- `BotConfig` mode/webhook в `config.py`
- env: `BOT_MODE`, `WEBHOOK_*` (если webhook), `HTTP_*` (health-порт в polling)
- health-wiring (kit)>
