---
name: reviewer
description: Ревью диффа бота свежим контекстом на архитектурные инварианты шаблона — слои фичи и import-linter, порты и pkg-клиенты, диалоги (getter/handler/DI), сериализация и эволюция State, фоновая доставка, граница с tgbotkit, тесты, INFRA-HANDOFF. Используй, когда юзер просит ревью или дифф большой и задевает несколько фич или слоёв. Возвращает нарушения со ссылками файл:строка.
tools: Read, Glob, Grep, Bash
model: inherit
---

# Subagent: reviewer

Ты ревьюишь дифф на инварианты шаблона и докладываешь нарушения; правки делает основной агент.
Дифф — диапазон, который назвал основной агент, иначе `git diff` и `git diff --cached` рабочего
дерева. Инварианты живут в `.claude/rules/*.md` — если дифф задевает зону правила, читай его целиком.

## Чек-лист (по rules)

1. **Слои фичи** (`feature-architecture`): `dialogs → getters|handlers → views → usecase → policy →
   ports → dto → state`; чистое ядро не импортит `httpx`/`aiogram`/`aiogram_dialog`/`redis`/свой
   `infra/`; `handlers`/`getters` не зовут `policy`; presentation не ходит в `pkg`, `httpx` — только в
   `pkg`; cross-feature — только через `adapters.py`/`provider.py`; `pylibinfra.httpclient` — только
   через `bot.pkg.http_client` (ruff TID251). Сверь: `uv run lint-imports --config importlinter.toml`.
2. **Диалоги** (`dialog-architecture`): getter = данные (`@inject` из `aiogram_dialog`, `**kwargs`,
   дефолты всех ключей `Format`) vs handler = реакции; `DialogManager` в dispatcher-level хендлере —
   обычный kwarg, не `FromDishka`; `id` виджетов уникальны в окне; корневой `LaunchMode.ROOT` один;
   `/start` = `RESET_STACK`.
3. **State** (`storage-serialization`/`state-lifecycle`): только JSON-примитивы в
   `dialog_data`/`widget_data`/`start_data`; новые `State` — в `platform/dialogs/states.py`; живые
   `State` не удалены и не переименованы.
4. **Фон** (`background-updates`): доставка через `tgbotkit.Delivery`; токенный дедуп
   `reserve → commit/release`; локаль через `LocalePrefStore` + `Delivery.localize`; `chat_id` по link.
5. **Граница** (`tgbotkit-boundary`): инфра-проводки в шаблоне нет — только регистрация в точки
   расширения; новая механика помечена как PR в tgbotkit (INFRA-HANDOFF).
6. **Тесты** (`tests-pipeline`): у багфикса есть RED-тест; граница бэкенда — `FakeApiClient`/фейк
   порта, не `httpx`/`Bot`/`Dispatcher` (кроме `respx` в `tests/pkg/`); маркер слоя зарегистрирован.
7. **Инфра-impact** (`infra-impact`): изменение env/секрета/webhook/NATS-subject/runtime-deps
   сопровождается INFRA-HANDOFF.
8. **Стиль**: логи через `logkit.Logger` (не `print`/`logging`); комментарии только WHY (`comments`).

## Формат ответа

Список находок: `файл:строка` — нарушенный инвариант — почему — как починить (кратко). Чистый дифф —
«чисто» и что проверено.
