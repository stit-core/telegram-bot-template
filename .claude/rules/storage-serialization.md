---
name: storage-serialization
description: Всё, что уезжает в FSM/dialog storage (Redis), обязано быть JSON-сериализуемым. Terse; «как и почему» — docs/reference/architecture.md. Грузится при правке state.py и *state*-файлов.
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
- Храни **черновик/ввод**, не доменную сущность (она живёт за портом фичи — pkg-клиент/`infra/`,
  грузится getter'ом по месту).
  Модель в `dialog_data` — узкая (что нужно дорисовать окно), не «весь профиль с бэкенда».
- TTL на storage задаёт kit (`BOT_STATE_TTL`, дефолт `0` — без срока); контексты **не удаляются**,
  перезаписываются. Не закладывайся на «исчезнет само» — мёртвые ключи живут до TTL, а при `0` — всегда.

## Черновик wizard'а (многошаговый ввод)

Мастер из нескольких окон копит **черновик** в `dialog_data`, не доменную сущность. Образец —
`features/booking` (SERVICES → DETAILS → [ADDRESS] → CONFIRM).

- **Один узкий model на черновик** в `state.py` (PURE, pydantic): `BookingDraft` с
  JSON-примитивными полями. Лежит под одним ключом `dialog_data["draft"]`; пиши
  `draft.model_dump(mode="json")`, читай `BookingDraft.model_validate(...)` (мост — `from_data`/
  `to_data` на модели, без `aiogram`).
- **Managed-виджеты держат своё `widget_data` сами** (`Multiselect`/`TextInput`): на границе шага
  читай их через `manager.find("<id>").get_checked()`/`.get_value()` и **сворачивай в черновик** —
  не дублируй состояние виджета вручную.
- **Накопление, не отправка:** каждый шаг дописывает свой кусок в черновик; обращение к бэкенду
  (submit) — только на финальном окне. Промежуточные шаги — чистый `dialog_data`.
- **Идемпотентность финала:** генерируй `draft_id` (`uuid4().hex`) в `on_start` диалога, клади в
  `dialog_data`, передавай как `Idempotency-Key` submit — повтор «Подтвердить» не создаст дубль.
- **Ветвление шага — результат usecase** (`set_guests → GuestsStep(draft, address_required)`;
  внутри — `policy.needs_address`), handler только мапит его на `switch_to` (rule
  `dialog-architecture`); навигация назад — `SwitchTo` на явные `State` (не `Back`), чтобы не
  упереться в пропущенное окно.

## Чек

- Сомнение «сериализуется ли» — не угадывай: flow-тест на `JsonMemoryStorage`
  (`pylibinfra.testkit.bottest`) ловит несериализуемое тем же json-кодеком, что прод-Redis
  (rule `tests-pipeline`).
- Добавил поле в модель `dialog_data` → проверь, что оно JSON-примитив или покрыто
  `model_dump(mode="json")`.
- Эволюция самой `StatesGroup` (не данных) — rule `state-lifecycle`.
