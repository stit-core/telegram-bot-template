---
name: release
description: Запушить новую версию образа бота в registry ОДНОЙ командой (один образ — migrate-образа нет, бот stateless, FSM в Redis) и передать инфра-админу агрегированный handoff. Активируй когда пользователь говорит "релиз", "запушим версию", "сделай release vX.Y.Z", "/release".
---

# Skill: release

Канонический release-флоу бота. **Зона ответственности этого репо: код → image в registry. На STOP — всё.** Build локальный, push в `<host>/<org>/bot` под одним `vX.Y.Z`-тегом.

**Один образ.** В отличие от go-backend (api+migrate lockstep) у бота **нет migrate-образа**: бот stateless, весь state (FSM/диалоги/dedup/identity-link) живёт в Redis, схему БД он не держит. Фоновые подсистемы (notifications-подписчики, jobs) поднимаются **в том же процессе** через точки расширения tgbotkit — отдельного worker-образа тоже нет.

Дальше — **handoff** в проектный infra-репо: обновить `bot_tag`/env в compose и `make ship`. Этот шаг не выполняется здесь — `make release` печатает агрегированный INFRA-HANDOFF-блок, оператор передаёт его out-of-band.

## Когда применять

- "Релизим v1.2.3" / "Запушь новую версию" / "/release"
- После закрытия задачи и зелёного `make check`, когда юзер сказал "пора катить".

## Когда НЕ применять

- "Собери image локально для теста" → `docker buildx build --load -t bot-local .`, не `make release`.
- Пуш feature-веточного билда → preflight отвергает не-main.
- Юзер не озвучил OK на релиз → STOP, спроси.

## Pre-flight (BEFORE команды)

Любой пункт не закрыт — не лезь:

- [ ] Юзер явно сказал OK на релиз (тег + push — действие видимое вне репо).
- [ ] `make status` показывает: `main`, working tree clean, нет активных не-release планов.
- [ ] `make check` зелёный (ruff + import-linter + mypy + pytest). Если нет — STOP → `triage-failure`.
- [ ] **Startup-smoke зелёный** (`pytest -k collision` / `test_composition`): контейнер собирается, `setup_dialogs` не ловит коллизий StatesGroup. Это критично для бота — кривой State-граф не падает на CI юнитов, но уронит бот на старте в проде.
- [ ] Юзер знает версию (semver-bump по уровню изменений).
- [ ] Оператор залогинен в registry (`docker login <host>` — вне процесса, не делай сам).

## Шаги в этом репо

### 1. Подтвердить версию (semver-bump)

Спроси у юзера версию в формате `vX.Y.Z`. Не угадывай. Подскажи уровень:
- patch (`v1.2.3 → v1.2.4`) — bugfix без изменения флоу/контрактов.
- minor (`v1.2.3 → v1.3.0`) — новая фича/диалог, новые ключи i18n, обратно совместимо.
- major (`v1.2.3 → v2.0.0`) — **удаление/переименование живого State** (ломает открытые диалоги), breaking-изменение notification-subject/контракта бэкенда.

Нет предыдущих тегов — старт с `v0.1.0`.

**Rich changelog (опц.):** нужен содержательный annotated-tag message — оператор создаёт тег заранее: `git tag -a vX.Y.Z -m "<changelog>"`. `make release` детектит существующий тег на HEAD и использует его.

### 2. Одна команда

```bash
make release VERSION=vX.Y.Z
```

`scripts/release.sh` делает за тебя, по порядку:
1. валидирует `VERSION` (semver; `:latest`/`:edge`/lightweight отвергаются);
2. **confirm-промпт** (нет TTY/EOF → отмена, accidental release невозможен);
3. annotated tag, если на HEAD ещё нет (иначе использует существующий; конфликт версий → fail);
4. preflight: ветка=main / clean / annotated semver на HEAD / docker-auth — fail-fast;
5. `docker buildx --platform linux/amd64 --push` **одного** образа `<host>/<org>/bot:<v>` (multi-stage uv, приватный `pylibinfra[tgbotkit]` через `--mount=type=ssh`), `VERSION`/`GIT_SHA` зашиты в образ (версия/коммит билда);
6. печатает агрегированный **INFRA-HANDOFF** и STOP.

---

**После команды образ в registry. Зона этого репо закрыта.**

## Handoff (НЕ в этом репо — генерируется автоматически)

`make release` сам печатает блок `=== INFRA HANDOFF ===`:

- `bot_tag → <v>` (один образ);
- **накопленные `**Infra impact.**`** — `release.sh` агрегирует блоки из активных секций `.claude/plans/roadmap.md` (механизм — rule `infra-impact` + skill `infra-handoff`). Если пусто — печатает напоминание убедиться, что инфра-затрагивающее зафиксировано;
- действие инфра-стороны:
  - проект: в `<client-org>/infra` обнови `bot_tag=<v>` (env в compose) → `make ship`.

Твоя роль после команды: **показать блок юзеру и сказать передать инфра-админу out-of-band**. Подставь `project`/`env`, если юзер их называл. `make ship`/`ssh` отсюда **не выполняются**.

### Verify (в infra-репо, не здесь)

`make ps` → bot `healthy` (httpkit `/health`); в логах на старте `"starting" service=<bot> version=<v> commit=<sha>`.

## Откат

**Полностью в infra-репо** (этот репо не участвует — образ в registry):
1. в `<client-org>/infra` верни `bot_tag=<предыдущий>` (env в compose);
2. `make ship`.

⚠️ Откат образа **не откатывает удалённый State**: если в релизе вырезали живой State, у юзеров в открытых диалогах уже `UnknownState` — откат образа их не «вернёт», т.к. их dialog-stack в Redis ссылается на исчезнувший State. Поэтому удаление State — всегда через `state-migration` (deprecation), а не «откатим если что».

## Anti-patterns

- ❌ `git tag vX.Y.Z` без `-a`. Lightweight tag отвергнет preflight.
- ❌ `make release` минуя зелёный `make check` / startup-smoke. Красное — STOP, в `triage-failure`.
- ❌ `make release` не на main. Preflight отвергнет.
- ❌ `docker login <host>` сам. Креды оператора.
- ❌ `:latest` / `:edge` / любой не-semver tag.
- ❌ Думать про «migrate-образ» — его нет (бот stateless, один образ).
- ❌ Релизить удаление State как patch/minor — это major и только через `state-migration`.
- ❌ Выполнять `make ship` / `ssh <vps>` из этого репо. Наша роль — образ в registry + текст-handoff.
