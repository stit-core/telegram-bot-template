# Аудит d-flex — гибкость и расширяемость (главная линза заказчика)

Синтез-линза: насколько система **открыта к расширению без правки kit'а** и насколько
дёшево заказчику пройти 6 типовых путей роста бота. Опирается на поблочные отчёты
(`t-platform.md`, `p-http.md`, `p-store.md`, `k-tgbot-runtime.md`, `k-tgbot-feat.md`,
`t-wiring.md`) + собственная проверка кода и DI-механики.

## Что смотрел

- Точки расширения kit'а: `tgbotkit/extension.py`, `tgbotkit/module.py` (`BotProvider` дефолты),
  `tgbotkit/__init__.py` (public surface), `tgbotkit/runner/__init__.py` (`build_runner`),
  `tgbotkit/i18n/{__init__,resolver}.py`, `tgbotkit/config.py`.
- Регистрация в шаблоне: `src/bot/{app,extensions,config}.py`.
- Образцы фич (полный/сокращённый гексагон): `features/profile/{provider,gateway,__init__}.py`,
  `features/{start,payments,lang}/__init__.py`, `features/lang/{usecase,policy}.py`.
- Платформа-glue: `platform/backend/{client,provider}.py`.
- Контрпример мульти-клиента: `pgkit/module.py` (`NewType` + отдельный DI-ключ для реплики).
- Процедуры роста: `scaffold/references/{feature,window,backend-port}.md`,
  `de-template/references/{prune,wiring}.md`.
- Проверки grep: `component=`/`NewType` по обоим репо; `BackendClient.__init__`-сигнатура.

## Сильные стороны (гибкость правильной формы)

- **Точки расширения — образцовая dishka-идиома, не глобальный реестр.** Все наполняются
  декларативно и переопределяемы по last-wins, без правки kit'а: `RouterBundle`,
  `CommandBundle`, `NotifierBundle`, `ErrorUX`, `OptionalLocaleResolver`, `OptionalStreamBus`,
  `Logger`, `OptionalTranslator` (`extension.py:21,37,51`, `module.py:46-72`). Шаблон
  **декларирует что подключить**, kit знает **как** — граница «framework ≠ продукт» держится.
- **Добавить фичу / диалог / окно — чистый, документированный путь без касания kit'а.** Полный
  гексагон по скелетам (`scaffold/references/feature.md`), регистрация ровно в трёх тонких
  файлах (`app.py` Provider, `extensions.py` bundle, опц. `config.py` i18n-ресурс). import-linter
  + mypy ловят нарушение слоёв на месте. Это сильнейшая сторона гибкости — вертикальный рост
  ботов масштабируется по конвенции.
- **Переключение runner polling↔webhook — нулевая правка кода.** `build_runner` выбирает класс по
  `cfg.mode` (`runner/__init__.py:32`), а `mode` — env `BOT_MODE` (`config.py:31`). Заказчик
  меняет одну переменную окружения; шаблон не трогает ничего (webhook-секрет/base_url — те же
  `BOT_WEBHOOK_*`). Это INFRA-HANDOFF (ingress/TLS/≥2 инстанса), не код-изменение.
- **Добавить runner-режим (третий вид рантайма) — механика есть.** Новый наследник `_BaseRunner`
  + ветка в `build_runner` — но это by design PR в kit, не правка шаблона (заявленная граница).
- **i18n открыт: свой `Translator`/`LocaleResolver` подменяется через DI.** Движок (fluent) за
  Protocol, выбор локали за Protocol; `ChainResolver` композируется в `extensions.py:53-55`
  без касания kit'а.
- **Контрпример из p-store подтверждает: в pylibinfra мульти-клиент через DI — by design есть.**
  `pgkit` держит реплику отдельным DI-ключом `ReplicaPool = NewType("ReplicaPool", object)`
  (`pgkit/module.py:16,42-58`) — два разных Postgres-пула живут в одном контейнере без коллизии
  по типу. То есть архитектурный примитив «N клиентов к разным бэкендам через DI» в библиотеке
  **существует и работает**. Это важно для оценки HTTP-кейса ниже: проблема не в потолке dishka,
  а в том, что в `httpclient`/`platform/backend` тот же паттерн **не применён**.

## Находки

### HIGH — несколько типизированных HTTP-клиентов к разным API: паттерн pgkit НЕ перенесён, путь не открыт (CAT=flexibility, CONF=high) [KEY]

Это прямой ответ на тревогу №3 заказчика, и через линзу гибкости она **обоснована**. Цепочка
HTTP-бэкенда разрешается dishka **по типу**, и тип ровно один на каждом звене:

- `HttpClientProvider.client` отдаёт **один** `Client`, APP-scope, по типу `Client`, с единственным
  `base_url` из env `HTTPCLIENT_BASE_URL` (`httpclient/module.py:16-24`, `config.py`).
- `BackendProvider.client` отдаёт **один** `BackendClient` по типу `BackendClient`
  (`platform/backend/provider.py:15-17`). Конструктор `BackendClient.__init__(http, log)` **не
  принимает** ни имени, ни `base_url` (`platform/backend/client.py:23-25`) — он намертво привязан
  к единственному `Client`.
- Все gateway фич просят `BackendClient` по типу (`profile/provider.py:24`, `payments/provider.py`).

Зарегистрировать второй провайдер с той же сигнатурой `-> Client` или `-> BackendClient` →
**коллизия ключа** (last-wins перезатрёт первый). Чистого пути к второму типизированному клиенту
шаблон не даёт и не документирует:

- **dishka `component`** (изоляция графа) — `grep component=` по **обоим** репо пусто. Не
  используется нигде, не упомянут в rule/skill, тест-харнес моно-`BackendClient`.
- **`NewType`-ключ** (паттерн `ReplicaPool` из pgkit) — `grep NewType` находит **ровно один** файл:
  `pgkit/module.py`. В `httpclient`/`tgbotkit`/`platform/backend` его нет. Тот же приём
  (`PaymentsApi = NewType(...)`, отдельный провайдер-фабрика) **технически применим** к HTTP —
  но не сделан.

**Почему его нет в platform/backend, хотя в pgkit есть.** pgkit с самого начала проектировался
под мастер+реплику (две физически разные БД) — мульти-клиент был требованием. `platform/backend`
+ `httpclient` спроектированы под **ровно один апстрim**: единственный env-namespace `HTTPCLIENT_*`
(не префиксуется под второй клиент, `p-http.md` подтверждает эмпирически), фасад `BackendClient`
без `base_url`-параметра, гайд `scaffold/references/backend-port.md` знает только один backend.
Это «не предусмотрено», а не «нельзя».

**Что придётся форкать/дублировать/копипастить заказчику с несколькими API:**
1. В шаблоне: завести `BackendClientB` (или параметризовать `BackendClient` именем/`base_url`)
   + второй провайдер с `NewType`-ключом или dishka-`component`. Это **новая локальная механика**
   в `platform/` — ровно та зона, которую CLAUDE.md велит выносить PR'ом в kit.
2. В kit (`httpclient`): чтобы каждый клиент имел свой `base_url`/таймаут/breaker-порог **из env**,
   нужен параметризуемый env-префикс (`new_config(prefix="PAYMENTS_API_")`) — сейчас два `Config()`
   прочитают один `HTTPCLIENT_BASE_URL`. Без этого `base_url` второго клиента приходится хардкодить
   в коде, теряя env-driven конфиг.

**Нюанс в пользу системы (из p-http).** Сам класс `httpclient.Client` **не** глобальный синглтон:
каждый `Client.__init__` создаёт собственную breaker-фабрику, N независимых клиентов с разными
`base_url`/порогами поднимаются на уровне Python тривиально и изолированы по состоянию (проверено
эмпирически в `p-http.md`). То есть потолок — не в механике клиента, а в **последней миле**:
DI-конвенция + env-неймспейсинг под несколько апстримов отсутствуют. Это чинимо аддитивным PR в
kit + reference-паттерном в шаблоне, но сегодня — реальный пробел гибкости в заявленном кейсе
заказчика.

**fix:** (а) в `httpclient` — параметризовать `Config`/`BreakerConfig` env-префиксом и принимать
`breaker_name` в `Client` (часть PR, общая с per-host breaker, см. ниже); (б) в шаблоне — дать
явный паттерн именованных бэкендов (`NewType`-ключ как `ReplicaPool`, либо `component`) и
документировать в `backend-port.md`. Без этого «несколько API» = форк/дублирование в `platform/`.

### MEDIUM — wiring-док обещает «именованные клиенты», которых в коде нет (CAT=dx, CONF=high) [KEY]

`de-template/references/wiring.md:20` прямо пишет: «несколько бэкендов = именованные
клиенты/провайдеры в `platform/backend/provider.py`». Но **механизма именованных клиентов в коде
нет**: `BackendProvider` отдаёт один `BackendClient` по типу, конструктор без имени/`base_url`,
`HttpClientProvider` отдаёт один `Client`, `NewType`/`component` не применены. Заказчик, дошедший
до де-темплейтизации с несколькими API, прочитает в гайде, что путь есть, и упрётся в его
отсутствие — придётся изобретать конвенцию самому (HIGH выше). Это разрыв «обещание дока ↔
реальность кода»: гайд описывает несуществующую точку расширения. forward-only-док должен описывать
**текущее** состояние, а не желаемое.

**fix:** либо реализовать именованные клиенты (тогда строка станет правдой), либо переписать
`wiring.md:20` честно: «несколько бэкендов из коробки не поддержаны — это PR в `httpclient`
(env-префикс + `breaker_name`) + `NewType`-ключ в `platform/backend`», со ссылкой на паттерн
`ReplicaPool`.

### MEDIUM — общий circuit breaker и слипшиеся breaker-метрики на все API (CAT=correctness/observability, CONF=high)

Усугубляет мульти-бэкенд (детали — `p-http.md`, `t-platform.md`). `Client` держит один breaker с
фиксированным `BREAKER_NAME="httpclient"` (`httpclient/breaker.py:12`). Внутри одного `Client`
он host-agnostic: если заказчик пойдёт по «лёгкому» обходу (один `BackendClient` на оба API через
разные `path`), деградация одного внешнего сервиса откроет breaker для всех. А если поднять два
`Client` правильно — их breaker-переходы и gauge `breaker_open` **неразличимы в метриках** (один
label `name="httpclient"`), хотя латентность развести можно (label `host`). Заказчик-не-питонист
этого не увидит, пока в проде один тормозящий API не «погасит» обращения ко всем или не сделает
breaker-метрику бесполезной для диагностики.

**fix:** `breaker_name` из `Config`/`base_url.host` в `Client` и в label — часть того же PR в
`httpclient`, что и env-префикс мульти-клиента.

### LOW — «выключить reference-фичу» работает, но ручной чек-лист из 8 пунктов хрупок (CAT=dx, CONF=medium)

Путь де-темплейтизации (`de-template/references/prune.md`) полный и грамотный, но удаление одной
фичи требует синхронно тронуть **8 мест**: пакет фичи, `StatesGroup` в `platform/dialogs/states.py`,
4 регистрации в `extensions.py`, Provider в `app.py`, i18n-каталоги + `_I18N_RESOURCES`,
cross-feature порты/адаптеры, platform-glue (`platform/links.py`), тесты. Недочистка п.3/6 →
красный import-linter (висящий импорт); п.2 → красный startup-smoke (осиротевший `State`).
Защита есть (`uv run pytest -k collision` + `make check` ловят недочистку), и это **сильно**
снижает риск — но это процедурная дисциплина, не структурная гарантия. Удаление **слабосвязанной**
фичи (`lang`) проще, чем `start` (корневой ROOT — переписывается, не удаляется) или фичи,
читаемой через cross-feature-порт. Не блокер: гейт ловит, гайд исчерпывающий. Фиксирую как «цена
тонкости»: вертикальная нарезка делает добавление дешёвым, а удаление — многоточечным.

### LOW — `CommandSpec.observer: str` стрингли-типизирован (CAT=types, CONF=medium)

Точка расширения `CommandBundle` принимает `observer: str` (`extension.py:32`); опечатка
(`"messsage"`) даёт `KeyError` на старте, не на этапе типов (`module.py:104-105`). Падает громко
на старте (startup-smoke поймает), поверхность мала (фиксированный набор aiogram-observer'ов),
поэтому LOW. `Literal[...]` строже, но это утечка aiogram-vocabulary в API — компромисс осознан.

## Ответ на вопросы заказчика (в этой области)

Прохожу 6 путей роста явно — это и есть «насколько гибко».

**(1) Добавить фичу** — ✅ **открыто без правки kit'а.** Новый `features/<name>/` по скелетам
гексагона + регистрация в `app.py`/`extensions.py`/`config.py`. import-linter/mypy держат слои.
Документировано (`scaffold/references/feature.md`), есть скелет тестов. Лучшая сторона гибкости.

**(2) Добавить диалог/окно** — ✅ **открыто без правки kit'а.** Новое окно = `State()` в
центральный каталог `platform/dialogs/states.py` + getter/handler + `Window` в существующий
`Dialog` + привязка перехода (`scaffold/references/window.md`). Новый диалог — `RouterBundle` в
`extensions.py`. Единственная грабля (дубль `state=`, `State()` по месту) ловится startup-smoke.

**(3) Несколько типизированных клиентов к разным API** — ⚠️ **НЕ открыто из коробки; форк
неизбежен.** dishka-провайдеры завязаны на разрешение по типу, и тип ровно один на каждом звене
(`Client`, `BackendClient`); scope APP. Различение по типу — единственный механизм, и он занят
одним клиентом. **Форк/дублирование в `platform/backend` обязателен** (второй обёрточный тип
или `NewType`-ключ), **PR в `httpclient` практически обязателен** для env-driven per-API
`base_url`/breaker. Контрпример pgkit (`ReplicaPool = NewType`) доказывает: тот же паттерн
**применим** к HTTP и в библиотеке уже отработан — но в `platform/backend`/`httpclient` его не
перенесли, потому что слой проектировался под один апстрим. Симптом негибкости **конкретно в
кейсе заказчика** — реальный, хотя и аддитивно чинимый (не архитектурный тупик).

**(4) Заменить runner polling↔webhook** — ✅ **нулевая правка кода.** Одна env-переменная
`BOT_MODE`; `build_runner` выбирает класс. Это INFRA-HANDOFF (ingress/инстансы), не код.
Третий режим рантайма — PR в kit (заявленная граница, механика `_BaseRunner` для этого есть).

**(5) Добавить язык** — ✅ **в основном открыто, фича `lang` reference.** Нужно: положить
`locales/<lang>/*.ftl` (fluent находит локали по каталогам — `_I18N_RESOURCES` это **имена
ресурсов**, не список языков, менять его не надо), добавить код в `SUPPORTED_LOCALES`
(`features/lang/policy.py:8`) и кнопку в диалог выбора языка. Kit (`Translator`/`Resolver`) не
трогается. Моноязычному боту фича `lang` целиком прунится. Цена — продуктовый контент, не инфра.

**(6) Выключить reference-фичу (de-template)** — ✅ **поддержано, но процедурно (8 точек).**
Полный чек-лист + гейт (`-k collision`, import-linter) ловят недочистку. Структурной
one-shot-кнопки нет; недоудаление красит сборку, а не молча ломает прод. Цена тонкой вертикальной
нарезки.

**Итог по линзе.** Система **гибкая правильной формы** на 5 из 6 путей: рост вширь (фичи) и
вглубь (диалоги/окна), смена рантайма, языки, выключение фич — всё через **точки расширения и
env, без правки kit'а**. Единственный путь, где гибкость ломается — **несколько разных HTTP-API**:
здесь `platform/backend`+`httpclient` жёстко single-tenant, форк/дублирование неизбежны, и нужен
аддитивный PR в kit. Это не предел архитектуры (dishka тянет мульти-ключ, pgkit это доказывает) —
это **непротянутый паттерн** в одном слое + док, обещающий несуществующую точку расширения.
Открытость к расширению без правки kit: **высокая везде, кроме мульти-бэкенд-HTTP**.
