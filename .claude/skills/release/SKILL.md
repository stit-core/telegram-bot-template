---
name: release
description: Выпустить версию бота — одной командой make release собрать и запушить единственный образ <registry>/<org>/bot:vX.Y.Z (migrate-образа нет — бот stateless, FSM в Redis) и отдать хабу <org>/infra агрегированный INFRA-HANDOFF; дальше STOP. Используй, когда юзер хочет релиз, выпустить или запушить версию, закончить фазу образом для хаба (/release).
---

# Skill: release

Канонический release-флоу бота. **Зона ответственности этого репо: код → image в registry. На
STOP — всё.** Build локальный, push в `<registry>/<org>/bot` под одним `vX.Y.Z`-тегом: registry и
орга выводятся из `git remote origin` (Gitea `git.stit.tech`), registry переопределяется env
`REGISTRY`.

**Один образ.** В отличие от go-backend (api+migrate lockstep) у бота **нет migrate-образа**: бот
stateless, весь state (FSM/диалоги/dedup/identity-link) живёт в Redis, схему БД он не держит.
Фоновые подсистемы (notifications-подписчики, jobs) поднимаются **в том же процессе** через точки
расширения tgbotkit — отдельного worker-образа тоже нет.

Дальше — **handoff в хаб `<org>/infra`**: rollout — `make bump SVC=bot TAG=<v>` там (правит `BOT_TAG`
в `.env` на VPS + force-recreate; новые env-ручки инфра-админ дописывает в `.env` до бампа). Здесь
этот шаг не выполняется — `make release` печатает агрегированный INFRA-HANDOFF-блок для хаба.

## Когда применять

- «Релизим v1.2.3» / «Запушь новую версию» / `/release`.
- После закрытия задачи и зелёного `make check`, когда юзер сказал «пора катить»; фаза программы
  хаба — её результат для хаба и есть этот образ + handoff.

## Когда не применять

- «Собери image локально для теста» → `docker buildx build --load -t bot-local .`, не `make release`.
- Пуш feature-веточного билда → preflight отвергает не-main.
- Юзер не дал явного OK на релиз → остановись и спроси: тег и push видны вне репо.

## Pre-flight (до команды)

Любой пункт не закрыт — команду не запускай. Скрипт создаёт annotated-тег **до** своего preflight,
поэтому упавший preflight оставит локальный тег — ветку и чистоту дерева проверь заранее:

- [ ] Юзер явно сказал OK на релиз (тег + push — действие видимое вне репо).
- [ ] `make status` показывает: `main`, working tree clean, нет активных не-release планов.
- [ ] `make check` зелёный (ruff + import-linter + mypy + lock-check + pytest). Нет — стоп →
      `triage-failure`.
- [ ] **Startup-smoke зелёный** (`pytest -k collision` / `test_composition`): контейнер собирается,
      `setup_dialogs` не ловит коллизий StatesGroup — кривой State-граф не виден юнит-тестам, но
      уронит бот на старте в проде.
- [ ] Юзер знает версию (semver-bump по уровню изменений).
- [ ] Оператор залогинен в registry (`docker login <host>` делает он сам: это его креды).

## Шаги в этом репо

### 1. Подтвердить версию (semver-bump)

Спроси у юзера версию в формате `vX.Y.Z`, не угадывай. Подскажи уровень:
- patch (`v1.2.3 → v1.2.4`) — bugfix без изменения флоу/контрактов.
- minor (`v1.2.3 → v1.3.0`) — новая фича/диалог, новые ключи i18n, обратно совместимо.
- major (`v1.2.3 → v2.0.0`) — **удаление/переименование живого State** (ломает открытые диалоги),
  breaking-изменение notification-subject/контракта бэкенда.

Нет предыдущих тегов — старт с `v0.1.0`.

**Rich changelog (опц.):** нужен содержательный annotated-tag message — оператор создаёт тег
заранее: `git tag -a vX.Y.Z -m "<changelog>"`. `make release` детектит существующий тег на HEAD и
использует его.

### 2. Одна команда

```bash
make release VERSION=vX.Y.Z
```

`scripts/release.sh` делает за тебя, по порядку:
1. валидирует `VERSION` (semver; `:latest`/`:edge`/lightweight отвергаются);
2. **confirm-промпт** (нет TTY/EOF → отмена, accidental release невозможен);
3. annotated tag, если на HEAD ещё нет (иначе использует существующий; конфликт версий → fail);
4. preflight: ветка=main / clean / annotated semver на HEAD / buildx / docker-auth — fail-fast;
5. `docker buildx --platform linux/amd64 --push` **одного** образа `<registry>/<org>/bot:<v>`
   (multi-stage uv, приватный `pylibinfra[tgbotkit]` через build-secret `git_token`),
   `SERVICE_VERSION`/`GIT_COMMIT` зашиты в образ (версия/коммит билда → лог `starting`);
6. печатает агрегированный **INFRA-HANDOFF** и STOP.

---

**После команды образ в registry. Зона этого репо закрыта.**

## Handoff (выполняется в хабе, не здесь)

`make release` сам печатает блок `=== INFRA HANDOFF ===`:

- `BOT_TAG → <v>` (один образ);
- **накопленный handoff** — `release.sh` собирает разделы `## Handoff` активных планов
  `.claude/plans/` (механизм — rule `infra-impact` + skill `infra-handoff`). Пусто —
  печатает напоминание убедиться, что инфра-затрагивающее зафиксировано;
- действие хаба: в `<org>/infra` — `make bump SVC=bot TAG=<v>` (правит `BOT_TAG` в `.env` на VPS +
  force-recreate).

Бэклог скрипт не читает: строки INFRA-HANDOFF, отложенные туда до релиза, найди в `.claude/plans/backlog.md` и
приложи к блоку сам. Твоя роль после команды — отдать блок хабу: пришёл из корня проекта — верни
его с тегом сессии корня; прямой заход — покажи юзеру и попроси передать инфра-админу. Подставь
`project`/`env`, если юзер их называл. `make ship`/`make bump`/`ssh` отсюда не выполняются.

### Verify (в хабе, не здесь)

`make ps` → bot `healthy` (httpkit `/health`; `/ready` — пробы Bot API/Redis/NATS); в логах
(`make logs SVC=bot`) на старте `"starting" service=bot version=<v> commit=<sha>`.

## Откат

**Полностью в хабе** (этот репо не участвует — образ в registry):
`make bump SVC=bot TAG=<предыдущий>`.

⚠️ Откат образа **не откатывает удалённый State**: если в релизе вырезали живой State, у юзеров в
открытых диалогах уже `UnknownState` — откат образа их не «вернёт», т.к. их dialog-stack в Redis
ссылается на исчезнувший State. Поэтому удаление State — всегда через `state-migration`
(deprecation), а не «откатим если что».

## Anti-patterns

- ❌ `git tag vX.Y.Z` без `-a`. Lightweight tag отвергнет preflight.
- ❌ `make release` минуя зелёный `make check` / startup-smoke. Красное — стоп, в `triage-failure`.
- ❌ `make release` не на main. Preflight отвергнет — уже после создания тега.
- ❌ `docker login <host>` самому. Креды оператора.
- ❌ `:latest` / `:edge` / любой не-semver tag: скрипт их отвергает, а хабу нужен тег для отката.
- ❌ Релизить удаление State как patch/minor — это major и только через `state-migration`.
- ❌ Выполнять `make ship` / `make bump` / `ssh <vps>` из этого репо. Наша роль — образ в registry +
  handoff для хаба.
