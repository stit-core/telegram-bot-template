# Аудит d-types — типобезопасность как сквозной синтез (шаблон + pylibinfra)

## Что смотрел

Линза — **реальная** строгость mypy strict, а не декларация. Проверял эмпирически, не на веру:

- Прогон `uv run mypy src` в обоих репо (ground-truth + версии mypy).
- mypy-конфиги обоих `pyproject.toml` (`[tool.mypy]`, overrides, наличие/отсутствие `[tool.pydantic-mypy]`).
- Счётчики подавлений: `# type: ignore`, `cast(`, `Any`, `# noqa` по `src` обоих репо + категоризация каждого `Any`.
- `py.typed` у ключевых зависимостей (aiogram, aiogram_dialog, dishka, redis, pydantic) — реально ли
  mypy видит их типы или молча `Any`-ит границу.
- **Структурная типизация Protocol-портов** — нашёл порт (`PaymentsGateway`, `LocaleStore`) + адаптер
  + провайдер и эмпирически проверил, ловит ли mypy расхождение (неверная сигнатура / отсутствующий
  метод / неверный тип через границу kit↔шаблон). 5 probe-файлов с намеренными ошибками.
- Граница **dishka**: раскрытие `FromDishka[X]`, видимость тела `@inject`-функций, проверка типа
  внутри `@provide`.
- Граница **aiogram**: `bot.send_invoice(**dict[str, Any])` — теряется ли проверка kwargs.
- **pydantic.mypy-плагин**: что он реально проверяет на конструировании моделей (типы значений,
  лишние аргументы) — изолированный probe + полный прогон `src` под усиленными опциями.
- **Разъезд мажоров mypy** (шаблон 1.20.2 vs kit 2.1.0): один и тот же probe публичного API
  tgbotkit под обоими мажорами — маскирует ли разъезд ошибки на общем API.
- `Any` в публичной поверхности `tgbotkit` (точки расширения `CommandSpec`/`RouterBundle`/`Notifier`).

Прогоны (оба EXIT 0):
- Шаблон: `Success: no issues found in 71 source files`, mypy **1.20.2**.
- pylibinfra: `Success: no issues found in 176 source files`, mypy **2.1.0**.

---

## Сильные стороны

### mypy strict — не декоративный, конфиг идентичен и честный

Оба `[tool.mypy]` совпадают (`telegram-bot-template/pyproject.toml:87-100` ≡
`pylibinfra/pyproject.toml:144-158`): `strict = true` + явное дублирование
`warn_unused_configs`/`warn_redundant_casts`/`warn_unused_ignores`/`disallow_untyped_defs`/
`no_implicit_optional` + `plugins = ["pydantic.mypy"]`. `warn_unused_ignores = true` доказуемо
эффективен: в ките 13 `type: ignore` и гейт зелёный → **мёртвых ignore нет** (иначе упал бы). Единственный
relax — `ignore_missing_imports` на `fluent.*` (нет `py.typed`, стабов на PyPI нет) — узкий и обоснованный.

### Границы с aiogram/dishka/redis/pydantic реально типизированы, не `Any`-заглушены

Все ключевые зависимости поставляют `py.typed`: `aiogram`, `aiogram_dialog`, `dishka`, `redis`,
`pydantic` — все **YES**. Это значит mypy строго проверяет вызовы в эти либы, а не молча подставляет
`Any`. Доказано probe'ом: `bot.send_invoice(chat_id=1, ..., no_such_param=123)` →
`error: Unexpected keyword argument "no_such_param" for "send_invoice" of "Bot" [call-arg]`. Граница с
самой aiogram держится.

### Protocol-порты — структурная типизация реально работает (а не «для красоты»)

Главная проверка линзы. `PaymentsGateway` (Protocol, `features/payments/ports.py:14-17`) реализуется
`HttpPaymentsGateway` (`gateway.py:16`) и связывается в `provider.py:18` с **аннотацией возврата =
Protocol**. Эмпирически (probe с намеренными расхождениями):

- Адаптер с `fulfill(...) -> str` вместо `-> None` и `get_offer(offer_id: int)` вместо `str` →
  `error: Incompatible return value type ... Following member(s) ... have conflicts` с точным
  diff'ом Expected/Got. **Поймано.**
- Адаптер без метода `fulfill` → `"MissingMethod" is missing following "PaymentsGateway" protocol
  member: fulfill`. **Поймано.**
- То же **внутри dishka `@provide`** (декоратор не стирает тип): `BadProvider.gateway() -> PaymentsGateway`
  возвращающий неполный класс / `return 42` → обе ошибки `[return-value]`. **Поймано.**

То есть DI-граница типобезопасна на стороне продьюсера: подсунуть в провайдер реализацию, не
удовлетворяющую порту, mypy не даст. Это лучший случай — Protocol+DIP здесь рабочий инвариант, а не
комментарий в docstring.

### Граница kit↔шаблон через Protocol тоже проверяется

`features/lang/ports.py:12` объявляет свой `LocaleStore` (Protocol) и связывает его с **kit-классом**
`tgbotkit.LocalePrefStore` (`features/lang/provider.py:18`). Кит про `LocaleStore` шаблона не знает —
проверка целиком на стороне шаблона, и она работает: probe с обёрткой `set(user_id: str, ...)` вместо
`int` → `Incompatible return value type (got "BadStore", expected "LocaleStore")` с diff'ом сигнатур.
Значит, если будущая ревизия kit поменяет сигнатуру `LocalePrefStore.set`, mypy шаблона это поймает на
точке связывания — граница не «слепая».

### `FromDishka[X]` не дырявит тип — тело `@inject` проверяется

`FromDishka = Union[T, T]` под `TYPE_CHECKING` (dishka `entities/depends_marker.py:11`) — трюк,
схлопывающийся в `X` для type-checker'а. Probe доказал: внутри `@inject async def getter(uc:
FromDishka[PaymentsUsecase], ...)` опечатка `uc.nonexistent_method()` → `has no attribute`, а
`order.no_such_field` (нет поля DTO) → `[attr-defined]`. **Обе пойманы.** При этом вызов
`good_getter()` снаружи без аргумента `uc` проходит чисто — `@inject` корректно убирает
инжектируемые параметры из публичной сигнатуры. Бизнес-логика внутри хендлеров/getter'ов под полной
проверкой, инъекция типы не теряет.

### `Any` в шаблоне — 20 штук, ВСЕ на transport/JSON-границах, ноль в бизнес-логике

Категоризация всех 20 аннотаций `Any` (grep `src --include=*.py`, минус import): **20 из 20** —
`dict[str, Any]` (JSON-тела backend, `platform/backend/client.py`), `**kwargs: Any` (getter'ы
aiogram_dialog), `payload: Any` (NATS-событие, `notifications/deliver.py:24`), `user: Any`
(`identity/provider.py:29`). Подозрительных `Any` в `usecase`/`policy`/`dto`/`views` — **0**. И обе
ключевые `Any`-границы **навязаны типами публичного API**, а не выдуманы шаблоном:
`AiogramMiddlewareData = NewType(..., dict[str, Any])` (dishka) и `DeliverHandler = Callable[[Any,
Delivery], ...]` (`tgbotkit/notifications/router.py:18`). Шаблон защищается рантайм-guard'ами
(`isinstance(payload, dict)` в `deliver.py:25`, `int(user.id)` в `identity/provider.py:33`). Это
дисциплинированная работа с `Any`, а не дыры. 0 `type: ignore` / 0 `cast` / 0 `noqa` в шаблоне.

### pylibinfra — 13 ignore / 1 cast / 10 noqa, все живые и узкие

Все 13 `type: ignore` узко-кодированы по причине: `[import-untyped]` на `asyncpg`/`testcontainers.*`/
`yoyo` + точечные `[no-untyped-call]`/`[arg-type]`/`[no-any-return]` (`pgkit`/`httpkit`). Единственный
`cast` — `cast("datetime | None", await self._db.fetchval(...))` (`bruteforcekit/pgstore/store.py:43`),
оправдан (asyncpg `fetchval` отдаёт `Any`). `warn_unused_ignores=true` + зелёный гейт ⇒ мёртвых нет.

---

## Находки

### [SEV=medium | CAT=types | CONF=high | KEY=yes] pydantic.mypy подключён, но НЕ проверяет типы значений полей и лишние аргументы при конструировании моделей

`plugins = ["pydantic.mypy"]` стоит, но **нет секции `[tool.pydantic-mypy]`** ни в одном репо
(`grep init_typed/init_forbid_extra` → пусто в обоих `pyproject.toml`). По умолчанию плагин синтезирует
`__init__` модели с нетипизированными `**data: Any` и не форсит запрет лишних полей. Эмпирическое
доказательство (изолированный probe, **оба мажора mypy, оба EXIT 0 — без ошибок**):

```python
class M(BaseModel):
    n: int
    s: str
M(n="not-int", s="ok")   # int <- str: НЕ зажглось
M(n=1, s=2)              # str <- int: НЕ зажглось
M(n=1, s="ok", extra=9)  # неизвестный аргумент: НЕ зажглось
```

То же на реальных моделях: `OnboardingStatus(completed="yes")` (bool←str, `features/start/state.py:18`)
и `Order(... amount="x")` (int←str, `features/payments/dto.py:14`) проходят mypy **чисто**. Плагин
ловит только **пропущенные обязательные поля** (`Order(order_id="o")` → 3×`[call-arg]`).

Почему это важно именно здесь: модели конструируются **вручную из `dict[str, Any]`** на горячих
транспорт-границах — `gateway._to_order`/`_to_view` мапят сырой JSON бэкенда в DTO
(`payments/gateway.py:40-47`, `profile/gateway.py`), а `config.py:34-90` руками собирает все `*Config`.
Опечатка в имени поля DTO или подача `str` туда, где модель ждёт `int`, **не будет поймана mypy** —
вылезет рантайм-`ValidationError` в проде вместо ошибки на гейте. Для платформы, которая продаёт mypy
strict как барьер качества, это ощутимая дыра именно на самом частом виде ошибок (маппинг JSON→модель).

**Доказанный fix** (дешёвый и безопасный): добавить в оба `pyproject.toml`
```toml
[tool.pydantic-mypy]
init_typed = true
init_forbid_extra = true
```
Под этими опциями тот же probe даёт `[arg-type]` на оба неверных типа + `[call-arg]` на лишний
аргумент. И — проверено — **полный прогон `src` обоих репо остаётся зелёным** (`71 source files` /
`176 source files`, EXIT 0): текущий код уже корректен, опции лишь форсят это для будущих правок. Цена
нулевая, выгода — закрытие самой вероятной категории type-ошибок шаблона.

### [SEV=low | CAT=build | CONF=high | KEY=yes] Разъезд мажоров mypy (1.20.2 шаблон vs 2.1.0 kit) на основном API tgbotkit ошибки НЕ маскирует — но риск тонких strict-дефолтов остаётся

Уточнение к находке `_toolchain` (там `SEV=low`, без эмпирики). Я прогнал **один и тот же** probe с 6
намеренными ошибками вызова публичного API tgbotkit (`build_invoice` с `amount=str` / без обязательного
`payload` / лишний позиционный; `validate_init_data` с `max_age=str` / неверный return) под **обоими**
мажорами:

- mypy 1.20.2 (template venv): **8 errors**.
- mypy 2.1.0 (pylibinfra venv): **8 errors, вывод байт-в-байт идентичен**.

Вывод: для **сигнатурного** контракта общего API (типы аргументов, обязательность, return) разъезд
мажоров на практике **ничего не маскирует** — обе версии видят одно и то же. Риск сужается до тонких
ужесточений strict-дефолтов между 1.x и 2.x (mypy 2.0 менял дефолты), которые могут разойтись на
edge-конструкциях, не на основном API. То есть `_toolchain`-находка верна как гигиена, но её
практический вес ниже заявленного: общий API tgbotkit под обоими мажорами проверяется одинаково.
Доказательство: `pyproject.toml:21` (`mypy>=1.18,<2`) vs `pylibinfra/pyproject.toml:90` (`mypy>=2.1,<3`).
**Fix:** согласовать диапазон (поднять шаблон на `>=2.1,<3`) — снимает теоретический риск, ничего не
ломает (probe выше показывает совместимость поведения).

### [SEV=low | CAT=types | CONF=high | KEY=no] `CommandSpec.handler: Callable[..., Any]` — сигнатура handler'а на точке расширения kit не типизируется

`tgbotkit/extension.py:33`: `handler: Callable[..., Any]`. Когда шаблон регистрирует команды
(`extensions.py:42`: `(start.cmd_spec, *payments.command_specs, lang.cmd_spec)`), mypy **не проверяет**,
что сигнатура handler'а (напр. `on_pre_checkout(query: PreCheckoutQuery, *, uc, bot)`) соответствует
тому, что kit реально вызовет от aiogram. Несовпадение arity/типов параметров команды вылезет в рантайме
при доставке апдейта, не на гейте. Это типичная для универсальных точек расширения слабость (aiogram-
handler'ы разнородны по сигнатуре, строго типизировать tuple разных хендлеров трудно) — отмечаю как
факт границы, не как дефект шаблона. Для сравнения, `RouterBundle = tuple[Router, ...]` и
`NotifierBundle = tuple[Notifier, ...]` (Protocol) типизированы строго — `Dialog`/`Notifier` структурно
проверяются. Дыра только в `CommandSpec.handler`. **Fix (если вообще):** в kit можно сузить через
`ParamSpec`/перегрузки под классы хендлеров (command/pre_checkout/successful_payment), но это PR в
tgbotkit и спорно по соотношению цена/выгода.

### [SEV=low | CAT=types | CONF=high | KEY=no] `build_invoice() -> dict[str, Any]` → `bot.send_invoice(**invoice)` отключает проверку kwargs invoice'а

`tgbotkit/payments/invoice.py:13-37` `build_invoice` возвращает `dict[str, Any]` (и принимает
`**extra: Any`), а `handlers.py:45` делает `bot.send_invoice(callback.message.chat.id, **invoice)`.
Probe: прямой неверный kwarg в `send_invoice` mypy ловит, но **`send_invoice(chat_id=1, **invoice)` где
`invoice: dict[str, Any]` — НЕ проверяется** (опечатка ключа внутри `build_invoice` или лишний `**extra`
до `send_invoice` не дойдёт до mypy). Это by-design transport-граница (build_invoice по смыслу собирает
kwargs для send_invoice с XTR-нормализацией), но типобезопасность вызова `send_invoice` в этой точке
теряется. Низкий риск (одна централизованная фабрика, покрыта тестом), фиксирую как свойство границы.
**Fix (опц.):** в kit вернуть из `build_invoice` `TypedDict`, совместимый с kwargs `send_invoice` —
тогда `**invoice` проверится. PR в tgbotkit.

### [SEV=info | CAT=types | CONF=high | KEY=no] `Order._to_order` берёт `raw["title"]` без приведения → `title` может оказаться не-`str` в рантайме

`payments/gateway.py:42-47`: `title=raw["title"]`, `description=raw.get("description", "")`,
`currency=raw.get("currency", "XTR")` — без `str(...)`, тогда как `order_id`/`amount` приведены
(`str(...)`/`int(...)`). `raw` — `dict[str, Any]`, mypy не возразит. Без `pydantic-mypy init_typed` (см.
medium-находку) даже на конструировании `Order` это не зажжётся; в рантайме pydantic 2 **по умолчанию НЕ
коэрсит** `int→str` в strict-полях, но коэрсит в lax — поведение зависит от значения, и при неожиданном
типе с бэкенда (`title: 123`) поведение неочевидно. Мелочь, но иллюстрирует общую цену `dict[str, Any]`-
границы: вся валидация типов ответов бэкенда переехала в рантайм pydantic, и на части полей даже она
ослаблена отсутствием явного приведения. **Fix:** либо `str(raw["title"])` для симметрии, либо (лучше)
парсить ответ бэкенда через pydantic-модель `model_validate(raw)` вместо ручного `_to_order` — тогда
типы и обязательность полей ответа проверяются один раз и строго.

### [SEV=info | CAT=types | CONF=medium | KEY=no] `dict[str, Any]` на всём `platform/backend/client.py` — типобезопасность ответов разных API отсутствует by design

Связка с нервом заказчика (несколько backend-клиентов, см. `t-platform`). Весь `BackendClient` —
`dict[str, Any]` in/out (`client.py:25,30,35,45,63`). Это сознательная JSON-граница, но в контексте
«несколько разных API» она значит: типобезопасность ответов **каждого** бэкенда держится исключительно
на ручном маппинге в gateway-адаптере фичи. Чем больше разных API — тем больше ручных `_to_*`-мапперов,
каждый из которых (без `init_typed`) сам по себе типонебезопасен на конструировании DTO. То есть цена
гибкости «один фасад на любой JSON» переносится на дисциплину ручной валидации, которую mypy сейчас
почти не страхует (см. medium + предыдущий info). Не дефект границы как таковой — but compounding с
pydantic-находкой: включение `init_typed` заметно усилило бы именно этот слой.

---

## Системные темы (синтез по линзе)

1. **Структурная типизация работает там, где её писали руками (Protocol-порты), и слабее там, где
   полагаются на плагин/`Any`-границы.** Protocol+DIP — рабочий, доказанный инвариант (адаптеры,
   провайдеры, kit↔шаблон-границы — всё ловится). А вот «бесплатная» типобезопасность от pydantic-плагина
   недонастроена (`init_typed` не включён), и весь транспорт-слой сидит на `dict[str, Any]`. Итог: типы
   **не врут**, но самая частая ошибка реального бота — «неверно смаппил JSON бэкенда в модель» — mypy'ем
   сейчас почти не ловится.

2. **`Any` дисциплинирован, дыр-через-`Any` нет.** 20 `Any` шаблона все на навязанных транспорт-границах
   (dishka `NewType`, kit `Callable[[Any],...]`), бизнес-ядро чистое. 13 ignore + 1 cast кита — узкие и
   живые. С точки зрения «не врут ли типы» — почти нигде; единственные места, где тип шире реальности —
   ровно границы JSON/NATS, и они by design.

3. **Разъезд мажоров mypy практически безвреден на общем API** (доказано идентичным выводом обоих
   мажоров), но согласовать диапазоны стоит — дёшево и снимает теоретический риск тонких strict-дефолтов.

---

## Ответ на вопросы заказчика в этой области

**1. Получится ли строить нормальных ботов?** Со стороны типов — да. mypy strict здесь настоящий, а не
галочка: границы с aiogram/dishka/redis типизированы (все либы с `py.typed`), Protocol-порты реально
ловят расхождения, инъекция типы не теряет, бизнес-ядро без единого `Any`/ignore/cast. Барьер качества
рабочий. Одна реальная недокрутка — pydantic-плагин не форсит проверку конструирования моделей
(`init_typed` выключен), из-за чего самый частый класс ошибок (маппинг JSON бэкенда в DTO) проскакивает
мимо mypy. Чинится двумя строками конфига без поломок (доказано).

**2. Насколько гибкая система (с точки зрения типов)?** Типы гибкости не мешают и не врут. Расширение по
конвенции (новый порт = новый Protocol, mypy проверит адаптер) типобезопасно. Точки расширения kit
(`RouterBundle`/`Notifier`/`ErrorUX`) типизированы через Protocol — строго; единственная нетипизированная
— `CommandSpec.handler: Callable[..., Any]` (универсальность ценой проверки сигнатуры).

**3. Про несколько backend-клиентов (нерв) — взгляд из типов.** Весь `BackendClient` на `dict[str, Any]`
(`client.py:25-63`), типобезопасности ответов разных API на этом слое **нет by design**. Для одного
бэкенда это норма (валидация в одном gateway). Для нескольких разных API цена растёт: каждый новый API =
ещё один ручной `_to_*`-маппер, типонебезопасный на конструировании DTO (пока не включён `init_typed`).
Сами по себе типы не блокируют мульти-бэкенд, но и не помогают: вся проверка корректности ответов
переехала в рантайм pydantic и местами (`_to_order`: `title` без `str()`) ослаблена. Это усиливает
архитектурный вывод `t-platform`: гибкость «один фасад на любой JSON» оплачивается ручной дисциплиной,
которую сейчас mypy почти не страхует — и которую `init_typed=true` страховал бы заметно лучше.

**Итог области:** типы в обоих репо в хорошем состоянии и **не врут** — strict настоящий, Protocol-порты
рабочие, `Any` дисциплинирован, дыр-обманок нет. Единственная содержательная находка — **pydantic-плагин
недонастроен** (`init_typed`/`init_forbid_extra` выключены), из-за чего конструирование моделей и маппинг
JSON→DTO типобезопасны лишь частично; fix доказан дешёвым и не ломающим. Разъезд мажоров mypy на общем
API безвреден (проверено). Остальное — info-границы by design.
