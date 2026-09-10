---
id: stack.dependencies
kind: dependencies
name: dependencies
status: draft
---

# Dependencies — pylibinfra и runtime-deps

## pylibinfra pin
<Единственная рантайм-зависимость: `pylibinfra[tgbotkit]`, пин по git-ref в `[tool.uv.sources]`
(`rev=<commit>`; финально — релиз-тег). Ноль прямых инфра-пинов — вся инфра приходит extra `[tgbotkit]`
(tgbotkit + aiogram + aiogram_dialog + fluent.runtime) + транзитивом (dishka/redis/httpx/otel/fastapi/nats).>

## Kits used
<Какие kit'ы pylibinfra реально задействованы: tgbotkit, httpclient, cachekit, natskit, logkit,
httpkit (health-порт + webhook), clockkit (часы для лимитов), healthkit (пробы `/ready`).
Не тянуть лишнее.>

## External runtime-deps
<Внешние сервисы рантайма: Redis (обязателен), NATS (если notifications), продуктовые HTTP-бэкенды.
Их адреса — через env (storage/messaging/backends).>

## Capacity & dev-only
<Ожидаемая нагрузка/лимиты (если значимо). Dev-only зависимости (`aiogram-dialog[tools]`+graphviz для
`/preview-flow`) — не в рантайм, только dev-группа.>

## Generates
<Что de-template родит:
- `[tool.uv.sources]` пин `pylibinfra` (rev) в `pyproject.toml`
- набор extras `pylibinfra[tgbotkit]` (+ testkit в dev)
- заметки о внешних runtime-deps (указатель, не код)>
