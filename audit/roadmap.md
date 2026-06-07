# Роадмап по итогам аудита

Приоритизированный план: что чинить и в каком порядке. Источник — [`findings.md`](findings.md)
(ID находок в скобках). Метки: **KIT** = PR в `pylibinfra/tgbotkit` через `/infra-handoff`;
**TPL** = правка шаблона (через `/plan`); **S/M/L** = объём (часы / день-два / неделя+).

> **Дисциплина проекта**: инфра-механика (middleware, runner, дедуп-примитивы, доставка, rate-limit)
> — это **PR в `pylibinfra/tgbotkit`**, не полукалека в шаблоне (`tgbotkit-boundary`). Большинство
> блокеров — именно kit-сторона. Правки шаблона веди через `/plan`, kit-поверхность — через `/infra-handoff`.

---

## Кратчайший путь к доверенному прод-боту

Если нужен **один** ориентир: **Фаза 0 закрывает всё, что молча теряет деньги и сообщения.** До неё
не запускай прод-бот с платежами или фоновыми уведомлениями. Без платежей/уведомлений (простой
command→dialog→backend бот) — можно в прод уже сейчас, закрыв C1 (recovery) + H3 (секреты) из Фазы 0/1.

---

## Фаза 0 — Блокеры прода: доставка, деньги, recovery `[критично]`

Цель: убрать **тихие потери**. Три находки, но **два PR** (C2 и H1 — один корень).

| # | Что сделать | Закрывает | Где | Объём |
|---|-------------|-----------|-----|-------|
| 0.1 | **Reserve/commit вместо mark-before-commit.** Заменить `dedup.seen()`/`guard_charge` (ставят ключ ДО действия) на `reserve(short_ttl)` → действие → `commit(long_ttl)`. `Delivery.send_message` — **не глотать** ошибку: пробрасывать/возвращать признак, транзиентные → `nak(delay)`, `commit` только после успешной отправки. **Один PR закрывает обе бизнес-потери.** | **C2** (потеря уведомлений) + **H1** (потеря выдачи платежа) | KIT | M |
| 0.2 | **Порядок recovery.** В `RecoveryMiddleware` пропускать `UnknownIntent`/`OutdatedIntent`/`UnknownState` наверх (`raise`) к `dp.errors` — чтобы и кастомный stale-UX, и штатный stack-recovery aiogram_dialog ожили. | **C1** | KIT | S |
| 0.3 | **Тесты, которые ловят 0.1/0.2.** Дать `FakeDelivery` режим инъекции сбоя (`fail_on`); RED-golden на потерю push; flow-тест `UnknownIntent → AppErrorUX`. Иначе фикс не застрахован (сейчас фейк физически не умеет упасть). | **M5** (частично) | TPL+KIT | M |
| 0.4 | Поймать `BackendConflict` (409) в мутирующих gateway (для идемпотентного повтора — это «выполнено», не паника); guard `resp.json()` на не-JSON 2xx. | **M7** | TPL | S |

**После Фазы 0**: добавить метрику успешной выдачи (`payments_total{stage=paid,result=ok}`) и логи промаха
доставки — иначе будущие регрессии этих путей снова будут невидимы (часть темы «тихие потери»).

---

## Фаза 1 — Надёжность под нагрузкой и на сбоях `[высокий]`

Цель: бот переживает burst-трафик, разрыв Redis/NATS и деплой без потерь и без «немоты».

| # | Что сделать | Закрывает | Где | Объём |
|---|-------------|-----------|-----|-------|
| 1.1 | **Rate-governor на исходящем пути доставки** (token-bucket в Redis: 30 msg/s global + 1 msg/s/chat) + honor `TelegramRetryAfter` (sleep+retry). | **H2**, **H5** (часть) | KIT | M |
| 1.2 | **JetStream failure-path**: `max_deliver` + `nak(delay=backoff)` + `term()`/DLQ-subject; `flow_control=True` + `idle_heartbeat`. | **H8**, **H5** | KIT | M |
| 1.3 | **Реальный drain**: `JsBus.drain()` = `unsubscribe` → `await gather(_tasks)` → `nc.drain()`, вызвать из `NotificationRunner.drain` до `container.close`. Заодно polling-drain in-flight хендлеров (оживить `BOT_SHUTDOWN_DRAIN`). | **M2**, **L2** | KIT | M |
| 1.4 | **Толерантность к инфре**: fail-open в `DedupMiddleware` на ошибке Redis; nats reconnect-callbacks (`max_reconnects=-1` для consumer) + переустановка JS-подписок; health-эндпоинт в polling-режиме (redis/nats probe). | **H7** | KIT | M |
| 1.5 | **Ordering для realtime**: per-chat single-flight для подписок, где порядок важен (статусы одному чату). | **H5** | KIT | M |
| 1.6 | **Секреты → `SecretStr`** (token/webhook_secret/VAULT_TOKEN), `.get_secret_value()` на использовании; в `config.load()` ловить `ValidationError` без `input_value`. | **H3** | KIT | S |
| 1.7 | PII-redact: рекурсия по dict/list + приведение не-строк; `LOG_REDACT_ENABLED` в `.env.example`; в доке честно «redact ≠ дисциплина не-логировать PII». | **M6** | KIT | S |
| 1.8 | `ThrottleMiddleware`: не троттлить фон (`update_id==0`/aiogd), скоупить `bot_id`, атомарный `INCR+EXPIRE NX` (Lua/pipeline). | **M3** | KIT | S |

---

## Фаза 2 — Сеть качества и корректности `[средний]`

Цель: убрать «ложный зелёный» гейта и тихие конфиг-ловушки; чинить медленные/латентные риски.

| # | Что сделать | Закрывает | Где | Объём |
|---|-------------|-----------|-----|-------|
| 2.1 | **Integration-слой**: 2–3 теста на боевом redis/nats-контейнере (DeliveryDedup TTL, guard TTL, JetStream `nak`→redelivery, «глоток→golden на потерю»). Сейчас 0 integration при заявленном testcontainers. | **M5** | TPL+KIT | M |
| 2.2 | Дотестировать error-пути: gateway-маппинг (`backend.get_error`), глобальный `AppErrorUX` (36%→), `payments/handlers` (47%→). | **M5** | TPL | M |
| 2.3 | `[tool.pydantic-mypy]` с `init_typed=true`+`init_forbid_extra=true` (прогон подтвердил: оба репо остаются зелёными). Ловит класс JSON→DTO-ошибок. | **M4** | TPL+KIT | S |
| 2.4 | **TTL на state**: пробросить `state_ttl`/`data_ttl` из `BOT_STATE_TTL` (KIT) + вызывать `cache.set(..., ttl=)` для onboard/chat-link/locale (TPL). Чинит и невозможность дочистки deprecated State. | **M1** | KIT+TPL | S |
| 2.5 | **Вычистить мёртвый конфиг** (forward-only: реализовать ИЛИ удалить поле+docstring): `BOT_SHUTDOWN_DRAIN` (оживлён в 1.3), `write_timeout`, `max_conn_lifetime`, bruteforce `window`. | **M10**, **L2** | KIT | S |
| 2.6 | Локаль фоновых уведомлений: locale-канал в `Delivery` + ключ `notifications-*` в `.ftl`; убрать ложное «локаль закрыта» из доки. | **M12** | KIT+TPL | S |
| 2.7 | Согласовать мажор mypy между репо (шаблон → `>=2.1,<3`), перелочить. Свапнуть `rev=` pylibinfra на release-тег. | **L6** | TPL | S |

---

## Фаза 3 — Расширяемость для требовательных сценариев `[средний, по потребности]`

Цель: превратить «непротянутые паттерны» в образцы. **Делать по мере того, как сценарий реально нужен.**

| # | Что сделать | Закрывает | Где | Объём |
|---|-------------|-----------|-----|-------|
| 3.1 | **Несколько API-клиентов** (твоя тревога №3): reference-паттерн именованных бэкендов — `NewType`-маркеры (`CrmClient`/`LlmClient`…) + провайдер-фабрика по образцу `pgkit.ReplicaPool`; задокументировать в `backend-port.md`. Опц. kit-PR: `breaker_name`/env-префикс ради per-API метрик. **Малый объём — паттерн уже есть в репо.** | **L1** | TPL (+опц. KIT) | S |
| 3.2 | **Reference-wizard** (3–4 окна) как образец: живой `dialog_data` между шагами, `Multiselect`+`find().get_checked()`, валидируемый `TextInput`, условный `switch_to` из policy, финальный submit. Конвенция «черновик wizard'а» в `storage-serialization`. | **M9** | TPL | M |
| 3.3 | **Payments-adv в kit**: `build_subscription_link` (`create_invoice_link(subscription_period)`); `build_invoice` с `prices:list`+`max_tip`+типом валюты (минорные единицы); `refund_charge`-обёртка + guard для `refunded_payment`; `Money(amount_minor,currency)` в DTO. | **H6** | KIT+TPL | L |
| 3.4 | **Мультитенант — решение** (одно из двух): либо задокументировать инвариант «процесс=токен=деплой, общий Redis между тенантами не поддержан» и **снять ложный сигнал** из `storage.py` docstring; либо (если нужен мультибот в процессе) сквозной `bot_id`-namespace на ВЕСЬ Redis-стейт + фабрика ботов + роутинг по `bot.id`. | **H4**, **L5** | KIT(+TPL) | S или L |
| 3.5 | **Local-only бот**: ветка в `/de-template` (чеклист удаления backend-слоя), исправить `wiring.md:10`/`prune.md`; `backend_user_id` опциональным/выносимым из `BotIdentity`. | **M8** | TPL | S |

---

## Фаза 4 — Гигиена и догон `[низкий]`

| # | Что сделать | Закрывает | Где |
|---|-------------|-----------|-----|
| 4.1 | Sec-киты (если будут активированы): реализовать/удалить bruteforce `window`; TOTP `valid_window=1`; auditkit append-only через grant/триггер. | **M11** | KIT |
| 4.2 | Пометить demo-only код под прун (`is_first_time`, `ProfileDialogData`, webapp `init_data`) — чтобы потребитель не скопировал паттерн без живого вызывающего. | **L4** | TPL |
| 4.3 | i18n: нормализация региональных кодов (`pt-br`→`pt`), ограничить кэш `FluentLocalization` known-locales. | **L7** | KIT |
| 4.4 | cachekit tag-invalidation атомарной (pipeline/Lua); прочие low/info из `raw/*.md`. | **L8** | KIT |
| 4.5 | Привести docstring/skill-доку к коду (`job.md` API, `resolver.py` ключ, wiring.md именованные клиенты). | **L3** | TPL(doc) |

---

## Вне скоупа аудита (твоя зона)

- **Восстановить `docs/` и `design/`** — снесены намеренно. Для тебя (не-питониста) это **самый важный
  DX-шаг**: всё ядро (`CLAUDE.md`/README/rules/skills) маршрутизирует в `docs/` как в source-of-truth.
  До восстановления кривая входа ведёт в пустоту. (Аудит это как находку не считает — по твоей установке.)

---

## Как заводить в работу

- **Kit-пункты** (большинство Фаз 0–1) → `/infra-handoff` → PR в `pylibinfra/tgbotkit`. Корневой PR
  «reserve/commit + не глотать ошибку доставки» (0.1) — самый ценный: закрывает оба CRITICAL-класса.
- **Template-пункты** → `/plan` (секция в `.claude/plans/roadmap.md`), RED-first для багфиксов через
  `/triage-failure`.
- **Порядок**: 0 → 1 обязательны до прода с платежами/уведомлениями. 2 — параллельно/следом. 3 — по
  мере появления требовательного сценария. 4 — фоном.

Скажи, что заводим первым — могу развернуть любой пункт в конкретный план (`/plan`) или INFRA-HANDOFF
(`/infra-handoff`) с пофайловыми правками.
