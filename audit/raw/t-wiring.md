# Аудит t-wiring — Composition root и жизненный цикл шаблона

Область: `src/bot/app.py`, `src/bot/__main__.py`, `src/bot/extensions.py`, `src/bot/config.py`
(+ кросс-проверка границы с `pylibinfra/tgbotkit` и поведения dishka 1.10.1).

## Что смотрел

- **dishka-проводка и scope.** Корректность APP/REQUEST-разметки провайдеров, порядок аргументов
  в `make_async_container`, реальный механизм last-wins-override в dishka (по исходникам
  `dishka/graph_builder/uniter.py`, `registry.py`, `entities/validation_settings.py`).
- **Коллизии типов.** Пересечение типов, которые отдаёт `BotProvider` (дефолты) и которые
  override'ят `LogkitProvider` / `ExtensionProvider`. Проверял, тихая ли коллизия или dishka
  ругается; эмпирически собрал контейнер и проверил, какой объект побеждает.
- **Выбор runner'а (polling/webhook).** `build_runner` по `cfg.mode`, deferred-проводка
  (`setup_dishka`/`setup_dialogs`), graceful-shutdown в `_BaseRunner._cleanup`, сигналы в
  `WebhookRunner`.
- **Bootstrap/shutdown.** Поток `run()`: `container.get(Tracer)` → `container.get(BotRunner)` →
  `runner.run()`; где зовётся `container.close()` и на всех ли путях.
- **Чтение конфига/секретов.** `AppConfigProvider` как единая точка всех `*Config`, env-алиасы,
  i18n-сборка, отсутствие значений секретов в коде.
- **Граница tgbotkit↔шаблон.** Нет ли инфра-проводки (Bot/Dispatcher/Storage/middleware/
  setup_dialogs/runner) в шаблоне; открыт ли composition root к расширению.

Базовая проверка тревоги: `lint-imports --config importlinter.toml` → **3 контракта KEPT, 0 broken**;
контейнер собирается и резолвится без ошибок (эмпирически, см. ниже).

## Сильные стороны

- **Composition root действительно тонкий и по директиве.** `app.py` — только список провайдеров →
  `make_async_container` → `BotRunner.run()` (`app.py:29-59`). Никакого `Bot`/`Dispatcher`/
  `RedisStorage`/middleware/`setup_dialogs`/webhook-app в шаблоне — всё в kit'е (`tgbotkit/module.py`,
  `tgbotkit/runner/*`). Граница `tgbotkit-boundary` держится буквально.
- **Last-wins override реально работает и проверен эмпирически.** Сборка контейнера даёт:
  `Logger` = `_StructLogger` (реальный logkit, не `_Nop` из `BotProvider.default_logger`),
  `RouterBundle` = 4 роутера, `ErrorUX` = `AppErrorUX`, `OptionalLocaleResolver` = `ChainResolver`.
  То есть `LogkitProvider`/`ExtensionProvider` после `BotProvider` действительно перекрывают дефолты.
  Механизм: dishka собирает фабрики одного `provides`-ключа в группу и при implicit-override
  оставляет последнюю (`uniter.py:60-75`, `when_dependencies=res_factories[::-1]` → «last wins»).
- **Scope-разметка консистентна и корректна.** APP: `BotProvider`, `BackendProvider`,
  `AppConfigProvider`, `ExtensionProvider` (`backend/provider.py:13`, `extensions.py:34`).
  REQUEST: `IdentityProvider` (`identity/provider.py:23`) и все фиче-Provider'ы
  (`features/*/provider.py`). `IdentityProvider` тянет `AiogramMiddlewareData` из REQUEST-контекста,
  который кладёт `AiogramProvider` (`dishka/integrations/aiogram.py:51-52`, `from_context(... scope=REQUEST)`);
  поэтому `AiogramProvider` в списке обязателен — и он там есть (`app.py:35`). Утечки APP↔REQUEST нет.
- **Единая точка конфига — здравая асимметрия.** `AppConfigProvider` собирает ВСЕ `*Config`
  (kit'овые + `AppConfig`) в одном месте (`config.py:46-90`), потому что киты осознанно не
  provide'ят свои `Config` (caller выбирает источник). Env читается через pydantic-settings,
  значений секретов в коде нет (`BOT_TOKEN` и пр. — только алиасы в kit-Config). i18n включён
  из коробки с дефолт-локалью `ru`, env (`BOT_I18N_*`) приоритетнее (`config.py:81-90`).
- **Telemetry-init по DI-побочке оформлен явно и закрывается.** `await container.get(Tracer)`
  триггерит `telemetry.init`; flush — через `container.close()` на shutdown (`app.py:55-57`).
  Комментарий объясняет неочевидное WHY — это правильный кейс по rule `comments`.
- **notifications заведены без лишнего Provider'а.** Фича — NATS-подписчик, ей нужны
  `cache`+`redis` из контейнера, поэтому её собирает `ExtensionProvider.notifiers` через
  `build_router` (`extensions.py:45-46`), а не отдельный dishka-Provider. `OptionalStreamBus`
  гасится в None при выключенном JetStream (`extensions.py:57-60`) — runner тогда корректно
  пропускает нотификации (`runner/base.py:64-71`). Логика «активно только при JetStream» —
  forward-условие, не история.

## Находки

### [medium] Bootstrap-окно не гарантирует `container.close()` при сбое старта

`app.py:53-59`. `container.close()` зовётся **только** внутри `BotRunner.run()` →
`_BaseRunner._cleanup` (`runner/base.py:76-89`, в `finally`). Но в `run()` ему предшествуют два
резолва из контейнера вне всякого try/finally:

```python
container = build_container()
await container.get(Tracer)        # ← открывает telemetry-providers
runner = await container.get(BotRunner)  # ← инстанцирует Bot, Dispatcher, открывает redis-пул, читает nats-bus
await runner.run()                 # close() только отсюда
```

Резолв `BotRunner` тянет `bot`/`dp`/`client`(redis)/`bus` (`module.py:112-133`) — то есть открывает
APP-scope ресурсы с yield-teardown (`bot.session`, redis, nats). Если **любой** из этих резолвов
бросит (плохой `BOT_TOKEN`-валидация, недоступный redis при создании пула, ошибка в фабрике
`dispatcher`/`install_*`, или сам `telemetry.init`), исключение улетит из `run()` **до** входа в
`runner.run()`, и `container.close()` не вызовется — уже открытые провайдеры (telemetry-flush,
частично поднятые соединения) не зачистятся. На разовом краш-старте это не катастрофа (процесс
умрёт), но это негерметичный teardown и расхождение с заявленным инвариантом «graceful shutdown».
Симметрично: `__main__.py` оборачивает только `asyncio.run(run())` без обработки.

**Fix:** обернуть тело `run()` так, чтобы `container.close()` гарантированно отрабатывал и при
сбое bootstrap'а, например `async with container:` или `try/finally` вокруг
`get(Tracer)`+`get(BotRunner)`+`runner.run()`. CONF=high (по коду путь однозначный).

### [medium] Тихий last-wins держится на дефолтной (нестрогой) валидации dishka

`app.py:30` (`make_async_container(...)` без `validation_settings`). Override дефолтов `BotProvider`
происходит **без** явного маркера `override` — это implicit-override. dishka ругается на него
(`ImplicitOverrideDetectedError`) только если включён `implicit_override`, а
`make_async_container` по умолчанию использует `DEFAULT_VALIDATION`, где он `False`
(`dishka/entities/validation_settings.py`: `implicit_override: bool = False`;
`async_container.py:412` — дефолт `DEFAULT_VALIDATION`). То есть весь контракт «BotProvider даёт
дефолты, шаблон молча перекрывает порядком» работает ровно потому, что dishka **не** в строгом
режиме. Последствия: (1) если кто-то когда-нибудь передаст `STRICT_VALIDATION` — контейнер упадёт
на старте на легитимных override'ах Logger/RouterBundle/ErrorUX/Resolver/Bus; (2) случайная
повторная регистрация того же типа в шаблоне (например два провайдера отдают `RouterBundle`) тоже
пройдёт молча — реальную коллизию dishka не подсветит, победит «последний в списке». Это не баг
сейчас, но хрупкая опора: порядок аргументов в `app.py` — единственный source of truth корректности,
без машинной страховки. CONF=high (поведение dishka проверено по исходникам).

**Fix:** опционально явно помечать override'ящие провайдеры (`@provide(... override=True)` в
`ExtensionProvider`/`LogkitProvider`) и/или включить `implicit_override` в валидации — тогда
коллизия из дефолта станет осознанной, а случайная — падающей. Минимум — закрепить инвариант
порядка composition-smoke-тестом (проверять, что Logger≠nop, RouterBundle непуст и т.п.).

### [low] Набор фич захардкожен в двух местах без единого реестра

`app.py:24,42-49` (импорт `lang, payments, profile, start` + 4 `*.Provider()`) и
`extensions.py:29,37-42` (импорт пяти фич + ручная сборка `RouterBundle`/`CommandBundle`).
Добавление фичи требует синхронной правки обоих файлов: dishka-Provider в `app.py` **и**
роутер/команд в `extensions.py`. Реестра/авто-дискавери нет. Для **тонкого ревьюабельного шаблона
это осознанный trade-off** (явная регистрация > магия; так и заявлено в `de-template`/`scaffold`),
и `scaffold feature` автоматизирует обе правки. Но как «гибкость» это значит: набор фич — не
конфиг, а код в composition root; рассинхрон (Provider есть, в bundle забыли) проявится не на
сборке контейнера, а как «фича не реагирует» в рантайме. CONF=high. Скорее `info`, чем дефект, —
фиксирую для ответа на вопрос о гибкости.

**Fix:** не требуется; при желании — composition-smoke-тест, что каждый зарегистрированный
фиче-`Provider` имеет роутер в `RouterBundle` (ловит рассинхрон двух списков).

### [info] `BOT_SHUTDOWN_DRAIN` объявлен, но не потребляется (это kit, не шаблон)

Смежно с remit'ом «graceful shutdown»: `tgbotkit/config.py:47` декларирует
`shutdown_drain` (`BOT_SHUTDOWN_DRAIN`, дефолт 10с «на drain in-flight апдейтов»), но ни
`PollingRunner`, ни `WebhookRunner` его не используют — webhook на сигнале сразу `server.stop()`
без таймированного дренажа активных хендлеров (`runner/webhook.py:53-64`), polling полагается на
`start_polling`. Шаблон это **не может** починить (поверхность kit'а), но env обещает поведение,
которого нет. CONF=high. Не находка по шаблону — контекст для оркестратора / кандидат в
INFRA-HANDOFF к tgbotkit.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. Composition root собирается и резолвится без
ошибок, scope-разметка APP/REQUEST корректна, override-механика работает как заявлено (проверено
эмпирически), runner-выбор polling/webhook на месте, конфиг и секреты читаются через стандартный
pydantic-settings без хардкода. Каркас жизненного цикла рабочий и тонкий.

**2. Насколько гибкая система?** В части проводки — гибкость заложена правильно: точки расширения
(`RouterBundle`/`CommandBundle`/`NotifierBundle`/`ErrorUX`/`Resolver`/`Bus`) override'ятся одним
провайдером после kit'а, добавление фичи — две локальные правки (+scaffold). Цена гибкости —
**ручная** регистрация в двух списках и **тихий** last-wins без машинной страховки от коллизий
(находки medium/low): порядок провайдеров в `app.py` — единственный гарант корректности. Это
управляемо для ревьюабельного шаблона, но требует дисциплины и желательно composition-smoke-теста.

**3. Тревога про один `BackendClient` (APP-scope, единственный `BackendProvider`).** С точки зрения
wiring это **не** структурная негибкость: `BackendProvider` — обычный APP-провайдер
(`backend/provider.py:12-17`), и завести второй клиент к другому API — это добавить ещё один
провайдер с **другим типом** (напр. `PaymentsClient`/`CrmClient` со своим `httpclient.Config`) в
тот же `make_async_container`. dishka различает зависимости по типу, коллизии не будет, last-wins
тут ни при чём (разные `provides`-ключи). Ограничение не в composition root, а в том, что сам
`BackendClient`/`HttpConfig` сейчас одиночные (один `HttpConfig` в `AppConfigProvider:72-74`, один
`Client` из `HttpClientProvider`) — мультибэкенд потребует разнести `httpclient.Config`/`Client` по
тегам/типам. Это вопрос к области platform/backend, не к t-wiring; со стороны проводки
расширение под N клиентов — аддитивное (ещё провайдеры), а не переделка корня.
