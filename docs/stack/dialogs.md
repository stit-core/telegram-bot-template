---
id: stack.dialogs
kind: dialogs
name: dialogs
status: draft
---

# Dialogs — карта флоу (КРИТИЧНЫЙ)

> **КРИТИЧНЫЙ артефакт: без корректной карты диалогов прод падает/ломается на первом деплое.**
> Нет корневого `LaunchMode.ROOT` / `/start`=`RESET_STACK` → стек копится до 100 →
> `DialogStackOverflow`; нет error-handlers → устаревшие кнопки после рестарта/TTL дают
> `UnknownIntent`/`UnknownState` без UX-реакции; коллизия `State`/виджет-`id` ломает рендер.

Карта диалогов = source-of-truth UI (проектируется до кода, skill `dialog-deep-dive`). Механику
диалогов даёт `tgbotkit`+`aiogram_dialog`; здесь — **карта флоу и инварианты**.

## Dialog map
<Список диалогов сценариев: фича ↔ `StatesGroup` ↔ `Dialog`. Для каждого — окна и переходы.
Пример:
| Диалог | StatesGroup | Окна | Корневой? |
|---|---|---|---|
| start | Start | MENU | да (`LaunchMode.ROOT`) |
| profile | Profile | VIEW → EDIT_NAME | нет (запускается из меню) |
| payments | Payments | OFFER | нет |
| lang | Lang | CHOOSE | нет |
Маппинг флоу → файлы — docs/reference/dialog-mapping.md.>

## States catalog
<**Все `StatesGroup` — централизованно в `platform/dialogs/states.py`** (разрыв циклов импорта
между диалогами). Эволюция — только через deprecation: не удалять/переименовывать живые `State`
(сломает кнопки у пользователей в открытых диалогах → `UnknownState`). skill `state-migration`.>

## Launch & navigation rules
<- Корневой диалог — `LaunchMode.ROOT`.
- `/start` — всегда `StartMode.RESET_STACK` (иначе `DialogStackOverflow` при лимите стека 100).
- виджет-`id` — ASCII, короткие, уникальные; один media/markup/input на окно.
- getter — `**kwargs` + дефолты всех ключей `Format`.>

## Error UX
<Error-handlers (`Unknown*`→reset) регистрирует kit; **тексты/поведение — в шаблоне через `ErrorUX`**
(`platform/dialogs/errors.py: AppErrorUX`). Опиши UX устаревшей кнопки (подсказать `/start`),
нейтральное сообщение на прочих ошибках. На callback — только `answer` (сообщение могло быть удалено).>

## Generates
<Что de-template родит:
- `platform/dialogs/states.py` (единый каталог StatesGroup)
- `platform/dialogs/errors.py` (AppErrorUX) + регистрация `ErrorUX` в `extensions.py`
- состав `RouterBundle` (список диалогов) в `extensions.py`
- скелеты `features/<f>/dialogs.py` под scaffold>
