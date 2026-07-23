# Release

Зона репо: **код → image в registry, STOP.** Деплой — другие репо. Полный флоу — skill `/release`.

## Один образ

В отличие от go-backend (api+migrate lockstep) у бота **нет migrate-образа**: бот stateless, весь
state (FSM/диалоги/dedup/identity-link) живёт в Redis, схему БД он не держит. Фоновые подсистемы
(notifications-подписчики, jobs) поднимаются **в том же процессе** через точки расширения tgbotkit —
отдельного worker-образа тоже нет.

## Одна команда

```bash
make release VERSION=vX.Y.Z
```

`scripts/release.sh`: валидирует semver (`:latest`/lightweight отвергаются) → confirm-промпт →
annotated tag на HEAD → preflight (main / clean / docker-auth) → `docker buildx --platform
linux/amd64 --push` **одного** образа `<host>/<org>/bot:<v>` (multi-stage uv, приватный
`pylibinfra[tgbotkit]` через `--mount=type=ssh`; `VERSION`/`GIT_SHA` зашиты в образ) → печатает
агрегированный **INFRA-HANDOFF** и STOP.

Pre-flight (до команды): зелёный `make check` + startup-smoke (`pytest -k collision`: `setup_dialogs`
без коллизий `StatesGroup` — кривой State-граф не падает на CI юнитов, но уронит бот на старте).

## Версионирование (semver)

- **patch** — bugfix без изменения флоу/контрактов.
- **minor** — новая фича/диалог, новые ключи i18n, обратно совместимо.
- **major** — **удаление/переименование живого `State`** (ломает открытые диалоги), breaking
  notification-subject / контракт бэкенда.

Удаление State релизится только как major и только через `state-migration` (deprecation) —
[architecture.md](architecture.md § Non-goals), rule `state-lifecycle`.

## Handoff (НЕ в этом репо)

`make release` печатает `=== INFRA HANDOFF ===`: `bot_tag → <v>`; накопленные `**Infra impact.**` из
активных секций `.claude/plans/roadmap.md` (rule `infra-impact`); действия инфра-стороны: пин образа
(`bot_tag=<v>`) в конфиге деплой-репо `<org>/infra` → `make ship`. `make ship`/`ssh` отсюда
**не выполняются** — оператор передаёт блок out-of-band.

## Verify (в infra-репо)

`make ps` → bot `healthy` (httpkit `/health`); в логах на старте `"starting" service=<bot>
version=<v> commit=<sha>`.

## Откат

Полностью в infra-репо: пин `bot_tag=<предыдущий>` в конфиге деплой-репо → `make ship`. ⚠️ Откат образа
**не откатывает удалённый State**: если в релизе вырезали живой State, dialog-stack юзеров в Redis
ссылается на исчезнувший State (`UnknownState`) — откат их не «вернёт». Поэтому удаление State —
всегда через `state-migration`, не «откатим если что».
