---
id: stack.runtime
kind: runtime
name: runtime
status: draft
---

# Runtime — что и как крутится

## Mode
<Режим рантайма: polling (дев/простой прод) или webhook (прод за reverse-proxy). `BOT_MODE` +
`BOT_WEBHOOK_*` (base URL, path, secret) при webhook. Выбор задаёт runner kit'а — шаблон только декларирует.>

## In-process
<Что поднимается в ОДНОМ процессе (отдельного worker-образа нет): обработка апдейтов (диалоги),
NATS-подписчики (notifications), периодические jobs. Всё через точки расширения `ExtensionProvider`.>

## Health & lifecycle
<Health-порт `HTTP_ADDR` занимает `BotRunner` (`HttpProvider(autostart=False)`) и в polling, и в
webhook: `/health` + `/ready` (пробы Bot API/Redis/NATS из `ExtensionProvider.probes`). Graceful
shutdown — в kit'е (дренаж подписок → `container.close()`). Что проверяет infra (`make ps` → healthy).>

## Generates
<Что de-template родит:
- `app.py` `run()` (лог `starting` → резолв `BotRunner` → run)
- `tgbotkit.Config` (`new_config()` + i18n-каталог) и `httpkit.Config` в `config.py`
- `HttpProvider(autostart=False)`/`ClockProvider()` в `build_container()`
- env: `BOT_MODE`, `BOT_WEBHOOK_*` (если webhook), `HTTP_ADDR` (health-порт)>
