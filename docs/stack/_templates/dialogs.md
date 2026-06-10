---
id: stack.dialogs
kind: dialogs
name: dialogs
status: draft
---

# Dialogs — карта флоу + error-handlers

⚠️ **Критичный артефакт.** Карта флоу — source-of-truth presentation; вход для `/scaffold` и
`/preview-flow`. Заполняется `/dialog-deep-dive`. Источник дизайна — интервью или **стратегия-репо**
(слой `telegram-bot-flow/<surface>/`, read-only); маппинг полей в код — `docs/reference/dialog-mapping.md`.

## StatesGroup-инвентарь
<Полный перечень `StatesGroup` (единый каталог `platform/dialogs/states.py`): группа → её `State` в
порядке окон. Имена групп/состояний уникальны (коллизия → `setup_dialogs` падает на старте).>

## Root & entry
<Корневой диалог (`LaunchMode.ROOT`) — главное меню; точка входа `/start` = `RESET_STACK`. Бот без
ROOT-диалога не имеет точки входа.>

## Error-UX
<Поведение `AppErrorUX` на устаревших кнопках (`UnknownIntent`/`UnknownState` после рестарта/TTL →
подсказка `/start`) и прочих ошибках. Регистрацию error-handlers делает kit; шаблон даёт тексты.>

## Flow: <feature>
<Per-feature карта (повторить блок на каждый сценарий): точка входа, таблица окон
(State · getter-ключи · реакции · переходы), состояние виджетов (JSON ✓), ошибки/edge, i18n-ключи.
Формат — `docs/reference/dialog-mapping.md`.>

## Generates
<Что de-template/scaffold родят:
- `platform/dialogs/states.py` (инвентарь StatesGroup)
- `platform/dialogs/errors.py` (`AppErrorUX`)
- регистрация `RouterBundle` в `app.py`
- скелеты `features/<name>/dialogs.py` (scaffold по `## Flow:`)>
