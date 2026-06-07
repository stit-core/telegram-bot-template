# Реестр находок — дъявольский аудит telegram-bot-template + pylibinfra

Сводный реестр находок 32 агентов-аудиторов (1 ground-truth + 16 поблочных + 9 сквозных линз +
6 стресс-сценариев), с уточнением severity после адверсариальной верификации 9 топ-находок.
Детальные отчёты по каждой области — в `audit/raw/<id>.md`.

**Легенда статуса:**
- ✅ **verified** — прошла адверсариальную проверку (скептик пытался опровергнуть, не смог); severity — финальная.
- 🔁 **multi-source** — независимо найдена несколькими агентами, high-confidence, отдельно не верифицировалась.
- ◽ **single-source** — одна область, доказательство `file:line` есть.

**KIT** = чинится в `pylibinfra/tgbotkit` (INFRA-HANDOFF / PR в kit). **TPL** = правка шаблона.

> `docs/` и `design/` намеренно очищены заказчиком и будут переписаны — их отсутствие **в реестр не входит**
> (хотя несколько находок DX/wiring ссылаются на расхождение «дока обещает X, кода нет» — это про живые
> docstring/skill-файлы, не про снесённый каталог).

---

## CRITICAL (2) — чинить до прода с диалогами/уведомлениями

| ID | Находка | Где | Статус | Чинить |
|----|---------|-----|--------|--------|
| **C1** | `RecoveryMiddleware` ловит dialog-исключения (`UnknownIntent`/`OutdatedIntent`/`UnknownState`) **раньше** `dp.errors` → и кастомный stale-UX (`errorux.register_error_handlers`), и штатный stack-recovery aiogram_dialog (`IntentErrorMiddleware._fix_broken_stack`) **мертвы**. Юзер с протухшей кнопкой после деплоя залипает в петле «что-то пошло не так» до ручного `/start`. **Воспроизведено на живом Dispatcher.** | `tgbotkit/middleware/recovery.py:31`, `__init__.py:45` | ✅ verified | KIT |
| **C2** | **Тихая потеря уведомлений (at-most-once).** `dedup.seen()` метит ключ `SET NX EX` **до** отправки; `Delivery.send_message` ловит и **проглатывает** исключение; JetStream делает `ack()` раз handler не бросил → push потерян без следа и без redelivery. Бьёт по бизнес-событиям (`order_paid`). Анти-паттерн «mark-before-commit + swallow» прописан инвариантом в `background-updates.md`. **Воспроизведено.** | `notifications/deliver.py:29`, `tgbotkit/notifications/delivery.py:46-53`, `dedup.py:17`, `natskit/jetstream.py:144` | ✅ verified | KIT (+TPL) |

---

## HIGH (8)

| ID | Находка | Где | Статус | Чинить |
|----|---------|-----|--------|--------|
| **H1** | **Окно потери выдачи платежа.** `guard_charge` ставит дедуп-ключ **до** `complete`; при сбое `fulfill` исключение глотает recovery, redelivery заглушён ключом → деньги списаны, выдачи нет, авто-восстановления нет. Бэкенд-идемпотентность не спасает — второго вызова `fulfill` не происходит. | `payments/handlers.py:71-73`, `tgbotkit/payments/guard.py:24`, `payments/gateway.py:36` | ✅ verified | KIT (+TPL) |
| **H2** | **Нет соблюдения Telegram rate-limit на исходящем пути.** Ни global 30 msg/s, ни 1 msg/s/chat, ни обработки `TelegramRetryAfter` (aiogram 3.28 по дефолту 429 **не** ретраит). Backpressure JetStream (`max_in_flight=100`) развязан с лимитом Telegram → до 100 параллельных `send` → 429 → проглот (C2). Триггерится при включённом JetStream под burst-нагрузкой. | `tgbotkit/module.py:79`, `notifications/delivery.py:46-53`, `natskit/jetstream.py:106`, `config.py:19` | ✅ verified | KIT |
| **H3** | **Секреты — голый `str`, не `SecretStr`.** `BOT_TOKEN`/`webhook_secret`/`VAULT_TOKEN` печатаются открыто в `repr`/`model_dump`; `config.load()` интерполирует значение секрета в трейсбек `ValidationError` при старте. `redact` off-by-default и чистит только top-level `str`. | `tgbotkit/config.py:30,43`, `config/vault.py:13`, `config/loader.py:25` | ✅ verified | KIT |
| **H4** | **Мульти-тенант: `with_bot_id` изолирует только FSM+update-dedup**, а `links`/`locale`/`throttle`/`notify-dedup` — плоские ключи без `bot_id` → cross-tenant коллизия онбординга/identity-линка/локали на общем Redis. Docstring `storage.py` ложно сигналит мультибот-готовность. | `tgbotkit/storage.py:1-4,17`, `platform/links.py:12-14`, `i18n/resolver.py:36`, `throttle.py:26`, `notifications/dedup.py:17` | ✅ verified | KIT+TPL |
| **H5** | **Realtime fan-out — демо-уровень (verdict: blocked).** Композит H2 + ordering не гарантирован (`ordered_consumer=False`, нет per-chat single-flight) + drain теряет in-flight + poison-loop. Честный потолок: теряет уже на десятках msg/s и **молча**. | `natskit/jetstream.py:106,111`, `notifications/runner.py:33` | 🔁 multi-source | KIT |
| **H6** | **Refund/recurring/фиат отсутствуют как класс.** Нет порта/usecase/хендлера `refunded_payment`, нет `create_invoice_link(subscription_period)`, `amount:int` перегружен (XTR vs минорные единицы). aiogram 3.28 **уже даёт** `refund_star_payment`/subscription API — пробел в kit/шаблоне, не в Telegram. (verdict: blocked) | `tgbotkit/payments/invoice.py:13-33`, `payments/ports.py:14-17`, `dto.py:16` | 🔁 multi-source | KIT+TPL |
| **H7** | **Хрупкость на старте/разрыве инфры.** NATS-down или Redis-down при старте роняет весь бот (Telegram-polling не стартует); нет reconnect-callback'ов (`max_reconnects=60` → молча умирает через ~2 мин); нет fail-open; в polling-режиме нет health-эндпоинта. | `tgbotkit/module.py:121`, `natskit/conn.py:23-28`, `runner/polling.py` | 🔁 multi-source | KIT |
| **H8** | **Poison-message hot-loop.** JS-консьюмер без `max_deliver`/`nak(delay)`/backoff/DLQ → честно бросающий handler уходит в tight-loop редоставки до `max_age` стрима (7 дней), жжёт CPU, забивает `max_ack_pending`. | `natskit/jetstream.py:101-107,142` | 🔁 multi-source | KIT |

---

## MEDIUM (12)

| ID | Находка | Где | Статус | Чинить |
|----|---------|-----|--------|--------|
| **M1** | Безлимитный рост state: `RedisStorage` без `state_ttl`/`data_ttl`, не-FSM-ключи (onboard/chat-link/locale) без TTL, нет `BOT_STATE_TTL`. Медленный линейный рост + **deprecated State нельзя безопасно дочистить** (сессии не истекают никогда); доки обещают TTL, которого нет. | `tgbotkit/storage.py:14-18`, `start/gateway.py:23,25`, `extensions.py:55` | ✅ verified | KIT+TPL |
| **M2** | `nc.drain()` не дожидается детач-тасок `_handle_one` → `ack`/`nak` по закрытому соединению на shutdown. JetStream редоставит по `ack_wait`, но в связке с C2 (dedup-before-send) даёт пропуск эффекта. Контраст: `timerkit`/`outboxkit` свои таски `gather`'ят, `JsBus` — нет. | `natskit/jetstream.py:111`, `notifications/runner.py:33-34` | ✅ verified | KIT |
| **M3** | `ThrottleMiddleware`: режет фоновые notification-апдейты (ловит `event_from_user`), ключ без `bot_id` (cross-bot), `INCR` без гарантированного `EXPIRE` (вечный бан окна при отмене на shutdown). | `tgbotkit/middleware/throttle.py:26-31` | 🔁 multi-source | KIT |
| **M4** | `pydantic.mypy` подключён, но без `[tool.pydantic-mypy]` (`init_typed`/`init_forbid_extra`) → типы значений полей и лишние аргументы при конструировании моделей **не** проверяются. Самый частый класс ошибок (JSON→DTO, `_to_order`) проскакивает мимо mypy. Прогон подтвердил: фикс оставляет оба репо зелёными. | `pyproject.toml` (оба репо), `payments/gateway.py:40-47` | ◽ single-source | TPL+KIT |
| **M5** | **Тесты дают ложный зелёный ровно на критбагах.** `FakeDelivery` физически не умеет упасть → C2 проходит `make check`; `FakeRedis` игнорит TTL → дедуп-протухание непроверяемо; 0 integration-тестов при заявленном testcontainers-слое; глобальный error-handler (`AppErrorUX`) покрыт 36%, error-пути gateway — 0. | `tests/_fakes/delivery.py:13-17`, `tests/_fakes/redis.py:25`, `platform/dialogs/errors.py` (36%) | 🔁 multi-source | TPL+KIT |
| **M6** | PII-redact частичный (top-level `str`), off по умолчанию, нет `LOG_REDACT_ENABLED` в `.env.example` → вложенные dict/числа/`tg_id` уезжают в Loki. Контракт «фильтр PII» переобещан (это defence-in-depth, подан как граница). | `logkit/redact.py:42-46` | 🔁 multi-source | KIT |
| **M7** | `BackendClient._decode` зовёт `resp.json()` без guard на не-JSON 2xx (HTML от прокси/WAF → `JSONDecodeError` минует доменную классификацию → паника). `BackendConflict` (409) производится и тестируется, но **ни один gateway его не ловит** → всплывает как паника. | `platform/backend/client.py:60-64,67` | 🔁 multi-source | TPL |
| **M8** | Локальный бот (без бэкенда): выпиливание backend «всё-или-ничего», `/de-template` ведёт в падающий старт (dishka валидирует граф); `backend_user_id` вшит в общий тип `BotIdentity` (лишний Redis-резолв на апдейт + поле-фантом). | `app.py:34,41`, `platform/identity/identity.py:15`, `de-template/.../wiring.md:10` | ◽ single-source (s-no-backend) | TPL |
| **M9** | Тяжёлый wizard: шаблон-референс обрывается там, где wizard начинается — **ноль** образцов `dialog_data`-переноса между шагами, **ноль** динамических виджетов (Multiselect/ScrollingGroup/пагинация), нет образца условного ветвления. Гексагон при этом держится (сильная сторона). | `profile/state.py:16` (мёртв), grep по `src/` пуст | ◽ single-source (s-wizard) | TPL |
| **M10** | «Построено впрок, не обкатано»: `pylibinfra.config` (loader/vault), `flagkit`, sec-киты (`authnkit`/`bruteforcekit`/`auditkit`) — **0 потребителей** в шаблоне; повторяющийся мёртвый конфиг (`BOT_SHUTDOWN_DRAIN`, bruteforce `window`, `max_conn_lifetime`, `write_timeout`) — «есть, валидируется, ничего не делает». | `config/__init__.py`, `tgbotkit/config.py:47`, `bruteforcekit/config.py:11` | 🔁 multi-source | KIT |
| **M11** | Sec-киты (не используются ботом, но): bruteforce-`window` не реализован (счётчик неудач не сбрасывается по времени → ложные локи + иллюзия настройки); TOTP без `valid_window` (ложные «неверный код»); `auditkit` «append-only» без grant/триггер-защиты от тамперинга. | `bruteforcekit/pgstore/store.py:13`, `authnkit/totp.py:20`, `auditkit/` | 🔁 multi-source | KIT |
| **M12** | `start_dialog` в фоне локализуется лишь best-effort, а `Delivery.send_message` **не** локализован вовсе (текст уведомления захардкожен по-русски в `deliver.py:34`), хотя docstring заявляет «локаль закрыта в Delivery». en-юзер получит русский push. | `notifications/deliver.py:34`, `tgbotkit/notifications/delivery.py:46` | 🔁 multi-source | KIT+TPL |

---

## LOW / INFO — выборка (полный список в `audit/raw/*.md`)

| ID | Находка | Где | Статус | Чинить |
|----|---------|-----|--------|--------|
| **L1** | **Несколько HTTP-клиентов к разным API — «не из коробки», НО обходится тонким template-only паттерном (~15–25 строк).** dishka на двух провайдерах одного типа даёт silent last-wins; нужны `NewType`-маркеры (по образцу `pgkit.ReplicaPool`) + `Config(base_url=...)` напрямую (`populate_by_name=True`). **PR в kit НЕ требуется**; breaker изолирован per-`Client`, фикс. `BREAKER_NAME` блюрит только метрики (косметика). Это тревога заказчика №3 — **меньше, чем казалась.** | `httpclient/config.py:8,15`, `pgkit/module.py:16`, `platform/backend/provider.py:16` | ✅ verified (HIGH→LOW) | TPL |
| L2 | `BOT_SHUTDOWN_DRAIN` — мёртвый конфиг; polling не дренирует in-flight хендлеры на shutdown → апдейт застрявшего юзера теряется на деплое. | `tgbotkit/config.py:47`, `runner/polling.py` | 🔁 | KIT |
| L3 | `wiring.md:20` обещает «именованные клиенты», которых в коде нет; `backend-port.md` знает один бэкенд; `job.md` показывает несуществующий API `PeriodicJob`. | `de-template/references/*` | 🔁 | TPL(doc) |
| L4 | Cross-feature `profile→start` (`is_first_time`), `ProfileDialogData`, webapp `init_data`, `BackendConflict` — собраны и mypy-зелёные, но в рантайме **мертвы** (demo-scaffold без живого вызова). Потребитель скопирует паттерн без вызывающего. | `profile/usecase.py:37`, `profile/state.py:16` | 🔁 | TPL |
| L5 | Рантайм жёстко на один `Bot`/`Dispatcher`/токен — мультибот **в одном процессе** не выразим (модель «процесс=токен=деплой» разумна и k8s-нативна, но нигде не задекларирована). | `tgbotkit/module.py:78-81,88` | ◽ | KIT(doc) |
| L6 | mypy разъезжается по мажору: шаблон 1.20.2 vs kit 2.1.0 — зелёный в ките не гарантирует зелёный в шаблоне на общем API tgbotkit (на практике вывод идентичен, но дрейф на центральном инварианте). | `pyproject.toml:21` vs `pylibinfra/pyproject.toml:90` | 🔁 | TPL |
| L7 | i18n: нет нормализации региональных кодов (`pt-br`→`pt`) → новый язык молча падает в дефолт; неограниченный кэш `FluentLocalization` по недоверенному `language_code`. | `i18n/resolver.py:22-25`, `translator.py:27` | ◽ | KIT |
| L8 | `cachekit` tag-invalidation не атомарна (`set`+`sadd`+`expire` и `smembers`+`delete` без pipeline/Lua) → теряет ключи под гонкой. Ботом теги не используются. | `cachekit/cache.py:53-72` | ◽ | KIT |

---

## Сильные стороны (severity: info) — обязательная часть честной картины

| # | Что хорошо | Доказательство |
|---|-----------|----------------|
| S1 | **Тулчейн зелёный в обоих репо**, гигиена образцовая: `make check` EXIT 0, покрытие **84%** (шаблон) / **83%** (kit), **0** `type:ignore`/`cast`/`noqa`/`print`/`TODO` в `src/bot`; 13 узких обоснованных `type:ignore` в ките. | `_toolchain.md` |
| S2 | **Гексагон — настоящий, не косметика.** Все 3 контракта import-linter `KEPT`; чистое ядро без инфры, cross-feature однонаправленно через `adapters/provider`, getter/handler-split — всё на машинном enforce. | `d-arch.md`, `t-feat-start-profile.md` |
| S3 | **Рантайм-ядро tgbotkit — самая сильная часть.** Чистая абстракция runner (polling/webhook расходятся только в `_serve`), корректный deferred-wiring (`setup_dialogs` строго последним — главная грабля aiogram_dialog отработана), `RedisEventIsolation` для мультиворкера, graceful-shutdown по сигналам. | `k-tgbot-runtime.md` |
| S4 | **Типы не врут.** mypy strict настоящий, Protocol-порты эмпирически ловят расхождения (включая границу kit↔шаблон), `Any` дисциплинирован (на transport-границах, 0 в ядре). | `d-types.md` |
| S5 | **Самые опасные security-места закрыты правильно.** HMAC initData (constant-time, верный data-check-string, TTL), сверка цены платежа на бэкенде в `pre_checkout` (подмена суммы/валюты не проходит), fail-closed precheckout/webhook-guard, secret-token вебхука, нет SQL-инъекций, чистый bandit (`ruff S`). | `d-security.md`, `k-tgbot-feat.md` |
| S6 | **httpclient качественный:** retry+backoff+jitter, breaker оборачивает retry-цепочку, корректное 4xx-vs-5xx, span-на-запрос, breaker изолирован per-`Client`. `httpkit` (1346 LOC) — НЕ дубль, чистая граница inbound/outbound. | `p-http.md` |
| S7 | **Гибкость правильной формы на 5 из 6 путей роста** без правки kit: добавить фичу/диалог/окно, сменить runner polling↔webhook (одна env), добавить язык, выключить reference-фичу. Локальный бот (без бэкенда) — первоклассный. | `d-flex.md`, `s-no-backend.md` |
| S8 | Observability production-grade (структурный JSON-лог с trace-correlation, OTLP→Loki, RED-метрики). testkit крепкий для диалог-флоу, `JsonMemoryStorage` — честный JSON-паритет с прод-Redis. | `p-obs.md`, `p-testkit.md` |

---

## Сквозные темы (корни, через которые проходят находки)

1. **«mark-before-commit + проглатывание ошибки»** — единый анти-паттерн в дедуп-примитивах (`seen()`/`guard_charge`) + `Delivery`, глотающий ошибку. **Один корень → C2 + H1.** Лечится введением `reserve(short_ttl)→commit(long_ttl)` и пробросом ошибки доставки наверх (→ `nak`). Один PR в tgbotkit закрывает обе бизнес-потери.
2. **Сеть восстановления дырявая ровно в момент сбоя** — порядок Recovery↔`dp.errors` (C1), отсутствие fail-open на Redis/NATS (H7), отсутствие rate-limit/retry на доставке (H2). Почти все потери **тихие** (невидимы в телеметрии: нет метрики успешной выдачи, нет логов промаха доставки).
3. **«Построено впрок, не обкатано»** — config-пакет/flagkit/sec-киты без потребителей + повторяющийся мёртвый конфиг (M10). «Безопасный» параметр выглядит настроенным, защиты нет.
4. **Фоновый путь системно слабее основного** — идёт мимо middleware: нет локали (M12), error-handler'а, observability, тестируемости (M5). Точки расширения kit под фон недостаточны.
5. **Тонкость шаблона как reference обрывается на сложном** — wizard (M9), мульти-API (L1), payments-adv (H6): простой happy-path показан образцово, требовательный сценарий потребитель проектирует сам по доке библиотеки.
