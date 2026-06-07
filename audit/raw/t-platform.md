# Аудит области t-platform — `platform/` шаблона (нерв заказчика: backend-абстракция)

## Что смотрел

Файлы области:
- `src/bot/platform/backend/{client,provider,errors}.py` + `__init__.py`
- `src/bot/platform/dialogs/{common,errors,states}.py`
- `src/bot/platform/identity/{identity,provider}.py`
- `src/bot/platform/webapp/init_data.py`
- `src/bot/platform/links.py`
- `src/bot/shared/{decision,errors}.py` (фактически лежат в `src/bot/shared/`, не под `platform/`)

Контекст (для проверки утверждений docstring'ов и инвариантов):
- kit: `pylibinfra/src/pylibinfra/httpclient/{client,config,module,breaker}.py` (что райзит `Client.request`, как устроены `base_url`/breaker, `HttpClientProvider`)
- kit: `pylibinfra/src/pylibinfra/tgbotkit/webapp/init_data.py` (`validate_init_data` — реальный HMAC-алгоритм)
- потребители: `features/{profile,payments}/gateway.py` + `provider.py`, `app.py`, `config.py`
- тесты: `tests/backend/test_backend_client.py`, `tests/unit/test_webapp.py`, `tests/_fakes/harness.py`
- инварианты: `importlinter.toml`, rules `tgbotkit-boundary`/`state-lifecycle`/`storage-serialization`

Прогнал `uv run pytest tests/backend tests/unit/test_webapp.py` — 7 passed.

## Сильные стороны

- **`platform/backend` — корректная anti-corruption граница, не дублирует инфру.** Транспорт-механика
  (retry/breaker/X-Request-ID/OTel-span) живёт в `httpclient.Client`; `BackendClient` — тонкий фасад,
  добавляет ровно две вещи: маппинг HTTP-статусов в доменно-нейтральные транспорт-ошибки и
  `Idempotency-Key`-хедер (`client.py:38-57`). Это by design тонкого шаблона, не утечка инфры.
- **Грамотный разбор того, что райзит kit.** Docstring `client.py:1-7` точно описывает поведение
  `httpclient`: 5xx-после-ретраев приходит как `httpx.HTTPStatusError`, 4xx возвращается как `Response`
  без исключения. Сверено с `httpclient/client.py:137-147` — верно. Поэтому 4xx разбирается в `_decode`,
  а `BreakerOpenError`/`HTTPStatusError`/`TransportError` ловятся в `_request` (`client.py:51-56`).
- **Чистое ядро `shared/` соблюдает инварианты.** `Decision` (`shared/decision.py`) и `FeatureError`
  (`shared/errors.py`) — PURE, frozen-dataclass / голое исключение, без I/O. Дают единый язык
  policy/usecase всех фич, легко юнит-тестируются. `BackendError`-иерархия (`backend/errors.py`) PURE.
- **HMAC-валидация WebApp initData — корректна и не переизобретена.** Алгоритм (secret =
  HMAC(`WebAppData`, token); hash = HMAC(secret, data_check_string); `compare_digest` constant-time +
  свежесть `auth_date`) реализован в kit (`tgbotkit/webapp/init_data.py:20-39`) — это правильный
  алгоритм Telegram. Шаблон (`platform/webapp/init_data.py`) НЕ дублирует крипту, только парсит уже
  проверенное поле `user` и валидирует `id` (`isinstance(uid, int)`). Тест `test_webapp.py:41` ловит
  подделку. Безопасность здесь в порядке.
- **`identity` корректно изолирует «нет from_user».** Синтетический нулевой юзер вместо падения
  (`identity/provider.py:30-32`) — апдейты без `from_user` (часть service-сообщений) не роняют резолв.
- **`states.py` как единый каталог `StatesGroup`** — верное решение против циклов импорта между
  диалогами и точка приложения rule `state-lifecycle` (deprecation вместо удаления). Аккуратно, по
  конвенции (имя группы = фича PascalCase, state UPPER_SNAKE).
- **`common.py` — фабрики виджетов, не shared-инстансы** (`common.py:1-2`): у каждого окна свой объект
  кнопки. Это снимает реальную грабли aiogram_dialog (один и тот же `id` виджета в разных окнах).

## Находки

### HIGH — «один бэкенд» зашит в тип, второй типизированный клиент к другому API не вставить без боли

**CAT=flexibility, CONF=high, KEY=yes**

Это прямой ответ на тревогу заказчика, и она обоснована. Цепочка завязана на разрешение dishka **по
типу**, и тип ровно один на каждом звене:

- `HttpClientProvider` (`httpclient/module.py:13-24`) provide'ит единственный `Client`, APP-scope,
  с единственным `base_url` из env `HTTPCLIENT_BASE_URL` (`httpclient/config.py:15`).
- `BackendProvider` (`backend/provider.py:12-17`) provide'ит единственный `BackendClient` поверх этого
  `Client`, тоже по типу.
- Все gateway фич просят `BackendClient` по типу (`profile/gateway.py:17`, `payments/gateway.py:17`,
  `profile/provider.py:24`, `payments/provider.py:18`).

dishka резолвит зависимости по типу-ключу. Чтобы получить **второй** типизированный клиент к **другому**
API (другой `base_url`, свой breaker/таймаут), есть только обходы, ни один из которых шаблон не
показывает и не документирует:
1. Завести `BackendClientB` как отдельный класс-обёртку + второй `Client` — но `HttpClientProvider`
   provide'ит `Client` по типу `Client`, второй такой же провайдер даст коллизию ключа; нужен ещё и
   второй httpx-клиент с другим `base_url`, которого механика kit'а из коробки не даёт.
2. dishka `component` (изоляция графа) — нигде в шаблоне не используется (`grep component` по `src/bot`
   пусто), не упомянут ни в одном rule/skill, тест-харнес (`tests/_fakes/harness.py`) тоже
   моно-`BackendClient`.

Симптом негибкости подтверждается и документацией расширения: `scaffold/references/backend-port.md`
описывает добавление эндпоинтов **только** к одному `platform/backend.BackendClient` — кейса «второй
API» в гайдах нет вообще.

Вердикт по сути вопроса: для **одного** бэкенда это удобный и правильный фасад. Но это **жёсткое
предположение «один бэкенд»**, а не просто convenience: ни код, ни DI-механика kit'а, ни гайды не
дают чистого пути к нескольким типизированным клиентам. Заказчику с несколькими API придётся либо
тащить разные `base_url` через `path` в каждом вызове (ломает идею «клиент = один сервис», теряет
per-host breaker), либо вводить второй слой провайдеров/обёрток вручную — это и есть «потребуется
менять шаблон/kit».

**fix:** дать в шаблоне явный паттерн именованных бэкендов — напр. `BackendClient.__init__` принимает
имя/`base_url`, провайдер-фабрика `named_backend("payments_api")`, и/или задействовать dishka
`component` для изоляции графов на каждый API. Сопутствующе — kit `HttpClientProvider` должен уметь
отдавать несколько `Client` (по `component`/именованной конфигурации), иначе per-backend breaker/таймаут
не получить. Это PR в `tgbotkit/httpclient` + reference-паттерн в шаблоне. Документировать в backend-port.

### MEDIUM — общий circuit breaker на все API (усугубляет мульти-бэкенд)

**CAT=correctness, CONF=high, KEY=yes**

`Client` держит **один** breaker с фиксированным `BREAKER_NAME = "httpclient"`
(`httpclient/breaker.py:12`, `client.py:65,117`), host-agnostic. Пока бэкенд один — норм. Но как только
появится второй API через тот же `Client` (а сейчас архитектура толкает именно к этому — все вызовы идут
через единственный `BackendClient`/`Client`), деградация **одного** внешнего сервиса откроет breaker и
для **всех** остальных: разные `path` к разным хостам считаются в один счётчик отказов. Это скрытый
side-effect моно-клиента, который заказчик на не-питон-уровне не увидит, пока в проде один тормозящий
API не положит обращения ко всем.

**fix:** breaker per-host/per-backend (ключ брейкера = host или имя бэкенда) — часть того же PR в
`httpclient`, что и мульти-клиент. Связан с HIGH-находкой: один клиент = один breaker.

### MEDIUM — `BackendConflict` (409) производится, но ни один gateway его не ловит → 409 всплывает как паника

**CAT=errors, CONF=high, KEY=no**

`client.py:67-68` корректно мапит 409 → `BackendConflict`, и тест `test_backend_client.py:40` это
проверяет. Но **ни одна фича не ловит `BackendConflict`** (`grep BackendConflict` по `features/` пусто):
- `payments/gateway.py:29-37` `fulfill` ловит только `BackendUnavailable`. Именно здесь 409 наиболее
  вероятен: docstring обещает идемпотентность по `Idempotency-Key=charge_id`, а 409 — стандартный ответ
  «идемпотентный повтор с другим телом» (так прямо сказано в `errors.py:19`).
- `profile/gateway.py` тоже ловит только `NotFound`/`Unavailable`.

Непойманный `BackendConflict` — это `BackendError`, не `FeatureError`, поэтому `views.error_text` его не
распознает как доменный → он всплывёт в recovery-middleware kit'а как настоящий сбой: panic-метрика +
нейтральное «Что-то пошло не так» (`platform/dialogs/errors.py:25-32`). То есть штатный для идемпотентной
мутации ответ трактуется как авария. Тип `BackendConflict` экспортирован (`backend/__init__.py:14`), но
по факту мёртв в потребителях — заявленный в errors.py сценарий «различаем конфликт» не доведён до фич.

**fix:** в reference-гейтвеях, делающих мутации (как минимум `payments.fulfill`), ловить
`BackendConflict` и переводить в осмысленный sentinel/успех (для идемпотентного повтора 409 часто = «уже
выполнено»); добавить упоминание 409 в `scaffold/references/backend-port.md` (там сейчас только
404/5xx). Иначе тип-обманка: есть, протестирован на границе, но не работает дальше неё.

### LOW — `_decode` парсит `resp.json()` без проверки content-type на 2xx

**CAT=correctness, CONF=medium, KEY=no**

`client.py:60-64`: на любом `is_success` с непустым телом вызывается `resp.json()`. Если бэкенд вернёт
200 с не-JSON телом (HTML от прокси/балансировщика, `text/plain`), `resp.json()` бросит
`json.JSONDecodeError` — не-`BackendError`. Этот класс **не** ловится в `_request` (там только
breaker/HTTPStatusError/TransportError) → всплывёт как паника, минуя доменную классификацию. Маловероятно
при дисциплинированном бэкенде, но это незакрытый путь в «нерве», который претендует быть единой точкой
маппинга транспорт→домен.

**fix:** обернуть `resp.json()` в try и мапить `JSONDecodeError`/`ValueError` в `BackendUnavailable`
(контрактный сбой бэкенда = «недоступен» для UX, как уже сделано для прочих 4xx в `client.py:69-70`).

### LOW — `webapp/init_data.py` — reference-утилита без потребителя в шаблоне

**CAT=dx, CONF=high, KEY=no**

`validate_webapp_user` нигде в `src/bot` не вызывается (`grep` по `src/bot` вне самого `platform/webapp`
пусто). Это заявлено осознанно (docstring `webapp/init_data.py:5-7` про «путь B / webhook-режим»), сам
код корректен и покрыт тестом. Фиксирую как факт, а не дефект: для потребителя шаблона это пример без
живого wiring — нет endpoint'а, который принимает initData. При de-template легко остаться «висящим»
кодом. Не блокер; скорее зона для явной пометки «reference, подключи при webhook+webapp».

### INFO — `identity` фолбэк `backend_user_id = tg_id` может молча смешать пространства идентификаторов

**CAT=correctness, CONF=low, KEY=no**

`identity/provider.py:42`: до линковки аккаунта `backend_user_id` = `str(tg_id)`. Дальше этот id уходит в
`GET /v1/users/{backend_user_id}` (`profile/gateway.py:22`). Если на бэкенде id пользователей — не
Telegram id (а они почти всегда разные пространства), до линковки запрос либо 404, либо (хуже) попадёт в
чужую запись с совпавшим числовым id. Это reference-поведение и зависит от контракта бэкенда заказчика,
поэтому CONF=low — но стоит знать как граблю онбординга. fix: до линковки не дёргать backend-by-id, либо
явный признак «не слинкован» вместо подмены tg_id.

## Ответ на вопросы заказчика в этой области

**3. Один `BackendClient` — это негибкость или норм by design?**
Гибридно, но ближе к **негибкости для заявленного сценария заказчика**. Для одного бэкенда фасад
правильный, тонкий и не дублирует инфру — это образцовая anti-corruption граница. Но «один бэкенд»
зашит **жёстко на уровне типа** через всю цепочку (`Client` → `BackendClient` → gateway, все
type-keyed в dishka, единственный `HTTPCLIENT_BASE_URL`, единственный breaker `httpclient`). Несколько
типизированных клиентов к разным API из коробки не собрать: нет именованных бэкендов, нет dishka
`component`, kit отдаёт ровно один `Client`, гайды (`backend-port.md`) знают только один backend.
Заказчику с несколькими API придётся менять и шаблон, и kit (per-component `Client`, per-host breaker).
Это не фатально — анти-коррупционный слой как раз туда и расширяется — но сегодня это предположение,
а не точка расширения, и это симптом негибкости конкретно в его кейсе.

**1. Получится ли строить нормальных ботов?** В этой области — да, для ботов поверх **одного**
бэкенда: границы чистые, ошибки классифицированы, identity/states/webapp сделаны грамотно, инварианты
(import-linter, PURE-ядро) держатся. Шероховатости (мёртвый `BackendConflict`, `resp.json()` без guard)
— чинятся точечно.

**2. Насколько гибкая система?** Внутри «один бэкенд + диалоги» — гибкая и расширяемая по конвенции
(scaffold backend-port, единый каталог states, shared-примитивы). Поперёк «несколько разных API» —
негибкая без правок kit'а. Для заказчика с несколькими бэкендами это главный архитектурный пробел области.
