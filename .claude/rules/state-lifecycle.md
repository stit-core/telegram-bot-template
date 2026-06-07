---
name: state-lifecycle
description: Эволюция StatesGroup/State — через deprecation, не удаление (живые State в открытых диалогах сломаются после деплоя). Terse; процедура — skill state-migration. Грузится при правке platform/dialogs/states.py.
paths:
  - "src/bot/platform/dialogs/states.py"
---

# Жизненный цикл State

`platform/dialogs/states.py` — **единый каталог всех `StatesGroup`** (разрыв циклов импорта между
диалогами). У пользователя в открытом диалоге `state` уже записан в Redis по имени; удалил/
переименовал State → после деплоя его апдейт не резолвится → `UnknownState`/`UnknownIntent`.
Безопасная процедура миграции — skill `state-migration`.

## Инварианты

- **Все `StatesGroup` — только тут.** Не объявлять `State()`/`StatesGroup` в фичах; фича делает
  локальный re-export (`ProfileSG = states.Profile`).
- **Не удалять и не переименовывать живой `State`** (и не менять порядок так, что меняется
  идентичность). Вывод из обихода — через deprecation: перестать на него навигировать, оставить в
  каталоге, пока живут сессии/до планового окна.
- **Добавлять — аддитивно.** Новый `State` в конец группы, новая `StatesGroup` — отдельным классом.
- Имя группы = имя фичи (PascalCase), state — UPPER_SNAKE. Один диалог ⇄ одна группа.
- **Error-handlers — сеть под ломающиеся переходы**, не оправдание удалять State.
  `UnknownIntent`/`UnknownState`/`OutdatedIntent` → reset + UX (`platform/dialogs/errors.py:
  AppErrorUX`, отдаётся в `ErrorUX`). Регистрацию делает kit; шаблон даёт тексты/поведение.

## Чек

- Любая правка этого файла — сверься со skill `state-migration` (deprecation вместо удаления,
  версионирование при breaking, smoke).
- Smoke `emit_startup` (диалоги биндятся, переходы валидны) должен оставаться зелёным; падение
  на старте — в skill `triage-failure`.
- Удалить deprecated State можно, только когда ни одна живая сессия на него не сошлётся (TTL
  storage истёк / плановое окно) — это отдельный аддитивный шаг, не вместе с заменой.
