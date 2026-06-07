# Аудит области p-obs — observability: logkit + telemetry + bizmetric

Область: три кита `pylibinfra` — `logkit` (структурный логгер), `telemetry` (bootstrap OTel
SDK), `bizmetric` (helper бизнес-метрик). Плюс граничные точки потребления в `tgbotkit`
(`tg_*`-метрики, request_id-middleware) и шаблоне (бизнес-логи).

## Что смотрел

- **logkit** целиком: `logger.py` (Protocol + nop), `structlog_impl.py` (configure/процессоры/
  JSON-форматтер/OTel-bridge), `redact.py` (PII-redact), `config.py`/`service.py`/`module.py`.
- **telemetry** целиком: `init.py` (resource/providers/OTLP/stdout), `config.py`, `decorator.py`
  (`span()`), `module.py` (dishka).
- **bizmetric** целиком: `bizmetric.py` (`counter/histogram/gauge/must_name`).
- Граница потребления: `tgbotkit/metrics.py` (`TgInstruments`), `middleware/request_id.py`
  (что binд'ится в лог-контекст), `middleware/observability.py`, `middleware/recovery.py`,
  `payments/precheckout.py`, `payments/guard.py`; бизнес-логи шаблона
  (`features/payments/usecase.py`, `features/profile/usecase.py`); wiring в `app.py`/`config.py`;
  `.env.example`.
- **Тесты**: `tests/{logkit,telemetry,bizmetric}` — прогнал, 17 passed. Дополнительно
  эмпирически воспроизвёл поведение redactor'а, OTLP-экспорта атрибутов и trace-correlation
  через `uv run python` (см. находки — все доказательства проверены в рантайме).

## Сильные стороны

- **Чёткий kit-on-kit-дизайн, инфра не течёт в шаблон.** `Logger` — это `Protocol` (`logger.py:13`),
  реализация (`structlog`) спрятана; шаблон импортит только `pylibinfra.logkit.Logger`. Бизнес-код
  (`features/payments/usecase.py:18`) принимает `Logger` в конструктор — testable, DIP соблюдён.
- **Корректный graceful-degrade без telemetry.** logkit и `TgInstruments` берут глобальные OTel-
  providers (`metrics.get_meter("app")`); без `telemetry.init` это no-op-meter → метрики и OTLP-
  лог-хэндлер тихо ничего не делают, stdout-JSON продолжает работать (`module.py:10-14`,
  `metrics.py:1-4`). Это не «полукалека», а честный fallback.
- **Redaction покрывает и Loki-путь, не только stdout.** Эмпирически подтвердил: redactor —
  structlog-процессор (`structlog_impl.py:85-89`), отрабатывает ДО передачи в stdlib logging, так
  что и `StreamHandler` (JSON), и `LoggingHandler`→OTLP получают уже `[REDACTED]`-значения.
- **`bizmetric.must_name` — строгая конвенция с fail-fast.** Регэксп `^[a-z][a-z0-9_]*$`
  (`bizmetric.py:20`), `ValueError` на невалидном domain/name, авто-суффиксы (`_total`/`_seconds`),
  префикс `biz_` под автодискавер дашборда. Покрыто параметризованным тестом. Resource-attrs
  (service.name/tenant/env) не дублируются в labels — правильно, их кладёт SDK.
- **`tg_*`-метрики когерентны и осмысленны.** `TgInstruments` (`metrics.py`): RED-набор
  (`tg_updates_total{type,result}` + `tg_update_duration_seconds` с разумными бакетами
  0.005..30s), `tg_update_panics_total`, `tg_updates_deduped_total`. Имена — инфра-стиль (`tg_*`,
  не `biz_*`), консистентно с `http_requests_total` у httpkit. Лейблы низкокардинальны
  (`type`, `result` ∈ ok/error). `span("tg.update")` оборачивает каждый апдейт — трейс есть.
- **`telemetry.init` — грамотный bootstrap.** ParentBased(TraceIdRatioBased) сэмплер,
  W3C trace+baggage propagator (для cross-service-трейса), system-метрики, Bearer-токен к OTLP,
  resource-attrs по OTel-семконвенциям (`deployment.environment.name`), stdout-fallback с
  Simple-процессорами для dev. `Providers.shutdown()` flush'ит в правильном порядке (logs→
  metrics→traces) и зацеплен на закрытие dishka-контейнера (`module.py:19-22`).
- **`span()`-CM** записывает exception + `StatusCode.ERROR` и ре-рейзит (`decorator.py`) —
  аналог `defer(err)` из Go, корректно.

## Находки

### MEDIUM — PII-redact не покрывает вложенные и не-строковые значения (утечка в Loki)
`redact.py:42-46` итерирует только верхний уровень `event_dict` и редактит **только**
`isinstance(value, str)`. Воспроизвёл в рантайме (включён `LOG_REDACT_ENABLED=true`):
- `log.info("evt", email="leak@example.com")` → атрибут `email="[REDACTED]"` ✅
- `log.info("evt", nested={"email":"nested@example.com"})` → в OTLP-атрибутах улетает
  `nested={'email': 'nested@example.com'}` **без редактирования** ❌
- `card=4111111111111111` как `int` (не `str`) → НЕ редактится (паттерн `\d{13,19}` работает
  только по строкам) ❌

То есть любой PII, попавший в логи как элемент dict/list или как число, обходит redact и уезжает
в корп-Loki. Дефолт `enabled=False` (`redact.py:26`) и отсутствие `LOG_REDACT_ENABLED` в
`.env.example` усугубляют: «из коробки» redact выключен совсем. Это не критично (redact —
defence-in-depth, основной контроль — не логировать PII), но заявлен как PII-фильтр, а покрывает
лишь часть поверхности. CONF=high (воспроизведено).
**fix:** рекурсивно обходить dict/list-значения; приводить не-строки к `str` перед матчингом
(или хотя бы редактить `repr` числовых). Добавить `LOG_REDACT_ENABLED` в `.env.example` с
комментарием. Документировать инвариант «redact ≠ замена дисциплины не-логировать PII».

### MEDIUM — `Logger`-протокол не умеет прикрепить exception/traceback (DX + observability)
`logger.py:13-18`: методы `debug/info/warn/error/with_` принимают `msg` + `**kv: Any` — и всё.
Нет ни `exc_info`, ни отдельного `exception()`. `_JsonFormatter` УМЕЕТ форматировать
`record.exc_info` (`structlog_impl.py:66-67`), но протокол не даёт способа его передать. Итог:
структурный лог ошибки несёт только то, что руками положил автор. Симптом виден в самом ките:
`RecoveryMiddleware` — последний рубеж от паники — логирует `error=repr(exc)`
(`middleware/recovery.py:34`), теряя стектрейс; шаблон так же (`payments/usecase` логирует без
ошибок, но паттерн `error=repr(exc)` навязан). Для прод-диагностики «recovered panic» без
трейса — это слепое пятно. CONF=high.
**fix:** добавить в протокол `exception(msg, **kv)` (или `error(..., exc_info=True)`),
прокинуть в `_log.error(msg, exc_info=...)` — structlog/stdlib тогда положат traceback в
`record.exc_info`, форматтер его уже умеет.

### LOW — дублирование `trace_id`/`span_id` в OTLP-лог-записи
`_inject_trace` (`structlog_impl.py:40-45`) кладёт `trace_id`/`span_id` как строковые атрибуты в
каждый лог. Но `LoggingHandler`→OTLP-LogRecord и так несёт trace-context **нативно** (top-level
поля записи). Воспроизвёл: `record.trace_id` (native) и `attributes["trace_id"]` совпадают —
дубль. Для stdout-JSON инъекция оправдана (там нет нативного поля), для OTLP — лишние байты на
каждой строке в Loki и потенциальная путаница (два источника одного факта). CONF=high (дубль
воспроизведён), severity low (косметика/объём).
**fix:** инъекцию trace_id/span_id оставить только в stdout-форматтере (`_JsonFormatter`), не как
общий structlog-процессор; либо осознанно задокументировать как намеренную избыточность.

### LOW — `tg_payments_total{stage=paid}` эмитится только для дубликатов, успешный платёж не считается
`payments/precheckout.py:49` даёт `{stage=pre_checkout, result=ok|rejected|error}` —
полноценно. Но на стадии `paid` единственный эмит — `guard_charge` при дубле:
`{stage=paid, result=duplicate}` (`payments/guard.py:27`). Ни в ките, ни в шаблоне
(`features/payments/handlers.py`, `usecase.py:32-34`) нет `{stage=paid, result=ok}` на успешный
fulfill. Значит метрика **не отвечает** на вопрос «сколько платежей реально завершилось» — видны
только pre_checkout-исходы и paid-дубликаты. Конверсия pre_checkout→paid по метрикам
непосчитываема. Это граница tgbotkit/payments-фичи (не мои три кита напрямую), но прямо про
когерентность `tg_*`. CONF=medium.
**fix:** эмитить `{stage=paid, result=ok}` после успешного `guard_charge=False`+fulfill (в ките —
helper, или в шаблонном хендлере как reference). Привести docstring `__init__`
(`metrics.py:39` — «by result», а лейблов два: `stage`+`result`) в соответствие.

### LOW — глобальное мутабельное состояние `_log_counter` + пересоздание counter в `configure()`
`structlog_impl.py:24` `_log_counter: Counter | None = None` (module-global), переустанавливается
на каждом вызове `configure()` (`:77-78`). В норме `configure()` зовётся один раз (через
`LogkitProvider.logger`), так что на горячем пути это безвредно. Но: (1) глобал делает logkit
несовместимым с двумя независимо сконфигурированными логгерами в одном процессе; (2)
`_inject_trace`/`_count`/redactor — module-level процессоры, опираются на глобал, что хрупко в
тестах (тесты гоняют `configure()` повторно — работает, но через сайд-эффект на глобал). Не баг,
но снижает изоляцию. CONF=medium, severity low.
**fix:** держать counter и redact-цепочку в объекте, привязанном к экземпляру логгера/провайдеру,
а не в module-global (если когда-нибудь понадобится >1 конфигурации).

### INFO — `Logger.warn` вместо `warning`; нет `critical`/`exception`
`logger.py:16` метод называется `warn` (мапится на `_log.warning`, `structlog_impl.py:120-121`).
Это сознательный go-slog-стиль (короткие имена), консистентно внутри кита — ок. Отсутствие
`critical` приемлемо для бота. Фиксирую как info: API узкий, но цельный; единственный реальный
пробел — `exception` (см. MEDIUM выше).

### INFO — горячий путь логгера чистый
`cache_logger_on_first_use=True` (`structlog_impl.py:96`); redactor компилит паттерны один раз в
`build_redactor` (`redact.py:38`), не на запись; при `enabled=False` (дефолт) redactor вообще не
добавляется в цепочку — нулевая стоимость. `_count` — один `counter.add` с bounded-лейблом
`level`. На апдейт-путь логгер не аллоцирует лишнего. Производительных проблем не нашёл.

### INFO — `tg_user_id`/`chat_id` в лог-контексте — это идентификаторы, не контент (приемлемо)
`middleware/request_id.py:30,33` binд'ит `tg_user_id`/`chat_id` в structlog-contextvars → они в
каждом логе апдейта (и в Loki). Это Telegram-ID (числа, не телефон/имя) — для трассировки
обращений нужны, это норма для бота. Не PII в смысле спецкатегорий. Но если включён redact и в
политике компании tg_id считается персональными данными — он НЕ покроется (число, и см. MEDIUM
про не-строки). Фиксирую как контекст к MEDIUM-1, не как отдельную проблему.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** Да. Observability-фундамент серьёзный и
production-grade: структурный JSON-лог + автоматический trace-correlation + OTLP→корп-Loki/
коллектор, RED-метрики апдейтов из коробки, system-метрики, баггедж-пропагация для сквозного
трейса бот↔бэкенд. Для «нормального» бота этого с запасом. Два пробела, которые стоит закрыть до
прода: (а) логгер не умеет прикреплять стектрейс ошибки (MEDIUM-2) — диагностика паник слеповата;
(б) PII-redact частичный и по умолчанию выключен (MEDIUM-1) — если бот логирует пользовательский
ввод, нужна дисциплина «не логировать PII», на redact полагаться нельзя.

**2. Насколько гибкая система?** В части наблюдаемости — достаточно гибкая и при этом не
переусложнённая. `bizmetric` даёт чистый способ добавлять бизнес-метрики со своей доменной
конвенцией (`biz_<domain>_<name>`), `span()` — произвольные трейс-спаны, `Logger.with_()` —
контекстное обогащение, всё конфигурится через env (sampler, endpoint, tenant, redact-паттерны).
Жёсткость только в именах метрик (`must_name`) — и это сознательное благо (когерентность дашбордов
> свобода именования). Никаких архитектурных тупиков для роста наблюдаемости не вижу.

**3. Тревога про «один BackendClient / несколько API».** Вне моей области (это platform/backend),
прямого отношения к observability не имеет. Косвенно: трейс/метрики/логи никак не привязаны к
«одному» клиенту — `httpclient`-инструментация и request_id-propagation сработают для любого числа
исходящих клиентов одинаково (контекствар request_id — глобальный на апдейт). То есть со стороны
observability мульти-клиент-сценарий не создаёт проблем: каждый исходящий вызов получит свой span
и X-Request-ID независимо от того, сколько BackendClient'ов. Симптомом негибкости в МОЕЙ области
это не является.
