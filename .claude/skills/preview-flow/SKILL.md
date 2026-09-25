---
name: preview-flow
description: Построить граф переходов диалогов (render_transitions) и/или HTML-preview окон (render_preview) из реальных Dialog'ов бота как ревью-артефакт и диагностику навигации — недостижимые окна, тупики, лишние рёбра, расхождение кода с картой флоу. Требует aiogram_dialog[tools] и системный graphviz (dev-only). Используй, когда нужно увидеть флоу глазами до мержа, разобрать навигационный баг (из triage-failure) или сверить код с картой dialog-deep-dive (/preview-flow).
---

# Skill: preview-flow

Строит **граф переходов** (`render_transitions`) и/или **HTML-preview окон** (`render_preview`) из
реальных `Dialog`'ов проекта — как ревью-артефакт и диагностику навигации. На графе видно то, что в
коде рассыпано по `dialogs.py`: недостижимое окно, тупик без выхода, лишнее/неверное ребро, цикл без
выхода, рассинхрон с картой флоу (`dialog-deep-dive`).

⚠️ **Зависимость не в дефолтном наборе.** `aiogram_dialog.tools` тянет extra `[tools]` (`diagrams` —
обёртка над **graphviz**, `aiohttp`); в шаблоне их нет, рантайму они не нужны. Без них импорт
`render_transitions` падает `ModuleNotFoundError: No module named 'diagrams'`. Поэтому это
on-demand-инструмент, а не часть `make check`.

## Когда применять

- Ревью нового/изменённого флоу: «покажи граф, прежде чем мержить».
- Диагностика навигации (из `triage-failure`): кнопка ведёт не туда, окно недостижимо, тупик.
- Сверка кода с картой флоу (`dialog-deep-dive`): совпадает ли реализованное с задуманным.
- Препарат для обсуждения с продуктом: HTML-preview окон без живого бота.

## Когда не применять

- Проектирование флоу с нуля (ещё нет `Dialog`'ов) → `dialog-deep-dive` (рисует карту словами).
- Проверка коллизий StatesGroup на старте → startup-smoke (`pytest -k collision`), дешевле и без graphviz.
- Рантайм-баг логики (getter не отдаёт данные) → граф не покажет; → `triage-failure`.

## 1. Поставить инструменты (dev-only)

```bash
# системный graphviz (даёт бинарь `dot`):
#   Debian/Ubuntu: apt-get install -y graphviz
#   macOS:         brew install graphviz
# python-часть — разово в .venv (pyproject/uv.lock не трогает; следующий `uv sync` её снимет):
uv pip install "aiogram-dialog[tools]"
```

Проверь: `uv run python -c "from aiogram_dialog.tools import render_transitions, render_preview; print('ok')"`.
Падает на `diagrams` — не доставлен extra `[tools]`; падает на `dot not found` — нет системного graphviz.

Закрепить инструмент в dev-группе (`uv add --group dev "aiogram-dialog[tools]"`) — правка
`pyproject.toml`/`uv.lock`, это решение юзера; в рантайм-зависимости (`[project] dependencies`)
он не идёт.

## 2. Граф переходов (`render_transitions`)

`render_transitions(router, title=…, filename=…, format="png")` принимает `Router`/`Dispatcher` и
сам собирает из него все `Dialog`'ы (`collect_dialogs`); рёбра — по виджетам-переходам
(`Start`, `SwitchTo`/`Next`, `Back`, `Cancel`):

```python
# scripts/preview.py — dev-утилита, не коммитится
import asyncio

from aiogram import Router
from aiogram_dialog.tools import render_preview, render_transitions

from bot.features import booking, lang, payments, profile, start  # те же, что в RouterBundle

router = Router()
router.include_routers(start.dialog, profile.dialog, payments.dialog, lang.dialog, booking.dialog)
render_transitions(router, filename="flow")  # → flow.png
asyncio.run(render_preview(router, "preview.html"))  # → preview.html (§3)
```

```bash
uv run python scripts/preview.py
```

**Что читать на графе:**
- **недостижимое окно** — State без входящих рёбер (кроме точки входа) → кнопка-переход не привязана
  или ведёт мимо.
- **тупик** — State без исходящих рёбер (и не финальный) → нет `Back`/`Cancel`/`done`/`Next`.
- **лишнее/неверное ребро** — переход, которого по карте флоу (`dialog-deep-dive`) быть не должно.
- **межгрупповые `Start`-рёбра** — переходы в другую фичу; ровно один корневой узел (`LaunchMode.ROOT`).

Граф строится только по виджетам: переходы из кода handler'ов (`manager.switch_to`/`next`/`done` —
так устроены шаги визарда `booking` и сохранение в `profile`) на нём не видны. Окно, куда попадают
только из handler'а, выглядит недостижимым — сверь с `handlers.py`, прежде чем чинить; для рендера
такие рёбра подсказываются `Window(preview_add_transitions=[...])`.

## 3. HTML-preview окон (`render_preview`)

`await render_preview(router, "preview.html")` (корутина; тот же `router`, что для графа) рендерит все
окна в статический HTML — тексты и клавиатуры без запуска бота. Рендер идёт через фейковый
`DialogManager`, getter'ы не вызываются: данные окна берутся из **`preview_data`**
(`Window(..., preview_data={...})` — статический dict или async-функция); без него `Format` с ключами
getter'а не отрендерится. `I18NFormat` в preview показывает сам ключ — i18n там не настроен. Окно,
которое невозможно отрендерить без живого бэкенда, — сигнал добавить ему `preview_data` с
репрезентативными значениями (заодно документирует контракт getter'а).

## 4. Артефакт ревью

- `flow.png` — приложи к PR/обсуждению, отметь словами найденные аномалии (недостижимость/тупик/лишнее
  ребро).
- Сверь граф с картой флоу из `dialog-deep-dive` (`docs/stack/dialogs.md § Flow: <feature>`) —
  расхождение «как задумано vs как в коде» обсуди/почини. Первоисточник «как задумано», если есть
  стратегия-репо, — её слой `telegram-bot-flow/<surface>/` (dialog `windows`/`transitions`, окна
  `state`/виджеты): цепочка правды `стратегия → карта флоу → граф`.
- `flow.png`/`preview.html`/`scripts/preview.py` не коммить: это артефакты ревью, а `.gitignore` их
  не исключает — удали после ревью или держи вне индекса.

## 5. Назад в поток

- Нашёл недостижимое окно/тупик/лишнее ребро → почини `dialogs.py` (привяжи переход / добавь выход /
  убери ребро), затем `pytest -k collision` + flow-тест.
- Граф не сходится с задумкой → вернись в `dialog-deep-dive` уточнить карту, потом правь код.
- Граф чистый → артефакт в ревью, продолжай.

## Anti-patterns

- ❌ Добавить `diagrams`/`graphviz` в рантайм-зависимости (`[project] dependencies`) — это dev-only.
- ❌ Считать preview заменой тестам: граф показывает структуру переходов, не поведение
  getter/handler. Логику проверяют flow-тесты.
- ❌ Коммитить `flow.png`/`preview.html`/`scripts/preview.py` в репо.
- ❌ Гонять preview там, где хватает startup-smoke (`pytest -k collision`) — коллизии State он ловит
  без graphviz.
