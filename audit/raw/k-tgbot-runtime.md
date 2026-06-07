# Аудит: tgbotkit — рантайм/проводка (id=k-tgbot-runtime)

## Что смотрел

Сердце инфры бота в `pylibinfra/tgbotkit`:

- `module.py` — `BotProvider` (dishka-first composition: Bot/Dispatcher/RedisStorage/runner + дефолты точек расширения), `probe()`, `new_config()`.
- `extension.py` — типизированные точки расширения (`RouterBundle`/`CommandSpec`/`CommandBundle`/`Notifier`/`NotifierBundle`).
- `storage.py` — `build_storage` (RedisStorage + key_builder), `build_isolation` (RedisEventIsolation).
- `config.py` — public-API `Config`/`I18nConfig` (env `BOT_*`).
- `runner/base.py` — `_BaseRunner` (общий lifecycle: `_bind`/`_start_notifications`/`_cleanup`/`run`), Protocol `BotRunner`.
- `runner/polling.py`, `runner/webhook.py`, `runner/__init__.py` — две реализации + `build_runner` (выбор по `cfg.mode`).

Сопутствующе (для оценки контракта/протечек): `middleware/*` (request_id/dedup/throttle/recovery/observability + `install_standard_middleware`), `errorux.py`, `metrics.py`, `notifications/{runner,delivery}.py`, `i18n/{__init__,middleware}.py`, `__init__.py` (public surface). Как шаблон вкладывается — `src/bot/{app,extensions,config}.py`.

Прогнал: `mypy src/pylibinfra/tgbotkit/` (чисто), `ruff check` (чисто), интроспекция установленного aiogram 3.28.2 (сигнатуры `RedisStorage.__init__`, `start_polling`, `setup_dishka`), grep по dead-config и протечкам aiogram в шаблон.

## Сильные стороны

- **Абстракция runner — чистая и правильная (`runner/base.py`).** Общий контракт `BotRunner` (Protocol, `async def run`), общий lifecycle в `_BaseRunner`: `_bind` (setup_dishka → build_isolation → setup_dialogs **строго последним**) → `_start_notifications` → `_serve` → `finally: _cleanup`. Polling/webhook отличаются только в `_serve` — это аккуратный template-method, никакого дублирования lifecycle. `base.py:56-61` корректно откладывает `setup_dishka`/`setup_dialogs` из фабрики в `run` (нужен готовый container) — это нетривиальная грабля aiogram_dialog, и она отработана.
- **Deferred-wiring обоснован и безопасен.** Проверил `setup_dishka` (dishka): он лишь вешает `ContainerMiddleware` на observers, **не** регистрирует `container.close()` в shutdown диспетчера. Значит единственный владелец APP-teardown — `_cleanup → container.close()` (`base.py:81`); двойного close нет. Порядок в `_cleanup` (notif.drain → isolation.close → container.close) корректен: container закрывает bot.session/redis/nats через yield-провайдеры последним.
- **`module.py:78-81` — bot как async-генератор-провайдер** с `await b.session.close()` после yield: сессия закроется на `container.close()`, ссылка на «lifecycle 06 §5» — порядок осознан.
- **Точки расширения — образцовая dishka-идиома (`extension.py`).** `RouterBundle`/`CommandBundle`/`NotifierBundle` как типы-агрегаты + last-wins override (`BotProvider` даёт `() ` / `None`-дефолты, шаблон override'ит `ExtensionProvider`'ом). Не декораторы-с-глобальным-реестром, не наследование. Шаблон **декларирует** что подключить (`extensions.py:36-60`), а не как — граница держится.
- **Optional-зависимости через type-wrapper (`module.py:31-35`)** (`OptionalStreamBus = StreamBus | None` и т.д.) — корректный обход того, что dishka не умеет optional по `X | None`; kit даёт `None`, consumer override'ит. Грамотно.
- **Storage изолирован правильно (`storage.py:14-18`).** `DefaultKeyBuilder(with_bot_id=True, with_destiny=True)` — разделяет мульти-бот и FSM-vs-dialog стораджи; `RedisEventIsolation` (а не `SimpleEventIsolation`) обязателен при ≥2 воркерах. Покрыто тестом `test_storage.py`.
- **Webhook-безопасность (`webhook.py:34-42`).** POST-роут под `shared_secret_guard` по `X-Telegram-Bot-Api-Secret-Token`, тот же secret уходит в `set_webhook(secret_token=...)`. `set_webhook`/`delete_webhook` обрамляют serve; `≥2 инстанса` безопасны через RedisEventIsolation. Аккуратно.
- **Graceful-shutdown по сигналам корректен в обоих режимах.** Polling: `start_polling` сам делает `emit_startup`/`emit_shutdown` и ловит SIGINT/SIGTERM (`handle_signals=True` aiogram-дефолт) — проверено интроспекцией. Webhook: руками `emit_startup` до serve, `emit_shutdown` в `finally`, `loop.add_signal_handler` под `contextlib.suppress(NotImplementedError)` (`webhook.py:53-64`) — корректная защита для не-главного потока/не-POSIX.
- **`allowed_updates` не хардкодится** (`polling.py:15`, `webhook.py:49`): `dp.resolve_used_update_types()` — Telegram шлёт только то, на что есть хендлеры. Правильно.
- **Нет протечки aiogram-механики в шаблон.** Шаблон импортирует `aiogram`/`aiogram_dialog` только в **фиче-диалогах/хендлерах** (`features/*/dialogs.py`, `platform/dialogs/*`) — это бизнес-UI на самом фреймворке диалогов, а НЕ инфра-проводка. `Dispatcher`/`Bot`/`RedisStorage`/middleware/`setup_dialogs`/`setup_dishka` в шаблоне отсутствуют. Граница `tgbotkit ↔ шаблон` держится.
- **Middleware-цепочка зрелая (`middleware/__init__.py:40-46`).** Порядок снаружи→внутрь: request_id → dedup → throttle → recovery → observability. Dedup атомарный `SET NX EX` (`dedup.py:34`), recovery — последний рубеж со swallow + panic-метрикой (`recovery.py`), observability на `dp.update` покрывает и фоновые dialog-события. Опциональные (dedup/throttle) навешиваются по конфигу.
- **Config — стабильный public-API** с явными `validation_alias` (`BOT_*`), хороший коммент про `locales_dir` vs `$PATH` (`config.py:19-20`). mypy strict + pydantic-плагин зелёные.

## Находки

### MEDIUM — `BOT_SHUTDOWN_DRAIN` / `shutdown_drain` — мёртвый конфиг (CAT=correctness, CONF=high) [KEY]

`config.py:46-47` объявляет `shutdown_drain: float = 10.0` с docstring «сек на drain in-flight апдейтов при остановке». Grep по всему репо (`pylibinfra` + шаблон) показывает: поле **нигде не читается** — ни один runner, ни `_cleanup`, ни notifications его не используют.

```
config.py:47:    shutdown_drain: float = Field(default=10.0, validation_alias="BOT_SHUTDOWN_DRAIN")
# единственное вхождение во всём репо
```

Последствие: оператор, выставивший `BOT_SHUTDOWN_DRAIN=30`, ожидает 30-секундный drain in-flight апдейтов при SIGTERM — этого не происходит. Фактический drain: polling полагается на внутренний graceful-stop aiogram (без управляемого таймаута отсюда), webhook — на httpkit `shutdown_timeout` (env `HTTP_*`, **другая** переменная). Конфиг-поверхность обещает контроль, которого нет. Либо протащить `shutdown_drain` в реальный drain (например в `webhook._serve`/`polling`), либо удалить поле и docstring (forward-only: не держать обещания, которых код не выполняет).

### MEDIUM — RedisStorage без `state_ttl`/`data_ttl` — FSM/dialog-стейт не истекает (CAT=state, CONF=high) [KEY]

`storage.py:14-18` строит `RedisStorage(client, key_builder=...)` **без** `state_ttl`/`data_ttl`. Интроспекция установленного aiogram 3.28.2 подтверждает, что оба параметра поддерживаются:

```
RedisStorage.__init__ params: ['self', 'redis', 'key_builder', 'state_ttl', 'data_ttl', 'json_loads', 'json_dumps']
```

Последствия:
1. **Безлимитный рост Redis.** Каждый когда-либо начавший диалог пользователь оставляет ключи стейта навсегда — на проде с заметным трафиком это монотонный рост памяти Redis (тот же общий инстанс, что и кэш/dedup/throttle), без авто-сборки.
2. **Стейл-стейт UX неполон.** `errorux.py:3` объясняет `UnknownIntent/UnknownState` через «устаревшие кнопки после рестарта/**TTL**», но TTL на сторадже нет — значит TTL-ветку устаревания **невозможно** воспроизвести; стейл-кнопки появляются только от рестарта/ручного reset. Docstring обещает механизм, которого нет.
3. **Нет env для настройки** — в `config.py` отсутствует `BOT_STATE_TTL`/`BOT_DATA_TTL`, оператор не может включить экспирацию без правки кита.

Для прод-бота session-TTL — стандартная практика. Рекомендация: добавить `state_ttl`/`data_ttl` (хотя бы опционально через `BOT_STATE_TTL`, default — например 30 дней) в `build_storage`+`Config`. Это аддитивно и back-compat.

### LOW — `NotificationRunner.drain()` ничего не дренирует (CAT=async, CONF=high)

`notifications/runner.py:33-34`: `drain()` только логирует «notifications draining» и возвращается. In-flight доставки (NATS→Telegram через `Delivery`/BgManager) не дожидаются — реальный teardown подписок отложен на `container.close()` (NatsProvider drain'ит соединение). Docstring это честно проговаривает («здесь только лог»), и `Delivery` swallow'ит ошибки (at-least-once, `delivery.py:40-44`), так что катастрофы нет. Но имя `drain()` вводит в заблуждение — это `noop log`, не drain. Либо реально дожидаться in-flight (например через unsubscribe + join), либо переименовать в `log_draining()`/убрать.

### LOW — нет health-endpoint в polling-режиме (CAT=observability, CONF=medium)

`module.py:136-143` экспортирует `probe()` (health через `bot.get_me()`), но в polling его никто не вызывает: HTTP-сервер с `/healthz` поднимает **только** `WebhookRunner` (`webhook.py:39`, `probes=(self._probe,)`). `PollingRunner._serve` не поднимает httpkit-Server вовсе. Значит для polling-деплоя нет HTTP liveness/readiness — k8s/оркестратор может опираться только на «процесс жив». Для бота это часто приемлемо (polling сам себя чинит реконнектами), но это асимметрия наблюдаемости между режимами, о которой стоит знать. `probe()` фактически — orphan-хелпер (grep: ноль consumers в шаблоне и polling-раннере).

### LOW — runner-lifecycle без прямых тестов (CAT=testing, CONF=high)

`tests/tgbotkit/` есть, но `test_module.py` покрывает только сборку Dispatcher (`test_container_builds_dispatcher_with_chain_and_error_handlers`) и **выбор класса** runner'а (`test_build_runner_selects_mode` — с `bot=None`, `.run()` не зовётся). Нет `test_runner.py`: самое хрупкое (порядок `_bind`: setup_dishka→setup_dialogs-последним; порядок `_cleanup`; ветка skip notifications при `bus=None`, `base.py:66-70`; emit_startup/shutdown в webhook) — без покрытия. Регрессия в порядке wiring (которая в aiogram_dialog ведёт к коллизиям StatesGroup / UnknownState на проде) не будет поймана юнит-тестом. Стоит добавить тест на последовательность `run()` с фейк-`_serve`.

### INFO — `CommandSpec.observer: str` — стрингли-типизированный ключ observer (CAT=types, CONF=medium)

`extension.py:32` — `observer: str` («message» | «pre_checkout_query» | ...), kit делает `dp.observers[spec.observer].register(...)` (`module.py:104-105`). Опечатка в строке (`"messsage"`) → `KeyError` на старте, не на этапе типов. Это малая поверхность (фиксированный набор aiogram-observer'ов) и падает громко на старте, поэтому INFO, не находка. `Literal[...]` типизация была бы строже, но это утечка aiogram-vocabulary в API — текущий компромисс осознан.

### INFO — webhook читает HTTP-конфиг внутри `_serve` (CAT=architecture, CONF=medium)

`webhook.py:33` — `httpkit.new_config()` вызывается прямо в `_serve`, а не инжектится через dishka. Это локальный pull зависимости в обход DI-графа (consistency-нюанс: остальное в ките идёт через provide). Работает (httpkit-конфиг из env), но тестировать webhook-serve в изоляции сложнее. Минор.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. Рантайм-ядро — зрелое и продуманное: корректный deferred-wiring (главная грабля aiogram_dialog отработана), чистая абстракция polling/webhook через template-method, атомарный dedup, RedisEventIsolation для мультиворкера, осмысленная middleware-цепочка с recovery-рубежом, секретный guard на webhook, graceful-shutdown по сигналам. Шаблон вкладывается в kit только декларацией (роутеры/команды/нотификаторы/ErrorUX/резолвер) — это рабочая, не дырявая модель. Два реальных продакшн-пробела до «нормального»: **нет TTL на стейте** (Redis растёт безлимитно) и **мёртвый `BOT_SHUTDOWN_DRAIN`** (обещанного управляемого drain нет). Оба аддитивно чинятся в ките, не ломая шаблон.

**2. Насколько гибкая система?** В части рантайма — гибкость правильной формы: точки расширения (`RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/`LocaleResolver`/`StreamBus`) через dishka last-wins позволяют подменять/наполнять поведение без правки кита; добавление третьего runner-режима — новый `_BaseRunner`-наследник + ветка в `build_runner` (механика для этого есть). Жёсткие места: режим (polling|webhook) — глобальный `cfg.mode`, один на процесс (норма для бота); `state_ttl` пока вообще не настраиваемый. Расширяемость самого рантайма (новый middleware/runner) by design идёт PR'ом в kit, не правкой шаблона — это заявленная граница, а не негибкость.

**3. Про несколько клиентов к разным API.** Вне моей области (это `platform/backend` + httpclient-провайдинг). Из рантайма видно лишь, что kit к этому нейтрален: он не знает про backend-клиентов, инжектит их через dishka как любые APP-scope зависимости. Ограничение «один BackendProvider» — свойство **шаблона/platform**, не tgbotkit-рантайма; kit не мешает зарегистрировать N клиентов разными провайдерами. CONF=medium (не мой файл-набор).

## Вердикт области

Рантайм-ядро tgbotkit — самая сильная и аккуратно спроектированная часть из увиденного: абстракция runner чистая (общий base, расхождение только в `_serve`), deferred dishka/dialogs-wiring корректен, storage/isolation/dedup/секреты webhook'а — на уровне. Протечек aiogram-механики в шаблон нет, границы держатся, mypy/ruff зелёные. Снижают оценку два прод-пробела (нет TTL стейта → безлимитный Redis; мёртвый `BOT_SHUTDOWN_DRAIN`) и тонкое тестовое покрытие именно lifecycle-последовательности.
