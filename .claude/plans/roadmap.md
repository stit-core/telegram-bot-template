# Roadmap

Единственный артефакт планирования проекта — этот файл. Подпапок, `<slug>.md`, архивов и
changelog'ов нет: они расходятся с правдой и мешают.

**Planning-first.** Изменение идёт через план — секцию в `## Active` ниже. Прямая правка без
плана допустима только для truly-atomic (опечатка, один очевидный файл) и багфиксов (→ skill
`/triage-failure`, RED-first). Отклонение от плана — осознанное и проговаривается с юзером.

**Жизненный цикл.** `planning → in-progress → blocked? → done`. По `done` секция задачи удаляется
целиком — история остаётся в `git log`. Незакрытый follow-up переезжает в `## Backlog` или новой
Active-секцией, а не хвостом в удаляемой.

**Gate.** Перед claim «готово»/push — `make check` зелёный (ruff format/check + import-linter +
mypy + pytest). См. `.claude/CLAUDE.md`.

**Current focus:** Фазы 0–2 и 4 закрыты. В работе — Фаза 3 (расширяемость) целиком: 3.1/3.2/3.3/3.5
(3.4 мульти-бот исключён). Секция ниже. Шаблон перепинится на новый kit-rev в кластере P.

## Active

### phase3-extensibility

Reference-паттерны Фазы 3 как образцы. Дизайн-решения (зафиксированы с юзером): wizard = «заказ/брони»
(`booking`) с submit через backend-gateway порт; payments-adv = полный демо-срез; 3.1 включает опц.
kit-PR breaker_name.

**Порядок (kit-first → перепин → template-кластеры, каждый отдельным коммит+push с подтверждением):**

**Кластер K (KIT `pylibinfra`)** — один push, затем перепин:
- 3.3-kit `tgbotkit/payments`: `Money(amount_minor, currency)` value-тип; `build_invoice` —
  доп. `prices: Sequence[LabeledPrice]` + `max_tip_amount`/`suggested_tip_amounts` (XTR ⇒ без
  tips/токена), back-compat со старой сигнатурой; `build_subscription_link(bot, …, price, period)`
  (`create_invoice_link(subscription_period=…)`); `refund_charge(bot, user_id, charge_id)` +
  `RefundGuard` (дедуп `refunded_payment` по charge_id, ключ `tg:refund:`); метрики
  `tg_payments_total{stage=refund|refunded,…}`. Экспорт в `payments/__init__` + `tgbotkit/__init__`.
- 3.1-kit `httpclient`: `Config.breaker_name` (env `HTTPCLIENT_BREAKER_NAME`, дефолт `httpclient`),
  проброс в `get_breaker(name)` + label метрик. Back-compat.
- Гейт: `ruff format --check && ruff check && mypy src && pytest -q`. Коммиты: `feat(tgbotkit)…`,
  `feat(httpclient)…`. Push (подтвердить).

**Кластер P (TPL payments-adv 3.3)** — перепин + полный демо:
- `pyproject.toml [tool.uv.sources]` rev → новый kit HEAD; `uv lock`.
- `Order` DTO: `price: Money`; обновить views/getters/gateway/handlers/dialogs. Кнопка подписки
  (`build_subscription_link`) в окне оффера. Dispatcher-хендлер `refunded_payment` (RefundGuard +
  `uc.reverse` → `gateway.revoke` идемпотентно). charge→user реестр в cache при fulfill. Admin
  `/refund <charge_id>` → `refund_charge`. `.ftl` ru/en, `command_specs`, `extensions.commands`, тесты.
- Гейт `make check`. Коммит+push (подтвердить).

**Кластер W (TPL wizard 3.2)** — новая фича `features/booking/`:
- Полный гексагон: `state.py` (Draft pydantic + re-export `Booking` SG), dto/errors/policy/ports/
  gateway/usecase/views/getters/handlers/dialogs/provider/__init__. Окна: SERVICES (Multiselect+
  `get_checked`), DETAILS (TextInput `type_factory=int`, policy-валидация диапазона), ADDRESS
  (условное окно — `policy.needs_address(services)` → switch_to из handler), CONFIRM (getter рисует
  черновик, submit → `gateway.submit(idempotency_key=draft_id)`). `draft_id` = `uuid4().hex` в on_start.
- `states.py` +`Booking`; `extensions.routers` + кнопка в start-меню; `booking.ftl` ru/en +
  `config._I18N_RESOURCES`; `app.py` provider; тесты (flow + policy + serialization).
- `rule storage-serialization`: добавить конвенцию «черновик wizard'а» (накопление dialog_data между
  шагами, `model_dump(mode="json")`, submit на финале — не доменная сущность).
- Гейт `make check`. Коммит+push (подтвердить).

**Кластер D (TPL doc+identity: 3.1-doc + 3.5)**:
- 3.1-doc `scaffold/references/backend-port.md`: секция «несколько именованных бэкендов» (NewType-
  маркеры + провайдер-фабрика по образцу `pgkit.ReplicaPool`, breaker_name на клиент). Код-образец.
- 3.5 local-only: ветка в `de-template` (`prune.md` чеклист удаления backend-слоя + `backend_user_id`
  из BotIdentity/IdentityProvider; «Что НЕ удалять» → backend условный), `wiring.md:10` точнее,
  `SKILL.md` упоминание. Forward-комментарий в `identity.py` (поле выносимо для local-only).
- Гейт `make check`. Коммит(ы)+push (подтвердить).

**Инварианты:** import-linter 3 контракта KEPT (ядро pure, фичи независимы, слоистость); mypy strict;
forward-only доки; логи через logkit; новая инфра-механика — в kit, не полукалека.

**INFRA-HANDOFF (в release-backlog при закрытии):** новые env `HTTPCLIENT_BREAKER_NAME`; payments-adv
требует включённых Stars-subscriptions/refunds у бота (BotFather) — не env, но deploy-замечание.

## Backlog

- **Метрика успешной выдачи** `payments_total{stage=paid,result=ok}` + лог промаха доставки —
  чтобы регрессии путей платежей/уведомлений перестали быть невидимыми (хвост Фазы 0).
- `.env.example` шаблона: `LOG_REDACT_ENABLED` (хвост 1.7); опц. провязать `OptionalConn`, чтобы
  health-probe в polling проверял и NATS.
- INFRA-HANDOFF Фазы 1 (при релизе/деплое): polling биндит health-порт (`HTTP_*`), новые env-ручки
  (`NATS_JS_MAX_DELIVER/BACKOFF/FLOW_CONTROL/IDLE_HEARTBEAT/DLQ_ENABLED`, `NATS_MAX_RECONNECTS=-1`,
  `BOT_FLOOD_ENABLED`, `BOT_RATE_GLOBAL`, `BOT_RATE_PER_CHAT`, `BOT_RETRY_AFTER_ATTEMPTS`), DLQ-сабжект
  `dlq.<subject>`. Опц. Фазы 2: `BOT_STATE_TTL` (TTL FSM-стейта, дефолт 0=вечно). Передать
  инфра-админу через `/release` handoff.
- Свапнуть пин `pylibinfra` с коммита `2f3260a` на release-тег `vX.Y.Z`, когда `pylibinfra`
  будет тегнут на ревизии с `tgbotkit` (`pyproject.toml` → `[tool.uv.sources]`). Кит ушёл вперёд
  на `0b43de8` (Фаза 4 sec-гигиена authnkit/auditkit — бот эти киты не использует, перепин не нужен).
