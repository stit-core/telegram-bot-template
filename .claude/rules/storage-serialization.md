---
name: storage-serialization
description: Всё, что уезжает в FSM/dialog storage (Redis), обязано быть JSON-сериализуемым. Terse; «как и почему» — design/ARCHITECTURE.md §10. Грузится при правке state.py и *state*-файлов.
paths:
  - "**/state.py"
  - "**/*state*.py"
---

# Сериализация state

`dialog_data` / `widget_data` / `start_data` уезжают в Redis (`fsm:*` / `aigd:*`) **как JSON**.
Несериализуемое значение упадёт при сохранении контекста — на проде, на первом же таком апдейте.
Проводку storage держит kit; здесь — контракт того, что в него класть.

## Инварианты

- **Только JSON-примитивы** в `dialog_data`/`widget_data`/`start_data`: `str`/`int`/`float`/
  `bool`/`None`/`list`/`dict` из них. `datetime`/`Decimal`/`date`/`set`/`bytes`/`UUID`/ORM-объект/
  произвольный класс — **нельзя**.
- Кладёшь pydantic-модель — через **`model.model_dump(mode="json")`** (читаешь —
  `Model.model_validate(raw)`). `mode="json"` обязателен: он сам сводит `datetime`→ISO-строку,
  `Decimal`→str, `Enum`→value. Без него `model_dump()` оставит `datetime`-объект → падение.
- `state.py` фичи — PURE: pydantic-модели данных диалога + локальный re-export `StatesGroup` из
  `platform/dialogs/states`. Никакого I/O, никакого `aiogram_dialog`/`httpx`/`redis`.
- Храни **черновик/ввод**, не доменную сущность (она живёт за gateway, грузится getter'ом по месту).
  Модель в `dialog_data` — узкая (что нужно дорисовать окно), не «весь профиль с бэкенда».
- TTL на storage задаёт kit; контексты **не удаляются**, перезаписываются. Не закладывайся на
  «исчезнет само» — мёртвые ключи живут до TTL.

## Чек

- Сомнение «сериализуется ли» — не угадывай: flow-тест на `JsonMemoryStorage`
  (`pylibinfra.testkit.bottest`) ловит несериализуемое тем же json-кодеком, что прод-Redis
  (rule `tests-pipeline`).
- Добавил поле в модель `dialog_data` → проверь, что оно JSON-примитив или покрыто
  `model_dump(mode="json")`.
- Эволюция самой `StatesGroup` (не данных) — rule `state-lifecycle`.
