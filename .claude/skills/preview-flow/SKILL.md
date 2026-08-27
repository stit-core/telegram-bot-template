---
name: preview-flow
description: Сгенерировать граф переходов диалогов (render_transitions) и/или HTML-preview окон (render_preview) как ревью-артефакт/диагностику — увидеть флоу глазами до/после кода, поймать недостижимые окна, тупики, лишние рёбра. Требует aiogram_dialog[tools] + graphviz (diagrams). Активируй когда говоришь "/preview-flow", "построй граф диалогов", "покажи флоу", "нарисуй переходы", "проверь достижимость окон", "preview окон", или когда triage-failure/dialog-deep-dive просит граф для разбора навигации.
---

# Skill: preview-flow

Строит **граф переходов** (`render_transitions`) и/или **HTML-preview окон** (`render_preview`) из реальных `Dialog`'ов проекта — как ревью-артефакт и диагностику навигации. Глазами на графе видно то, что в коде рассыпано по `dialogs.py`: недостижимое окно, тупик без выхода, лишнее/неверное ребро, цикл без выхода, рассинхрон с картой флоу (`dialog-deep-dive`).

⚠️ **Зависимость не в дефолтном наборе.** `aiogram_dialog.tools` тянет `diagrams` (Python-обёртка над **graphviz**); в шаблоне их нет (они dev-only, не нужны рантайму). Без них импорт `render_transitions` падает `ModuleNotFoundError: No module named 'diagrams'`. Поставить — отдельно (см. §1). Поэтому это on-demand-инструмент, а не CI-гейт по умолчанию.

## Когда применять

- Ревью нового/изменённого флоу: «покажи граф, прежде чем мержить».
- Диагностика навигации (из `triage-failure`): кнопка ведёт не туда, окно недостижимо, тупик.
- Сверка кода с картой флоу (`dialog-deep-dive`): совпадает ли реализованное с задуманным.
- Препарат для обсуждения с продуктом: HTML-preview окон без живого бота.

## Когда НЕ применять

- Проектирование флоу с нуля (ещё нет `Dialog`'ов) → `dialog-deep-dive` (рисует карту словами).
- Проверка коллизий StatesGroup на старте → это startup-smoke (`pytest -k collision`), дешевле и без graphviz.
- Рантайм-баг логики (getter не отдаёт данные) → граф не покажет; → `triage-failure`.

## 1. Поставить инструменты (разово, dev-only)

```bash
# системный graphviz (даёт бинарь `dot`):
#   Debian/Ubuntu: apt-get install -y graphviz
#   macOS:         brew install graphviz
# python-обёртки в dev-группу:
uv add --group dev "aiogram-dialog[tools]"      # или: uv pip install diagrams graphviz
```

Проверь: `uv run python -c "from aiogram_dialog.tools import render_transitions, render_preview; print('ok')"`. Падает на `diagrams` → не доставлен graphviz/diagrams. Падает на `dot not found` → нет системного graphviz.

> Не коммить эти зависимости в основной рантайм (`[project] dependencies`) — только dev-группа. Если решено сделать preview CI-гейтом, добавление в CI-окружение graphviz — изменение инфра-поверхности (`infra-handoff`: runtime-dep CI).

## 2. Граф переходов (`render_transitions`)

Собирает все `Dialog`'ы проекта (как `ExtensionProvider.routers` в `app.py` отдаёт в `RouterBundle`), строит directed-граф State→State по рёбрам виджетов (`SwitchTo`/`Next`/`Back`/`Start`/`Cancel`):

```python
# scripts/preview.py (dev-утилита, не коммит в рантайм)
from aiogram_dialog.tools import render_transitions
from bot.features import start, profile, payments, lang  # те же, что в RouterBundle

render_transitions(
    [start.dialog, profile.dialog, payments.dialog, lang.dialog],
    filename="flow",  # → flow.png (+ .dot)
)
```

```bash
uv run python scripts/preview.py && echo "→ flow.png"
```

**Что читать на графе:**
- **недостижимое окно** — State без входящих рёбер (кроме точки входа) → кнопка-переход не привязана или ведёт мимо.
- **тупик** — State без исходящих рёбер (и не финальный) → нет `Back`/`Cancel`/`done`/`Next`.
- **лишнее/неверное ребро** — переход, которого по карте флоу (`dialog-deep-dive`) быть не должно.
- **межгрупповые `Start`-рёбра** — переходы в другую фичу; ровно один корневой узел (`LaunchMode.ROOT`).

## 3. HTML-preview окон (`render_preview`)

Рендерит окна с фейковыми данными в статический HTML — увидеть тексты/клавиатуры без запуска бота. Окна с динамикой требуют **`preview_data`** (иначе getter не вызвать вне рантайма):

```python
import asyncio
from aiogram_dialog.tools import render_preview

# bot — фейковый/реальный Bot; registry — DialogRegistry со всеми Dialog'ами
asyncio.run(render_preview(bot, "preview.html"))
```

**Проверка `preview_data`:** окно с `getter=` и `Format("{x}")` в preview не дёргает реальный usecase — нужно, чтобы у окна был `preview_data` (статический dict/функция), иначе preview покажет пустоту/упадёт. Это сигнал: если окно невозможно отрендерить без живого бэкенда, добавь ему `preview_data` с репрезентативными значениями (заодно документирует контракт getter'а).

## 4. Артефакт ревью

- `flow.png` — приложи к PR/обсуждению, отметь словами найденные аномалии (недостижимость/тупик/лишнее ребро).
- сверь граф с картой флоу из `dialog-deep-dive` (`docs/stack/dialogs.md § Flow: <feature>`) — расхождение «как задумано vs как в коде» обсуди/почини. Первоисточник «как задумано», если есть стратегия-репо, — её слой `telegram-bot-flow/<surface>/` (dialog `windows`/`transitions`, окна `state`/виджеты): цепочка правды `стратегия → карта флоу → граф`.
- `flow.png`/`preview.html`/`scripts/preview.py` — **не коммить** (артефакты ревью; `.gitignore`/`.dockerignore` их и так исключают по расширению, проверь).

## 5. Назад в поток

- Нашёл недостижимое окно/тупик/лишнее ребро → почини `dialogs.py` (привяжи переход / добавь выход / убери ребро), затем `pytest -k collision` + flow-тест.
- Граф не сходится с задумкой → вернись в `dialog-deep-dive` уточнить карту, потом правь код.
- Граф чистый → артефакт в ревью, продолжай.

## Anti-patterns

- ❌ Добавить `diagrams`/`graphviz` в рантайм-зависимости (`[project] dependencies`) — это dev-only.
- ❌ Считать preview заменой тестам: граф показывает структуру переходов, не поведение getter/handler. Логику проверяют flow-тесты.
- ❌ Коммитить `flow.png`/`preview.html`/`scripts/preview.py` в репо.
- ❌ Гонять preview там, где хватает startup-smoke (`pytest -k collision`) — коллизии State он ловит без graphviz.
- ❌ Окно с динамикой без `preview_data` — preview покажет пустоту; добавь репрезентативные данные.
- ❌ Сделать preview обязательным CI-гейтом, не оформив graphviz в CI-окружении как infra-change.
