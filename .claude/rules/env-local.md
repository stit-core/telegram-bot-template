---
name: env-local
description: Формат и правила ./.env.local — gitignored файл с dev-tooling токенами (чтение прод-логов через корп-Loki/query-logs). Доступ к значению токена — через tools, не цитированием в чат. Грузится при работе с .env.local.
paths:
  - ".env.local"
---

# Dev tokens — .env.local

`./.env.local` хранит токены для **dev-tooling** (bearer'ы внешних API — observability), нужные
агент-тулам при работе с проектом. Это **не** runtime-секреты приложения — те в `.env` (локально)
или Vault + vault-agent (прод). Образец — `.env.local.example` (плейсхолдеры + откуда токен).

- Живёт в корне, в `.gitignore`. Committed только `.env.local.example`. В авто-backup'ы не уезжает.
- **Формат:** dotenv, `KEY=value` на строку. Парсится `grep`'ом, **не** `source`'ом — без
  многострочных значений, `$`-подстановок, inline-команд. `export `-префикс и кавычки допустимы.

## Security-инвариант

- **Доступ к значению токена — только через tools.** Скрипт `query-logs`/`logs.sh` сам `grep`-ает
  `KEY=` и передаёт значение внутри bash-процесса — в stdout/transcript оно не попадает.
- ❌ **`Read`/`cat` ради токена — необратимая утечка** в transcript (и память, если включена):
  придётся ротировать. Нужен токен — зови agent-tool, не вытаскивай значение в чат.
- ❌ Коммитить `.env.local` (gitignore страхует, но `git add -A` цепляет — проверяй `git status`;
  `permissions.deny` на правку `.env*`/`*.key` — вторая линия).
- ❌ Класть dev-tooling токены в `.env`/`.env.example` (там runtime приложения, rule `infra-impact`)
  или хранить здесь долгоживущие прод-секреты (их место — Vault).
- Правит файл предпочтительно юзер руками; если Claude — не эхо-ить значения. Ротация — обновить
  `.env.local` + источник (корп-Vault).

## Известные ключи

| Ключ | Используется | Документация |
|---|---|---|
| `SFTBMB_OBS_TOKEN` | `query-logs` (чтение прод-логов/трейсов) | skill `query-logs`; источник — корп-Vault `kv/projects/<p>/<env>/otel` |
| `SFTBMB_LOKI_ADDR` | `query-logs` (адрес корп-Loki read API; обязателен) | skill `query-logs` |
| `OTEL_TENANT` | e2e otel-agent | совпадает с `service_namespace` (корп-инвариант) |
