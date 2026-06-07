# Аудит d-security — сквозной синтез безопасности поперёк обоих репо

Линза: безопасность как система. Не отдельный кит, а **поверхность угроз** Telegram-бота на
`telegram-bot-template` + `pylibinfra[tgbotkit]`. Синтез поверх готовых отчётов (`p-sec`,
`k-tgbot-feat`, `t-platform`, `p-obs`, `p-cfg-time`, `p-http`) с собственной перепроверкой
критичных мест по исходникам обоих репо.

## Что смотрел (своими глазами)

- **WebApp initData**: `pylibinfra/.../tgbotkit/webapp/init_data.py` (HMAC-алгоритм, TTL,
  constant-time) + продуктовый парсер `src/bot/platform/webapp/init_data.py`.
- **Payments**: `tgbotkit/payments/{guard,precheckout,invoice}.py` + потребитель
  `src/bot/features/payments/handlers.py` (где реально решается «доверять ли сумме»).
- **Webhook secret-token**: `httpkit/webhook_secret.py` (`shared_secret_guard`) +
  `tgbotkit/runner/webhook.py` (приём апдейта, `set_webhook`).
- **Secret-handling**: `tgbotkit/config.py` (BOT_TOKEN/webhook_secret), `config/vault.py`
  (VAULT_TOKEN, VaultSource), `config/loader.py` (ValidationError-утечка), `src/bot/config.py`.
  Грепнул `SecretStr` по **обоим** репо.
- **PII в логах/Redis**: `logkit/redact.py`, `middleware/request_id.py` (что биндится в лог),
  FSM-storage `tgbotkit/storage.py`, бизнес-логи `features/{profile,payments}/usecase.py`,
  `.env.example` (дефолты).
- **SSRF / инъекции**: `httpclient/client.py` (`request`, base_url vs абсолютный url),
  `httpclient/module.py`, `platform/backend/client.py`, `features/*/gateway.py` (как строится
  path), `platform/identity/provider.py` (откуда берётся `backend_user_id`).
- **authnkit / bruteforcekit**: `authnkit/{jwt,totp,hasher}.py`, `bruteforcekit/{guard,pgstore}` —
  тайминг, обходы, неработающее окно.
- **bandit-поверхность**: `uv run ruff check --select S src` в **обоих** репо.
- **DoS входящего вебхука**: `httpkit/server.py` (MaxBody/RateLimit/Security/Recovery в цепочке).

**Прогоны:** `ruff --select S` (шаблон — All checks passed; pylibinfra — 1× S101 assert).
Подтвердил неиспользование sec-китов: `grep authnkit|bruteforcekit|auditkit|HS256JWT|TOTP|Argon2`
по `src/`+`tests/` шаблона — **пусто**.

## Ключевой контекст: что бот реально использует

Поверхность атаки бота определяется тем, что **активно в проде**, а не тем, что лежит в pylibinfra:

- **Аутентификация бота = подписанные Telegram-апдейты** (polling) или **secret-token вебхука**
  (webhook). Пароли/JWT/TOTP/RBAC-реестр (`authnkit`) и bruteforce-guard логина
  (`bruteforcekit`) — **не подключены** (подтверждено грепом; не входят даже в extra `[tgbotkit]`).
  Поэтому слабости sec-китов (см. ниже INFO-блок) — **не эксплуатируемы в дефолтном боте**; они
  станут боевыми только если консьюмер сам потянет кит ради собственного парольного backend-логина.
- **Активная security-поверхность бота**: (1) initData-валидация (если включён webapp/webhook),
  (2) payments precheckout + charge-dedup, (3) webhook secret-token, (4) обращение к одному
  бэкенду через httpclient, (5) секреты в env/Vault, (6) PII в логах/Redis/FSM.

Это смещает severity: **критичных эксплойтов в дефолтном проде я не нашёл** — самые
security-чувствительные места (HMAC initData, проверка суммы на бэкенде, constant-time, fail-closed)
сделаны **правильно**. Реальные риски — operational/defence-in-depth, и сосредоточены в
**обработке секретов** и **PII**.

## Сильные стороны (подтверждено своими глазами)

- **initData-HMAC спец-корректен** (`webapp/init_data.py:26-37`). `secret =
  HMAC("WebAppData", token)`; `expected = HMAC(secret, data_check_string)`; из строки исключается
  **только** `hash` (поле `signature` остаётся — это верно для bot-token-метода);
  `hmac.compare_digest` (constant-time); TTL по `auth_date` с `max_age=300`. Подделка отбивается,
  крипта не переизобретена (шаблон только парсит уже проверенный `user` —
  `platform/webapp/init_data.py:24`). Гипотезу «`signature` надо исключать» спецификация Telegram
  опровергает — kit прав.
- **Подмена суммы/валюты в платеже не проходит**. `answer_pre_checkout` (`precheckout.py:41`)
  гоняет `decide(query)` под `asyncio.wait_for(deadline=9.0 < 10с)`, fail-closed на
  timeout/исключении (`:43-45`). Шаблон в `decide` **не доверяет** `q.total_amount`, а сверяет на
  бэкенде: `uc.confirm(q.invoice_payload, q.total_amount, q.currency)`
  (`features/payments/handlers.py:53-55`). Это правильная модель «бэкенд — источник истины по цене».
- **Идемпотентность платежа** атомарна: `guard_charge` — `SET NX EX` по
  `tg:charge:<charge_id>` (`guard.py:24`), at-least-once successful_payment не двоит fulfilment
  (при идемпотентном `uc.complete` на бэкенде).
- **Webhook secret-token — fail-closed + constant-time**. `shared_secret_guard`
  (`webhook_secret.py:36-39`): пустой секрет ИЛИ несовпадение → 403; сверка `hmac.compare_digest`.
  Тот же секрет ставится в `set_webhook(secret_token=...)` (`webhook.py:48`). Telegram-CIDR не
  нужен — secret-token закрывает спуфинг вебхука.
- **DoS входящего вебхука закрыт штатно**: webhook-рантайм строится на `httpkit.Server`, и в
  цепочке уже навешаны `MaxBodyMiddleware` (413 по content-length, `server.py:69`),
  `RateLimitMiddleware` (`:70`), `SecurityHeadersMiddleware` (`:66`), `RecoveryMiddleware` (`:67`).
  Бот не пишет это руками — берёт из kit'а.
- **at-least-once дедуп апдейтов**: `DedupMiddleware` (`SET NX EX` по `bot_id:update_id`) +
  `ThrottleMiddleware` (per-user token-bucket) — спам/повторы отбиваются без Postgres.
- **JWT защищён от algorithm-confusion** (`authnkit/jwt.py:67`): `algorithms=["HS256"]` — pyjwt
  отвергает `alg=none`/RS256-подмену. **TOTP/argon2 constant-time** (внутри библиотек). SQL —
  параметризованный, инъекций нет (детально — отчёт `p-sec`).
- **bandit-поверхность чистая**: шаблон — 0 находок `S`; pylibinfra — единственный `S101`
  (`assert` в `httpkit/error.py:172`, под защищённым типовым инвариантом) — это **не дыра**.

## Находки (по severity)

### HIGH — секреты по всей системе хранятся как голый `str`, не `SecretStr` → утечка в repr/трейсбек/ValidationError

**CAT=security, CONF=high, KEY=yes**

`SecretStr` **не используется нигде** в обоих репо (`grep SecretStr src/` по обоим — пусто). Все
секреты — обычный `str`:

- `BOT_TOKEN` (`tgbotkit/config.py:30`), `webhook_secret` (`:43`);
- `VAULT_TOKEN` (`config/vault.py:12`), `JWTConfig.secret` (`authnkit`), NATS/Redis creds в URL;
- `AppConfig`/все kit-`Config` — `repr()`/`model_dump()` печатают значения **открытым текстом**.

Два конкретных канала утечки (подтверждено по коду + поведению pydantic v2):

1. **ValidationError печатает `input_value`.** `config/loader.py:25` делает
   `model_cls(**overrides)`, где `overrides` — секреты из Vault. Невалидный секрет (тип не сошёлся /
   кастомный validator упал) → `pydantic.ValidationError` по умолчанию включает само значение
   секрета в текст ошибки; ошибка **ничем не оборачивается** и улетает в трейсбек на старте → в
   stderr/логи. logkit-redact её не ловит (это голый трейсбек, не структурный лог-вызов). Source-
   ошибка оборачивается как `RuntimeError(f"...: {exc}")` (`loader.py:23-24`) — если hvac положит в
   `exc` тело ответа, секрет уедет в сообщение. (Это же — MEDIUM в `p-cfg-time`; здесь поднимаю до
   HIGH в сумме с системным отсутствием `SecretStr`.)
2. **`repr`/случайный лог конфига.** Любой `log.info("config", cfg=cfg)` или дамп объекта в
   диагностике/исключении напечатает `BOT_TOKEN`/`webhook_secret` открыто — тип не маскирует.

Почему HIGH, а не medium: это **системный** дефект обработки секретов (не один файл), а
**BOT_TOKEN — самый ценный секрет бота** (компрометация = полный захват бота). Сейчас единственная
защита — дисциплина «не логировать конфиг целиком» + vault-agent (который выводит config из
loader-пути). Это держится на договорённости, не на типах. Эксплуатируемость средняя (нужен триггер
— упавшая валидация секрета или неосторожный лог), но **импакт максимальный**.

**fix:** секретные поля → `pydantic.SecretStr` (`token: SecretStr`, `webhook_secret: SecretStr`,
`VaultClientConfig.token`, `JWTConfig.secret`) — даёт `repr`-маскирование из коробки; в `Bot(...)`
и `set_webhook` доставать `.get_secret_value()`. В `loader.load()` ловить `ValidationError` и
переподнимать без `input_value` (только имена полей). Source-ошибку оборачивать без интерполяции
`exc` целиком. Это PR в `pylibinfra` (config/tgbotkit/authnkit) + ревизия шаблонного `config.py`.

### HIGH — PII-redact частичный и выключен по умолчанию; в `.env.example` его нет вообще

**CAT=security, CONF=high, KEY=yes**

`logkit/redact.py` — единственный встроенный контроль «не утекает ли PII в Loki», и он дыряв на
двух осях (подтверждено `p-obs` в рантайме, перепроверил по коду):

- **Только верхний уровень + только `str`** (`redact.py:42-46`): `isinstance(value, str)` —
  вложенный `nested={"email": ...}` и **числовые** значения (`card=4111... как int`, **`tg_id`**)
  проходят мимо редактора и уезжают в OTLP→Loki.
- **`enabled=False` по умолчанию** (`redact.py:26`), и `LOG_REDACT_ENABLED` **отсутствует в
  `.env.example`** (проверил — в файле его нет). То есть «из коробки» redact выключен и не виден
  оператору как опция; включив его, оператор всё равно не покроет dict/числа.

Импакт привязан к тому, что бот **реально** кладёт в логи. В reference-фичах сейчас гигиенично:
`profile.usecase` логирует только `tg_id` (`usecase.py:36`), `email` из `ProfileView` не
логируется. `request_id`-middleware биндит `tg_user_id`/`chat_id` — это Telegram-ID (числа, не
спецкатегория PII), для трассировки норма. **Но** контракт «redact = фильтр PII» **переобещан**:
как только потребитель залогирует пользовательский ввод (имя/email/телефон) — вложенным или
числом — он молча уедет в корп-Loki. redact — defence-in-depth, а подан как фильтр.

Почему HIGH: это **прямой комплаенс-риск** (PII в централизованных логах), дефолт небезопасный
(выключен + не документирован), а у заказчика будет **несколько бэкендов** (его явный сценарий) —
вероятность залогировать ответ бэкенда с PII растёт. Эксплуатируемость = «обычная неосторожность
разработчика фичи», а не активная атака — поэтому это про дисциплину + дырявый предохранитель.

**fix:** рекурсивно обходить dict/list; приводить не-строки к `str` перед матчингом; добавить
`LOG_REDACT_ENABLED`/`LOG_REDACT_PATTERNS` в `.env.example` с комментарием; в доке прямо написать
«redact ≠ замена дисциплины не-логировать PII» (это defence-in-depth, не граница). PR в `logkit` +
правка `.env.example` шаблона.

### MEDIUM — webhook secret пустой по умолчанию: fail-closed безопасен, но создаёт «тихо мёртвый бот» вместо явной ошибки старта

**CAT=security, CONF=high, KEY=no**

`BOT_WEBHOOK_SECRET=` пуст в `.env.example` (подтверждено). В webhook-режиме:
`set_webhook(secret_token=cfg.webhook_secret or None)` (`webhook.py:48`) — при пустом секрете
Telegram шлёт апдейты **без** заголовка; а `shared_secret_guard` при `not expected` **отбивает
любой** запрос 403 (`webhook_secret.py:38`). Итог: бот в webhook-режиме с незаданным секретом
**молча не получает ни одного апдейта** (все 403). Безопасность не страдает (fail-closed — это
**правильно**: лучше отбить всё, чем принять неаутентифицированный вебхук), но:

- нет **fail-fast на старте** («webhook-режим требует BOT_WEBHOOK_SECRET») — оператор узнаёт о
  проблеме по «бот не отвечает», а не по понятной ошибке;
- риск «временного» обхода: под давлением оператор может прийти к мысли убрать guard, чтобы
  «заработало» — антипаттерн, которого нет явного предупреждения.

**fix:** в webhook-рантайме при `mode=webhook` и пустом `webhook_secret` — fail-fast с явным
сообщением (а не молчаливый 403-loop). Это PR в `tgbotkit/runner` + пометка в `.env.example`
«обязателен для webhook».

### MEDIUM — SSRF/path-injection через httpclient: абсолютный url игнорирует base_url; path-сегменты в gateway не экранируются

**CAT=security, CONF=medium, KEY=no**

`httpclient.Client.request(method, url)` (`client.py:82`) передаёт `url` в `httpx.request` поверх
`AsyncClient(base_url=...)` (`module.py:18`). Семантика httpx: **если `url` абсолютный (содержит
схему+host) — base_url игнорируется**, запрос уходит на host из `url`. То есть контроль «клиент =
один сервис» держится **только** на дисциплине вызывающего давать относительный path.

В reference-фичах эксплойта нет: path — литералы с интерполяцией `backend_user_id`
(`profile/gateway.py:22,33`: `f"/v1/users/{backend_user_id}"`), а `backend_user_id` приходит из
cache-линка или = `str(tg_id)` (число) — `identity/provider.py:42`. Свободного пользовательского
URL в path нет. **Но контракт хрупкий**:

- если потребитель положит в path **пользовательский ввод** (slug, имя, любой
  attacker-controlled-фрагмент) — `httpx` **не** экранирует path-сегменты в f-string: `../`,
  `@evil.com`, `%2e%2e` могут дать path-traversal или (при определённых формах) увод на чужой host;
- `BackendClient.get/post/patch(path)` (`platform/backend/client.py:25-36`) принимает голый
  `str path` без проверки «относительный ли он» — фасад не защищает.

Почему MEDIUM (не high): в дефолтном шаблоне не эксплуатируется (path — литералы + числовой id), и
бэкенд один. Но это **незакрытый класс уязвимости в «нерве»** (единая точка исходящих вызовов), и
он становится острее в сценарии заказчика с **несколькими API** — туда легко прорастёт
attacker-controlled path.

**fix:** в `httpclient.Client` или `BackendClient` отвергать абсолютные url (assert
`not httpx.URL(path).is_absolute_url` / `not host`), либо строить путь через
`httpx.URL(base).join(path)` с проверкой, что host не сменился; в `scaffold/backend-port.md`
зафиксировать инвариант «path — только относительный литерал, пользовательский ввод — через
query/body или `urllib.parse.quote`, не в path-сегмент».

### LOW — `identity` фолбэк `backend_user_id = tg_id` может уводить запрос в чужую запись

**CAT=security, CONF=low, KEY=no**

`identity/provider.py:42`: до линковки `backend_user_id = str(tg_id)`, и он уходит в
`GET /v1/users/{backend_user_id}` (`profile/gateway.py:22`). Если на бэкенде id пользователей — не
Telegram-id (почти всегда разные пространства), до линковки запрос либо 404, либо (хуже) попадёт в
**чужую** запись с совпавшим числовым id — это потенциальный IDOR-класс на стороне бэкенда. Зависит
от контракта бэкенда заказчика (поэтому CONF=low), но как граблю онбординга фиксирую (дубль
`t-platform` INFO, поднимаю как security-аспект).

**fix:** до линковки не дёргать backend-by-id; явный признак «не слинкован» вместо подмены tg_id.

### LOW — `_decode` парсит `resp.json()` без guard → не-JSON 2xx всплывает как паника, минуя доменную классификацию

**CAT=security, CONF=medium, KEY=no**

`platform/backend/client.py:60-64`: на любом 2xx с телом — `resp.json()`. HTML/`text/plain` от
прокси/WAF на 200 → `JSONDecodeError` (не `BackendError`) → не ловится в `_request` → всплывает
паникой. Security-грань: ответ промежуточного устройства (captive portal / WAF challenge) на 200
не отличается от валидного, и обрабатывается как краш, а не как «бэкенд недоступен». (Дубль
`t-platform` LOW.) **fix:** обернуть `resp.json()`, мапить в `BackendUnavailable`.

### INFO — слабости sec-китов реальны, но НЕ в поверхности бота (не активированы)

Зафиксировано детально в `p-sec`; перепроверил по коду и подтверждаю. Эксплойта в дефолтном боте
**нет** (киты не подключены), но при активации консьюмером станут боевыми:

- **bruteforce-`window` не реализован** (`bruteforcekit/pgstore/store.py` — `window` в SQL не
  участвует; `failed_count` растёт за всю историю): «защитный» env `BRUTEFORCE_WINDOW` читается и
  **ничего не делает** → ложные локи легитимных юзеров + счётчик без самосброса. Унаследовано из
  golibinfra. Самое опасное состояние «безопасного» параметра — есть, валидируется, не работает.
- **TOTP без `valid_window`** (`authnkit/totp.py:20`): нет допуска на дрейф часов (±0с против
  Skew:1 в Go-источнике) → ложные «неверный код». UX-деградация, не дыра.
- **auditkit не tamper-evident** сам по себе (нет триггера-запрета `UPDATE/DELETE`/hash-chain) —
  «append-only» обеспечивается грантами БД, кит молчит про это: нейминг обещает больше кода.
- **timing в `bruteforcekit.Guard.check`** (`guard.py:38`): read-строка-есть/нет даёт микро-
  тайминг, но раскрывает лишь «заблокирован/нет», не секрет — приемлемо.

Все четыре — `info` **для бота**; для консьюмера, поднявшего парольный backend-логин, bruteforce-
`window` поднимается до medium (см. `p-sec`).

### INFO — PII в FSM-Redis не шифруется (стандартно для aiogram, но стоит знать)

`tgbotkit/storage.py:15` — `RedisStorage` с `DefaultKeyBuilder(with_bot_id, with_destiny)`. В
`dialog_data` шаблона может попасть введённое пользователем имя (rename-флоу) — оно ляжет в Redis
**открытым текстом**. Это стандартное поведение aiogram-FSM (не дефект kit'а), TTL/изоляция
корректны. Фиксирую как контекст: централизованный Redis с пользовательским вводом — это PII-at-rest
без шифрования; если в политике компании это значимо — нужна дисциплина «минимум PII в FSM».

## Системная картина угроз (severity × эксплуатируемость)

| Угроза | Где | Severity | Эксплуатируемость в дефолтном боте |
|---|---|---|---|
| BOT_TOKEN/секреты голым `str` → утечка в trace/repr | оба репо, config-слой | **HIGH** | средняя (нужен триггер: упавшая валидация секрета / неосторожный лог); импакт максимальный |
| PII-redact дырявый + off + не в env.example | logkit + .env.example | **HIGH** | «обычная неосторожность фичи»; комплаенс-риск, не активная атака |
| webhook secret пустой → мёртвый бот / соблазн снять guard | tgbotkit/runner + env | MEDIUM | только webhook-режим; fail-closed безопасен, риск операционный |
| SSRF/path-injection если path = пользовательский ввод | httpclient + backend | MEDIUM | в reference — нет (path литералы+число); риск растёт с мульти-API |
| identity-фолбэк tg_id → чужая запись (IDOR-класс) | identity + gateway | LOW | зависит от бэкенда заказчика |
| не-JSON 2xx → паника | backend/client | LOW | маловероятно при дисциплинированном бэкенде |
| sec-киты (bruteforce-window/TOTP/audit) | pylibinfra | INFO (бота) | **не активны** в боте; medium при ручной активации |

**Подмена суммы/валюты, HMAC initData, constant-time, идемпотентность платежа, webhook
secret-token, инъекции SQL, bandit** — проверены и **закрыты правильно**. Реальная атака на
дефолтный прод-бот через эти векторы не проходит.

## Что критично закрыть до продакшена

1. **`SecretStr` для BOT_TOKEN/webhook_secret/VAULT_TOKEN/JWT-secret** + не печатать `input_value`
   в `loader` ValidationError (HIGH). Без этого один неудачный старт / неосторожный лог = слив
   токена бота = полный захват.
2. **Redact: рекурсия + не-строки + включить документированно** и добавить `LOG_REDACT_ENABLED` в
   `.env.example`; зафиксировать «redact ≠ дисциплина не-логировать PII» (HIGH). Комплаенс по PII в
   корп-Loki.
3. **Fail-fast при пустом webhook_secret в webhook-режиме** (MEDIUM) — убрать «тихо мёртвый бот».
4. **Отвергать абсолютный url / экранировать path в httpclient или BackendClient** + инвариант в
   `backend-port.md` (MEDIUM) — закрыть SSRF/path-injection до того, как заказчик подключит
   attacker-controlled path (особенно при нескольких API).

Пункты 1-2 — PR в `pylibinfra` (config/logkit/tgbotkit) через INFRA-HANDOFF, не правка шаблона.
3-4 — частью в kit, частью в гайды/`.env.example` шаблона.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** По безопасности — **да, фундамент крепкий**: самые
опасные места (HMAC initData, проверка цены на бэкенде, constant-time, fail-closed precheckout/
webhook-guard, идемпотентность платежа, DoS-защита вебхука, дедуп/throttle) сделаны **правильно и
спец-корректно** — это редкость. Под прод нужно закрыть **обработку секретов** (`SecretStr`) и
**PII-redact** — оба defence-in-depth, оба чинятся в kit без слома API шаблона. Это не
архитектурные дыры, а недотянутая гигиена.

**2. Насколько гибкая система (с т.з. безопасности)?** Security-механики обобщены адекватно:
`shared_secret_guard` aiogram-agnostic, payments параметризованы (currency/provider_token/decide),
sec-киты — чистые порты с подменяемыми бэкендами. Жёсткость одна и она **на пользу**: precheckout
заставляет проверять цену на бэкенде, guard fail-closed — это правильные «рельсы безопасности», а
не негибкость.

**3. Тревога про один BackendClient (с т.з. безопасности).** Мульти-API **усугубляет** ровно
security-аспект: (а) общий circuit breaker под одним именем (косметика безопасности — DoS одного
API гасит все, см. `t-platform`/`p-http`); (б) **SSRF/path-контроль** становится острее — больше
исходящих адресатов = больше шансов на attacker-controlled path; (в) больше шансов залогировать
PII из ответа второго бэкенда при дырявом redact. То есть мульти-бэкенд — не только flexibility-,
но и **security-долг**: при расширении на N API пункты «отвергать абсолютный url» и «починить
redact» из «желательно» становятся «обязательно».
