# 16 · Reference-фичи «Платежи (incl. Telegram Stars/XTR)» и «WebApp / Mini App» — анатомия, ports/adapters, идемпотентность

> **Зачем.** Архитектор решил, что **платежи** (фиат + Telegram Stars/XTR) и **WebApp/Mini App**
> идут в скелет «из коробки» как reference-фичи — наравне с `start`/`profile` (14 §6). Этот
> артефакт вписывает их в **каноническую анатомию фичи** (14 §2:
> `state·dto·errors·policy·ports·usecase·gateway·dialogs·getters·handlers·views·provider·adapters`)
> и в схему **бот = «фронтенд»**: бизнес-решение (есть ли товар, какая цена, провести/вернуть
> заказ) — на **бэкенде** через `BackendGateway`-порт; бот валидирует, оркеструет и **отвечает
> Telegram в дедлайны**.
>
> **Источники-якоря:** `design/_research/08` (каталог ситуаций — категория 6 «Платежи/Stars/refund»
> строки 137-149, категория 7 «WebApp/initData» 153-166), `09` (gateway/identity §1-2,
> идемпотентность §3, webhook-in §7), `14` (анатомия фичи §2, ports/adapters §3, composition root
> §4, enforcement §5), `04` (httpkit §8 — FastAPI bootstrap для WebApp-эндпоинта),
> `06` (dishka↔aiogram DI). Внешние (сверено ~июнь 2026):
> - Telegram Stars / pre_checkout / refund — [core.telegram.org/bots/payments-stars](https://core.telegram.org/bots/payments-stars),
>   aiogram `examples/stars_invoice.py` ([dev-3.x](https://github.com/aiogram/aiogram/blob/dev-3.x/examples/stars_invoice.py)),
>   [`refundStarPayment`](https://docs.aiogram.dev/en/latest/api/methods/refund_star_payment.html),
>   [`sendInvoice`](https://docs.aiogram.dev/en/latest/api/methods/send_invoice.html),
>   [`PreCheckoutQuery`](https://docs.aiogram.dev/en/latest/api/types/pre_checkout_query.html).
> - initData validation — [core.telegram.org/bots/webapps](https://core.telegram.org/bots/webapps),
>   [docs.telegram-mini-apps.com — Validating](https://docs.telegram-mini-apps.com/packages/tma-js-init-data-node/validating).

---

## 0. Ключевые решения (TL;DR)

> **ГЛАВНОЕ (директива архитектора).** Вся **generic-механика** платежей/WebApp (aiogram-specific,
> но НЕ product-specific) уходит в **bot-infra kit** (`tgkit` — новый кит pylibinfra, aiogram как
> опциональная extra; проектирует зона 18). В **шаблоне** — **только бизнес**: что продаём, цены,
> конкретные диалоги. Граница ниже оформлена как **поверхность kit'а** (§4): четыре платёжных
> примитива (`payments` extension-points, `answer_pre_checkout` timeout-guard, dedup платёжных
> апдейтов, метрики `tg_payments_*`) + валидатор initData (vendor-Telegram pure-сервис). Сводная
> таблица «механизм → generic(kit)/business(шаблон) → поверхность» — **§4.1**.

1. **`pre_checkout_query` и `successful_payment` — это апдейты ДИСПЕТЧЕРА, не dialog-callback.**
   Они приходят как `Update.pre_checkout_query` и `Message.successful_payment`, **вне стека
   диалога** aiogram_dialog. Поэтому их хендлеры живут на **dispatcher-level роутере фичи**
   (`payments/handlers.py` → `payments_router`, регистрируется в `build_dispatcher` ПЕРЕД
   `setup_dialogs`), а не в `Window`. Связь с диалогом покупки — через **`invoice_payload`**
   (кладём туда `order_id`/корреляцию) + опц. фоновый `BgManager.bg(...)` для досыла сообщения
   в активный диалог.

2. **10-секундный дедлайн pre_checkout — жёсткий SLA.** `answer_pre_checkout_query(ok=...)`
   обязан уйти **≤ 10 с** после апдейта, иначе Telegram отменяет платёж (08:143, подтверждено
   [PreCheckoutQuery docs](https://docs.aiogram.dev/en/latest/api/types/pre_checkout_query.html)).
   Внутри этих 10 с — **один** быстрый gateway-вызов «проверь наличие/цену» с **жёстким
   таймаутом** (≈3-4 с) и **fail-closed** (`ok=False` при недоступности бэкенда). Никакого
   «проведём заказ» здесь — только подтверждение готовности.

3. **Не доверять клиенту: сумму и товар брать с бэкенда, проводить заказ идемпотентно.**
   `callback_data`/`web_app_data` приходят от клиента и **подделываемы** — цена и состав заказа
   резолвятся на бэкенде по `order_id`/`item_id`. Проведение оплаты (`successful_payment`)
   **at-least-once** (08:144,148) → дедуп по `telegram_payment_charge_id` (Cache-маркер на боте
   + `Idempotency-Key` на бэкенде, 09 §3). `initData` доверяем **только** после проверки HMAC.

---

## 1. Reference-фича `payments/` — полный флоу

### 1.1. Флоу-диаграмма платежа (фиат и Stars/XTR)

```
                         ┌─────────────────────────── ДИАЛОГ ПОКУПКИ (aiogram_dialog) ──────────────────────────┐
 user                    │  Payment.CATALOG → Payment.CONFIRM                                                    │
  │   /buy               │   getter: каталог из бэкенда (цены — с бэкенда, НЕ из кода бота)                      │
  │ ───────────────────► │   on_click «Купить» (handlers.py, dialog-level)                                      │
  │                      │     └─► usecase.start_purchase(identity, item_id)                                    │
  │                      │           ├─ policy.can_buy(role, item)         (pure)                               │
  │                      │           ├─ gateway.create_order(item_id) ──────────────► BACKEND  POST /orders     │
  │                      │           │     (бэкенд резолвит ЦЕНУ и состав; возвращает order_id + amount + label) │
  │                      │           └─ bot.send_invoice(currency, prices=[amount], payload=order_id) ──► TG    │
  └──────────────────────┴──────────────────────────────────────────────────────────────────────────────────┘
                                    invoice_payload = order_id   ◄── единственная нить связи диалога ↔ апдейтов

  TG показывает инвойс ──► user жмёт «Оплатить»
       │
       ▼  Update.pre_checkout_query        ⏱ ДЕДЛАЙН 10 с — DISPATCHER-LEVEL handler (НЕ диалог)
  ┌──────────────────────────────────────────────────────────────────────────────────────────┐
  │ payments/handlers.py :: on_pre_checkout  @router.pre_checkout_query(F.invoice_payload...)  │
  │   order_id = q.invoice_payload                                                             │
  │   decision = usecase.precheck(order_id, q.total_amount, q.currency)  ← быстрый, жёсткий t/o │
  │      ├─ gateway.get_order(order_id) → проверка: существует? цена/валюта совпадают? в стоке? │
  │      └─ policy.precheck_ok(order, q.total_amount, q.currency)   (pure: сверка сумм)         │
  │   await q.answer(ok=True)            ◄── ≤10с; при сомнении/недоступности → ok=False        │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼  Message.successful_payment      AT-LEAST-ONCE — DISPATCHER-LEVEL handler (НЕ диалог)
  ┌──────────────────────────────────────────────────────────────────────────────────────────┐
  │ payments/handlers.py :: on_successful_payment   @router.message(F.successful_payment)      │
  │   sp = message.successful_payment                                                          │
  │   usecase.confirm(identity, order_id=sp.invoice_payload,                                   │
  │                   charge_id=sp.telegram_payment_charge_id,           ← ключ идемпотентности │
  │                   provider_charge_id=sp.provider_payment_charge_id,                         │
  │                   amount=sp.total_amount, currency=sp.currency)                             │
  │      ├─ dedup-маркер Cache  paid:<charge_id>   (ранний short-circuit, 09 §3)               │
  │      └─ gateway.confirm_payment(...)  Idempotency-Key=charge_id ──► BACKEND POST /payments  │
  │   await message.answer("Оплата прошла ✅")   (+ опц. bg.update в диалог)                     │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼  (опц.) refund — по команде саппорта/правилу
  ┌──────────────────────────────────────────────────────────────────────────────────────────┐
  │ usecase.refund(identity, charge_id)                                                        │
  │   ├─ gateway.authorize_refund(order_id)  ──► BACKEND  (можно ли возвращать? политика)       │
  │   └─ bot.refund_star_payment(user_id, telegram_payment_charge_id=charge_id)  ──► TG         │
  │   (idem по charge_id — Telegram refund идемпотентен по charge_id, 08:145)                   │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
```

**Где живут pre_checkout / successful_payment и как увязаны с диалогом покупки.**
Это **узловой вопрос**. aiogram_dialog оркеструет только `message`/`callback_query`, попавшие в
стек активного диалога; `pre_checkout_query` и `successful_payment` приходят **диспетчеру
напрямую** и стек диалога не трогают. Решение шаблона:

- Хендлеры обоих апдейтов — на **`payments_router` (обычный `aiogram.Router`)**, который
  `include_router` в диспетчер **до** `setup_dialogs` (14 §4: «команды-входы» / не-диалоговые
  хендлеры регистрируются раньше; `setup_dialogs` — строго последним).
- **Корреляция диалог ↔ апдейт — через `invoice_payload = order_id`.** Диалог при «Купить»
  создаёт заказ на бэкенде, кладёт `order_id` в `payload` инвойса. Оба апдейта несут его обратно
  (`pre_checkout_query.invoice_payload`, `successful_payment.invoice_payload`) — этого достаточно,
  чтобы резолвить заказ на бэкенде без знания про стек диалога.
- **Обратная связь в активный диалог** (опц.): после `confirm` дослать сообщение/обновить окно
  через `BgManager` (06 docs, `bg_factory` лежит в `dp["bg_factory"]`, 14 §4) — `bg.update(...)`
  по `(chat_id, user_id, stack)`. Если пользователь уже вышел из диалога — просто `message.answer`.
  **Не** обязательно: подтверждение оплаты самоценно и без диалога.

### 1.2. Раскладка файлов фичи `payments/` (зеркало 14 §2)

```
src/bot/features/payments/
├── __init__.py
├── state.py        # StatesGroup Payment (re-export из platform/dialogs/states.py); PaymentDialogData
│                   #   (item_id, draft order_id) — JSON-safe; pure-метод is_ready()
├── dto.py          # CatalogItem, OrderDraft(order_id, amount:int, currency, label),
│                   #   PrecheckOutcome, ConfirmResult, RefundResult — ЛОКАЛЬНЫЕ anti-corruption DTO
├── errors.py       # OrderNotFound, PriceMismatch, OutOfStock, AlreadyRefunded, PaymentForbidden
│                   #   (наследуют shared FeatureError)
├── policy.py       # PURE: can_buy(role,item)->Decision; precheck_ok(order, amount, currency)->Decision
│                   #   (СВЕРКА СУММ — критично, см. §3); can_refund(order, role)->Decision
├── ports.py        # Protocol BillingGateway (узкий): create_order / get_order / confirm_payment /
│                   #   authorize_refund. Опц. cross-feature OnboardingReader. Владелец — payments.
├── usecase.py      # ОРКЕСТРАЦИЯ: start_purchase / precheck / confirm / refund. Знает только Protocol'ы.
│                   #   Дедуп-маркер (cachekit.IdempotencyStore) тут. OTel-span + bizmetric.
├── gateway.py      # HttpBillingGateway над platform/backend/BackendHttpClient → DTO. Idempotency-Key.
├── dialogs.py      # Dialog(Window CATALOG, Window CONFIRM). on_click «Купить» → handlers.on_buy.
├── getters.py      # catalog_getter: usecase.catalog(identity) → dict для Select/виджетов
├── handlers.py     # ⚠ ДВА СОРТА:
│                   #   (a) DIALOG-level: on_buy(event,widget,manager,...) — кнопка «Купить»
│                   #   (b) DISPATCHER-level: on_pre_checkout(query,...), on_successful_payment(msg,...)
│                   #       + payments_router: Router с .pre_checkout_query()/.message(F.successful_payment)
├── views.py        # маппинг OrderDraft→окно; sentinel-ошибки → user-facing текст (mapErr)
├── provider.py     # dishka Provider: BillingGateway→gateway; usecase; экспорт payments_router + dialog
└── adapters.py     # (опц.) cross-feature anti-corruption
```

> **Отклонение от чистого 14 §2:** `handlers.py` содержит **и** dialog-level, **и** dispatcher-level
> хендлеры. Это осознанно: оба «реагируют на ввод» (SRP-смысл `handlers.py` сохранён), просто
> диспетчерские не привязаны к `Window`. Альтернатива — отдельный `update_handlers.py`; шаблон
> кладёт в один файл с явными секциями-комментариями `# --- dialog-level ---` / `# --- dispatcher-level ---`.
> `provider.py` экспортирует **два** объекта роутинга: `payments_router` (для `include_router` до
> `setup_dialogs`) и `payment_dialog` (в `registry.py`, как у `profile`).

### 1.3. Ports / DTO фичи `payments/`

```python
# src/bot/features/payments/dto.py — ЛОКАЛЬНЫЕ DTO (не схемы бэкенда)
from pydantic import BaseModel

class CatalogItem(BaseModel):
    item_id: str
    title: str
    amount: int          # минимальные единицы (для XTR — целое число Stars), С БЭКЕНДА
    currency: str        # "XTR" | "USD" | ...
    label: str

class OrderDraft(BaseModel):
    order_id: str        # резолвится бэкендом → идёт в invoice_payload
    amount: int          # ИСТОЧНИК ИСТИНЫ — бэкенд, не код бота, не callback
    currency: str
    label: str

class PrecheckOutcome(BaseModel):
    ok: bool
    error_message: str | None = None   # уходит в answer(ok=False, error_message=...)

class ConfirmResult(BaseModel):
    order_id: str
    already_confirmed: bool            # True если дедуп сработал (повторный апдейт)

class RefundResult(BaseModel):
    charge_id: str
    refunded: bool
```

```python
# src/bot/features/payments/ports.py — УЗКИЙ порт (ISP), владелец = payments
from typing import Protocol
from bot.features.payments.dto import CatalogItem, OrderDraft, PrecheckOutcome, ConfirmResult

class BillingGateway(Protocol):
    """Порт к биллингу бэкенда. Сужен до сценария покупки/возврата."""
    async def catalog(self, backend_user_id: str) -> list[CatalogItem]: ...
    async def create_order(self, backend_user_id: str, item_id: str) -> OrderDraft: ...
    async def get_order(self, order_id: str) -> OrderDraft: ...          # для precheck: цена/стат
    async def confirm_payment(                                          # ИДЕМПОТЕНТНО (Idempotency-Key)
        self, order_id: str, charge_id: str,
        provider_charge_id: str | None, amount: int, currency: str,
    ) -> ConfirmResult: ...
    async def authorize_refund(self, order_id: str) -> bool: ...        # политика возврата на бэкенде
```

### 1.4. Код-наброски слоёв

**(a) policy — pure, сверка суммы (НЕ ДОВЕРЯЕМ КЛИЕНТУ):**

```python
# src/bot/features/payments/policy.py
from bot.shared.decision import Decision
from bot.features.payments.dto import OrderDraft

def precheck_ok(order: OrderDraft, q_amount: int, q_currency: str) -> Decision:
    # pre_checkout_query несёт total_amount/currency ОТ TELEGRAM — сверяем с заказом бэкенда.
    if order.currency != q_currency or order.amount != q_amount:
        return Decision(allowed=False, reason="Цена изменилась, начните заново")
    return Decision(allowed=True)

def can_refund(order: OrderDraft, role: str) -> Decision:
    if role not in ("support", "admin"):
        return Decision(allowed=False, reason="Недостаточно прав")
    return Decision(allowed=True)
```

**(b) usecase — оркестрация + дедуп. Знает только Protocol'ы:**

```python
# src/bot/features/payments/usecase.py
import structlog
from pylibinfra.cachekit import IdempotencyStore
from bot.features.payments.ports import BillingGateway
from bot.features.payments.dto import OrderDraft, PrecheckOutcome, ConfirmResult
from bot.features.payments import policy, errors
from bot.platform.identity import BotIdentity

class PaymentsUsecase:
    def __init__(self, gw: BillingGateway, dedup: IdempotencyStore) -> None:
        self._gw, self._dedup = gw, dedup
        self._log = structlog.get_logger().bind(feature="payments")

    async def start_purchase(self, identity: BotIdentity, item_id: str) -> OrderDraft:
        # цена/состав резолвит БЭКЕНД, бот их не выдумывает
        return await self._gw.create_order(identity.backend_user_id, item_id)

    async def precheck(self, order_id: str, q_amount: int, q_currency: str) -> PrecheckOutcome:
        # ⏱ вызывается в окне 10с — ОДИН gateway-вызов с жёстким таймаутом; fail-closed
        try:
            order = await self._gw.get_order(order_id)
        except errors.OrderNotFound:
            return PrecheckOutcome(ok=False, error_message="Заказ не найден")
        except Exception:                       # таймаут/бэкенд недоступен → НЕ подтверждаем
            self._log.warning("precheck_backend_unavailable", order_id=order_id)
            return PrecheckOutcome(ok=False, error_message="Сервис занят, попробуйте позже")
        d = policy.precheck_ok(order, q_amount, q_currency)
        return PrecheckOutcome(ok=d.allowed, error_message=None if d.allowed else d.reason)

    async def confirm(self, identity, order_id, charge_id, provider_charge_id,
                      amount, currency) -> ConfirmResult:
        # дедуп №1 (бот): ранний short-circuit на повторный апдейт (at-least-once)
        # kit-форма (§4.1 P3): tgkit.payments.guard_charge(self._dedup, charge_id) + tg_payments_dedup_hits
        cached, _status, found = await self._dedup.get(f"paid:{charge_id}")
        if found and cached is not None:
            return ConfirmResult.model_validate_json(cached)
        # дедуп №2 (бэкенд): тот же charge_id как Idempotency-Key в gateway → бэкенд не задвоит
        res = await self._gw.confirm_payment(order_id, charge_id, provider_charge_id, amount, currency)
        await self._dedup.set(f"paid:{charge_id}", res.model_dump_json().encode(), 200)
        return res
```

**(c) gateway — транспорт→DTO, Idempotency-Key (09 §1.5/§3):**

```python
# src/bot/features/payments/gateway.py
from bot.platform.backend.client import BackendHttpClient
from bot.platform.identity import IdentityContext
from bot.features.payments.dto import OrderDraft, ConfirmResult
from bot.features.payments import errors

class HttpBillingGateway:                       # структурно удовлетворяет BillingGateway
    def __init__(self, http: BackendHttpClient, ident: IdentityContext) -> None:
        self._http, self._ident = http, ident

    async def create_order(self, backend_user_id: str, item_id: str) -> OrderDraft:
        raw = await self._http.post("/v1/orders", json={"item_id": item_id},
                                    headers={**self._ident.headers(),
                                             "Idempotency-Key": f"order:{backend_user_id}:{item_id}"})
        return OrderDraft(order_id=raw["id"], amount=raw["amount"],
                          currency=raw["currency"], label=raw["label"])

    async def confirm_payment(self, order_id, charge_id, provider_charge_id, amount, currency):
        raw = await self._http.post(
            f"/v1/payments/confirm", json={"order_id": order_id, "amount": amount, "currency": currency,
                                           "telegram_charge_id": charge_id,
                                           "provider_charge_id": provider_charge_id},
            headers={**self._ident.headers(), "Idempotency-Key": charge_id},   # ◄ charge_id как ключ
        )
        return ConfirmResult(order_id=order_id, already_confirmed=raw.get("duplicate", False))
```

**(d) handlers.py — DISPATCHER-LEVEL (pre_checkout 10с + successful_payment) + DIALOG-level кнопка:**

```python
# src/bot/features/payments/handlers.py
from aiogram import Router, Bot, F
from aiogram.types import PreCheckoutQuery, Message, LabeledPrice
from dishka.integrations.aiogram import FromDishka, inject
from dishka.integrations.aiogram_dialog import inject as dlg_inject, FromDishka as DlgFromDishka
from bot.features.payments.usecase import PaymentsUsecase
from bot.platform.identity import BotIdentity

payments_router = Router(name="payments")     # обычный Router (НЕ Dialog) — апдейты диспетчера

# ── DIALOG-level: кнопка «Купить» в Window CONFIRM ──────────────────────────────
@dlg_inject
async def on_buy(event, widget, manager,
                 uc: DlgFromDishka[PaymentsUsecase], identity: DlgFromDishka[BotIdentity],
                 bot: DlgFromDishka[Bot]):
    item_id = manager.dialog_data["item_id"]
    order = await uc.start_purchase(identity, item_id)        # цена — С БЭКЕНДА
    await bot.send_invoice(
        chat_id=event.from_user.id,
        title="Покупка", description=order.label,
        payload=order.order_id,                              # ◄ нить связи диалог↔апдейты
        currency=order.currency,                            # "XTR" для Stars
        provider_token="" if order.currency == "XTR" else PROVIDER_TOKEN,  # пусто для Stars
        prices=[LabeledPrice(label=order.label, amount=order.amount)],     # ровно 1 для XTR
    )
    await manager.done()                                     # диалог завершён, ждём оплату апдейтами

# ── DISPATCHER-level: pre_checkout — ⏱ ДЕДЛАЙН 10 с ─────────────────────────────
# kit-вариант (§4.1 P1/P2): payments_router = tgkit.payments.build_router(on_precheck=..., on_success=...)
# а сам ответ — через tgkit.payments.answer_pre_checkout(query, decide=uc.precheck_decision, deadline=9.0)
# (timeout-гард + метрика внутри kit). Шаблон отдаёт ТОЛЬКО decide()-корутину. Ниже — «развёрнутый» вид:
@payments_router.pre_checkout_query()        # фильтр по payload-префиксу при необходимости: F.invoice_payload.startswith("ord_")
@inject
async def on_pre_checkout(query: PreCheckoutQuery, uc: FromDishka[PaymentsUsecase]):
    # generic-обёртка kit'а (P2): wait_for(decide, 9s); таймаут → answer(ok=False) + tg_payments_precheck_timeout
    outcome = await uc.precheck(query.invoice_payload, query.total_amount, query.currency)
    if outcome.ok:
        await query.answer(ok=True)                          # ≤10с
    else:
        await query.answer(ok=False, error_message=outcome.error_message)

# ── DISPATCHER-level: successful_payment — AT-LEAST-ONCE ────────────────────────
@payments_router.message(F.successful_payment)
@inject
async def on_successful_payment(message: Message,
                                uc: FromDishka[PaymentsUsecase], identity: FromDishka[BotIdentity]):
    sp = message.successful_payment
    res = await uc.confirm(identity, order_id=sp.invoice_payload,
                           charge_id=sp.telegram_payment_charge_id,
                           provider_charge_id=sp.provider_payment_charge_id,
                           amount=sp.total_amount, currency=sp.currency)
    if not res.already_confirmed:
        await message.answer("Оплата прошла ✅")
    # опц.: BgManager.bg(...).update(...) — досыл в активный диалог, если есть
```

**Регистрация в `build_dispatcher` (14 §4):**

```python
# src/bot/app.py :: build_dispatcher — ДО setup_dialogs
from bot.features.payments.handlers import payments_router
dp.include_router(payments_router)            # pre_checkout/successful_payment — апдейты диспетчера
# ... dp.include_router(build_dialog_router())   # диалоги (вкл. payment_dialog)
# ... setup_dishka(container, router=dp)
# ... setup_dialogs(dp, ...)                      # СТРОГО последним
```

> **provider_token.** Для **Stars/XTR** — пустая строка `""` (подтверждено aiogram
> `stars_invoice.py` и [sendInvoice docs](https://docs.aiogram.dev/en/latest/api/methods/send_invoice.html)).
> Для **фиата** — секрет из Vault через config-кит (08:141), `provider_token=PROVIDER_TOKEN`.
> Для XTR `prices` — **ровно один** `LabeledPrice`, `shipping_query` **не приходит** (08:142,146).

---

## 2. WebApp / Mini App + валидация initData

### 2.1. Два способа доставки данных из WebApp (оба, рекомендация)

| Способ | Транспорт | Где обрабатывается | Когда применять |
|---|---|---|---|
| **A. `sendData` → `web_app_data`** | WebApp-JS зовёт `Telegram.WebApp.sendData(json)` → приходит **сервисное сообщение** `Message.web_app_data` (апдупдейт диспетчера) | `webapp/handlers.py` (dispatcher-level `@router.message(F.web_app_data)`) | **только** для WebApp, запущенного из **reply-keyboard `web_app`-кнопки**; payload ≤ 4096 байт; **закрывает Mini App**. |
| **B. HTTP к бэкенду/боту с `initData`** | WebApp-JS шлёт `fetch(backend, {headers:{Authorization: "tma "+initData}})` | `webapp/routes.py` (httpkit FastAPI-эндпоинт, 04 §8) **или** прямо на бэкенд | Inline-кнопки, menu-button, любой интерактивный обмен, многошаговые сценарии. **Основной путь.** |

> **Камень (08:158,164).** `web_app_data` приходит **не у всех** способов запуска — **только**
> из reply-keyboard-кнопки. Из inline/menu-button его НЕТ → там работает только путь B (HTTP).
> Поэтому **рекомендация:** **путь B (initData)** как основной (универсален, без 4 КБ-лимита,
> двусторонний), путь A — как простой one-shot для reply-кнопки.

> **Важно про доверие.** В **обоих** путях есть `Telegram.WebApp.initData`, и **в обоих** его
> надо **валидировать HMAC** перед доверием `user.id`. В пути A `web_app_data.data` —
> произвольная клиентская строка, `from_user` сообщения доверять можно (его ставит Telegram),
> но **сам payload — клиентский** (не класть туда цену/права). В пути B доверять `user` можно
> **только** после проверки hash (08:160: «не доверять `user.id` без валидации hash»).

### 2.2. Кнопка запуска Mini App (в диалоге)

```python
# в payments/webapp dialogs.py — Window
from aiogram_dialog.widgets.kbd import WebApp
from aiogram_dialog.widgets.text import Const
# WebApp(Url): web_app=WebAppInfo(url=...), HTTPS обязателен (docs 09 §4.3)
WebApp(Const("🚀 Открыть Mini App"), Const("https://miniapp.example.com"))
```

> **Gotcha 8.4 (docs).** В reply-окне (`ReplyKeyboardFactory`) `Url`/`LoginURL`/`CopyText`
> кидают `ValueError`, а **`WebApp`-кнопка конвертируется** (`web_app` сохраняется). Так что
> `WebApp` валиден и в inline-, и в reply-окне. Для **reply-keyboard `web_app`** (которая даёт
> путь A `sendData`) используем `KeyboardButton(web_app=WebAppInfo(...))` — в aiogram_dialog это
> подкласс `Keyboard` или прямой reply-markup (как `RequestUser` делается вручную, 14-kbd-request §11).

### 2.3. Сервис `platform/webapp/` — раскладка и место валидатора

Валидация initData — это **НЕ aiogram-апдейт** (08:164), а либо HTTP-эндпоинт (путь B), либо
вспомогательная проверка на уровне сервиса. Это **не фича** (нет диалога/state своего) — это
**platform-сервис** рядом с `identity/`:

```
src/bot/platform/webapp/
├── __init__.py
├── init_data.py     # ЯДРО: validate_init_data(raw, bot_token, max_age) -> WebAppInitData
│                    #   pure-функция HMAC-SHA256 + парсинг + auth_date — БЕЗ I/O, тестируется юнитом
├── dto.py           # WebAppInitData(user, auth_date, query_id, raw_user, start_param, ...)
├── errors.py        # InitDataInvalid (bad hash), InitDataExpired (auth_date), InitDataMalformed
├── identity_link.py # WebAppInitData → BotIdentity (маппинг tg_user → backend_user, как 09 §2.2)
├── gateway.py       # передача проверенных данных на бэкенд (BackendGateway-подобный порт)
├── routes.py        # (webhook-режим) httpkit FastAPI-router: POST /webapp/* с проверкой initData
└── provider.py      # dishka Provider: bot_token-config → валидатор; identity-link; gateway
```

> **Можно ли вынести валидатор initData в pylibinfra?** **Нет — обоснование:** алгоритм
> `secret = HMAC_SHA256(key="WebAppData", data=bot_token)` + парсинг `query_id`/`user`/`start_param`
> + окно `auth_date` — это **Telegram-специфика** (формат `data-check-string`, имена полей,
> константа `"WebAppData"`). pylibinfra — **vendor-agnostic** инфра (http/cache/jwt/otel), как
> границы в 14 §5 / 01 §6.4: «переиспользуемое/инфра → кандидат в pylibinfra», но это **доменная
> специфика Telegram**, не инфра-примитив. Аналогия: `authnkit.JWTParser` (generic JWT) — в
> pylibinfra; а маппинг «Telegram deep-link → backend_user» (09 §2.2) — в `platform/identity`
> бота. **Вывод:** валидатор → `platform/webapp/init_data.py` (pure, тестируемый); generic-кирпич,
> который он использует (constant-time compare, hmac) — стандартная `hmac`/`hashlib`, не требует
> кита. Если в pylibinfra появится `tgkit` (Telegram-специфичный кит) — тогда туда; пока **нет**.
> Pure-ядро `validate_init_data` можно при желании держать в `shared/` (как `shared/decision.py`),
> но `platform/webapp/` логичнее: оно знает про `BotIdentity` и bot_token-config.

### 2.4. Валидатор initData — код-набросок (HMAC-SHA256 + auth_date)

```python
# src/bot/platform/webapp/init_data.py — PURE, без I/O (юнит-тест на фикстурах)
import hmac, hashlib, time
from urllib.parse import parse_qsl
from bot.platform.webapp.dto import WebAppInitData
from bot.platform.webapp.errors import InitDataInvalid, InitDataExpired, InitDataMalformed

_WEBAPP_KEY = b"WebAppData"

def validate_init_data(raw: str, bot_token: str, *, max_age_sec: int = 300) -> WebAppInitData:
    """
    Алгоритм (core.telegram.org/bots/webapps):
      secret_key      = HMAC_SHA256(key="WebAppData", data=bot_token)
      data_check_str  = "\\n".join(f"{k}={v}" for k,v in sorted(pairs) if k != "hash")
      calc_hash       = hex( HMAC_SHA256(key=secret_key, data=data_check_str) )
      valid  ⟺  constant_time_eq(calc_hash, received_hash)  AND  now - auth_date <= max_age
    """
    try:
        pairs = dict(parse_qsl(raw, strict_parsing=True))      # сохранить порядок не нужно — сортируем
    except ValueError as e:
        raise InitDataMalformed(str(e))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataMalformed("no hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(_WEBAPP_KEY, bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):      # constant-time (08:161, анти-timing)
        raise InitDataInvalid("hash mismatch")                 # подделка/чужой токен

    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date <= 0 or (int(time.time()) - auth_date) > max_age_sec:   # anti-replay, ≤5 мин (08:159)
        raise InitDataExpired("stale auth_date")

    return WebAppInitData.parse(pairs)   # парсит JSON-поле user → tg_id/username/...
```

> **Bot API 8.0+ (Ed25519) — note.** Telegram добавил параллельную подпись `signature`
> (Ed25519, валидируется публичным ключом Telegram, не bot_token) для third-party-валидации без
> раскрытия токена. Шаблон реализует **классический HMAC-путь** (нужен только `bot_token`,
> которым бот владеет — проще и достаточно для self-валидации). Ed25519 — расширение, если
> понадобится валидировать на стороне, не знающей токена. Источники:
> [webapps docs](https://core.telegram.org/bots/webapps), [tma-js validating](https://docs.telegram-mini-apps.com/packages/tma-js-init-data-node/validating).

### 2.5. HTTP-эндпоинт (путь B, webhook-режим, httpkit 04 §8)

```python
# src/bot/platform/webapp/routes.py — только в webhook-режиме (httpkit FastAPI)
from fastapi import APIRouter, Header, HTTPException
from dishka.integrations.fastapi import FromDishka, inject
from bot.platform.webapp.init_data import validate_init_data
from bot.platform.webapp.errors import InitDataInvalid, InitDataExpired
from bot.platform.webapp.identity_link import to_identity
from bot.platform.webapp.gateway import WebAppGateway

webapp_router = APIRouter(prefix="/webapp")

@webapp_router.post("/action")
@inject
async def webapp_action(payload: dict,
                        authorization: str = Header(...),     # "tma <initData>"
                        bot_token: FromDishka[str] = None,
                        gw: FromDishka[WebAppGateway] = None):
    raw = authorization.removeprefix("tma ").strip()
    try:
        init = validate_init_data(raw, bot_token, max_age_sec=300)
    except InitDataExpired:
        raise HTTPException(401, "initData expired")
    except InitDataInvalid:
        raise HTTPException(403, "initData invalid")          # подделка
    identity = to_identity(init)                              # tg_user → BackendIdentity (09 §2.2)
    # payload КЛИЕНТСКИЙ — действие/сумму резолвит бэкенд по identity, не из payload
    return await gw.perform(identity, action=payload.get("action"))
```

> **httpkit-нюансы (04 §8 warning).** `RateLimitMiddleware` лимитит **per-IP** — для WebApp-
> эндпоинта IP **пользовательские** (не пул Telegram), так что дефолт rps=100/burst=200 ок,
> но добавить **anti-bruteforce на сам эндпоинт** (08:161: rate-limit). `MaxBodyMiddleware` 1 MiB
> — норм. CORS — разрешить origin Mini App. **Этот же FastAPI-app** уже поднят для Telegram-
> webhook (14 §4, 04 §8) — `webapp_router` просто `app.include_router(...)`, отдельный сервер не
> нужен. В **polling-режиме** httpkit нет (04 §8) → путь B идёт **прямо на бэкенд** (Mini App
> валидирует initData на бэкенде тем же алгоритмом), а бот реализует **только путь A**
> (`web_app_data`). Шаблон даёт обе ветки, выбор — по `cfg.mode`.

### 2.6. Путь A — обработчик `web_app_data` (dispatcher-level)

```python
# src/bot/platform/webapp/handlers.py  (или features/<webapp-feature>/handlers.py)
from aiogram import Router, F
from aiogram.types import Message
webapp_data_router = Router(name="webapp_data")

@webapp_data_router.message(F.web_app_data)
@inject
async def on_web_app_data(message: Message, gw: FromDishka[WebAppGateway],
                          identity: FromDishka[BotIdentity]):
    # message.web_app_data.data — КЛИЕНТСКАЯ строка (button_text + data). from_user — доверенный.
    # Не доверять содержимому payload для денег/прав — резолв на бэкенде по identity.
    await gw.handle_sent_data(identity, raw=message.web_app_data.data)
    await message.answer("Данные получены ✅")
```

---

## 3. Идемпотентность и безопасность

### 3.1. Что НЕ доверять клиенту

| Данные | Откуда приходят | Почему опасно | Правильно |
|---|---|---|---|
| Сумма/цена | `callback_data`, `web_app_data.data`, `payload` Mini App | подделываемы клиентом | **резолвить на бэкенде** по `order_id`/`item_id` (`gw.create_order`/`get_order`); в инвойс — `amount` **с бэкенда** |
| `pre_checkout_query.total_amount` | от Telegram, но **отражает то, что бот сам положил в инвойс** | если бот клал клиентскую цену — уже скомпрометировано | сверять с `order.amount` (`policy.precheck_ok`); инвойс изначально из бэкенд-цены |
| `user.id` из `initData` | WebApp-JS | подделываемо без проверки | доверять **только** после HMAC (`validate_init_data`); 08:160 |
| Состав/право заказа | любой клиентский payload | privilege escalation | бэкенд проверяет принадлежность заказа `identity.backend_user_id` |

### 3.2. Дедуп платёжных апдейтов (at-least-once, 08:144,148; 09 §3)

**Двойная защита** (как 09 §3 «оба слоя одним ключом»):

1. **На боте — ранний short-circuit.** `cachekit.IdempotencyStore`, ключ `paid:<telegram_payment_charge_id>`
   (см. `usecase.confirm` §1.4b). Закрывает повторный `successful_payment` (ретрай вебхука Telegram).
   Дополнительно — generic **dedup апдейтов** `tg:update:<update_id>` в outer-middleware
   (09 §3 note: «отдельный короткий маркер про апдейт») — ловит дубль на уровне транспорта раньше DI.
2. **На бэкенде — `Idempotency-Key = telegram_payment_charge_id`** в `gw.confirm_payment`
   (`httpkit.IdempotencyMiddleware`, 09 §3). Даже если бот рестартнул и его кэш холодный —
   бэкенд не проведёт заказ дважды. `charge_id` стабилен и уникален per-payment → идеальный ключ.

**Refund** идемпотентен по `charge_id` на стороне Telegram (08:145) + `authorize_refund` на
бэкенде гейтит политику и состояние (`AlreadyRefunded`). Хранить `charge_id` (в заказе на
бэкенде) обязательно — иначе нечем вызвать `refund_star_payment`.

### 3.3. Защита от повторной выдачи / fail-states

- **Не считать заказ оплаченным без `successful_payment`** (08:147): провал/отмена → апдейта
  просто нет. Reconcile-джоба (`timerkit`) сверяет «висящие» заказы с `getStarTransactions`/бэкендом.
- **pre_checkout fail-closed:** при недоступности бэкенда в окне 10 с → `ok=False` (не «на всякий
  случай ok=True» — иначе спишем без подтверждённого заказа). См. `usecase.precheck` §1.4b.
- **initData:** `auth_date` ≤ 5 мин (anti-replay) + constant-time hash (anti-timing, 08:161) +
  rate-limit на эндпоинт (anti-bruteforce).

---

## 4. Граница generic↔business: поверхность kit'а (`tgkit`, зона 18)

> **18-принцип (директива архитектора):** «ВСЯ инфраструктура бота прячется в pylibinfra
> (bot-infra kit `tgkit`, aiogram как опциональная extra), а в шаблоне — ТОЛЬКО бизнес-логика».
> Поэтому generic-механику (aiogram-specific, но не product-specific) оформляем как **поверхность
> kit'а / его точки расширения**, а в `features/payments/` + `platform/webapp/` оставляем **только
> бизнес** (что продаём, цены, диалоги). Ниже — что именно и в какой форме отдаёт kit, чтобы зона
> 18 могла встроить это в `tgkit` совместимо с остальными китами (Provider + Config-asymmetry +
> `biz_tg_*`-метрики + opt-deps как в 04 §8).

### 4.1. ТАБЛИЦА: механизм → generic(kit) или business(шаблон) → поверхность

| # | Механизм | Generic (kit `tgkit`) / Business (шаблон) | Поверхность (форма API kit'а или место в шаблоне) |
|---|---|---|---|
| **Платежи** ||||
| P1 | Регистрация dispatcher-level `pre_checkout_query`/`successful_payment` хендлеров | **kit** (механика «куда вешать»), **шаблон** (что внутри) | `tgkit.payments.PaymentsRouterBuilder(on_precheck=…, on_success=…)` → готовый `Router` с правильными фильтрами/middleware; шаблон передаёт **колбэки-usecase'ы**. Точка расширения, не хардкод. |
| P2 | Быстрый ответ pre_checkout с таймаут-гардом ≤10с | **kit** | `tgkit.payments.answer_pre_checkout(query, decide, *, deadline=9.0, on_timeout="fail_closed")` — оборачивает `decide()` в `asyncio.wait_for`, при таймауте сам шлёт `answer(ok=False)`, инкрементит метрику. Шаблон даёт **только** `decide()`-корутину (бизнес-проверку). |
| P3 | Дедуп платёжных апдейтов (at-least-once) | **kit** | (a) generic outer-middleware `tgkit.dedup.UpdateDedupMiddleware(store)` по `update_id` (`tg:update:<id>`); (b) helper `tgkit.payments.guard_charge(store, charge_id)` → bool «уже видели». Поверх `cachekit.IdempotencyStore` (09 §3). Шаблон вызывает helper в `usecase.confirm`. |
| P4 | Метрики платежей | **kit** | `tgkit.payments.metrics` поверх `pylibinfra.bizmetric` (04 §7): `tg_payments_invoice_total{currency}`, `tg_payments_precheck_total{result}`, `tg_payments_precheck_timeout_total`, `tg_payments_success_total{currency}`, `tg_payments_refund_total`, `tg_payments_dedup_hits_total`. No-op-safe без telemetry. Шаблон — **ничего** (инкремент внутри P1/P2/P3). |
| P5 | `send_invoice`-обёртка (XTR vs фиат-ветка) | **kit** (форма вызова), **шаблон** (title/desc/payload/amount) | (опц.) `tgkit.payments.build_invoice(currency, amount, label, payload, provider_token="")` — нормализует «XTR ⇒ `provider_token=""`, ровно 1 `LabeledPrice`». Тонко: можно и без kit (один `bot.send_invoice`). |
| P6 | `refund_star_payment` | **kit** (вызов идемпотентен по charge_id) / **шаблон** (политика «можно ли») | прямой `bot.refund_star_payment(...)`; политику возврата (`authorize_refund`) держит шаблон. Kit-обёртки почти не нужно. |
| P7 | **Цена/каталог/состав заказа** | **business (шаблон)** | `features/payments/` целиком: `policy` (сверка сумм), `usecase`, `gateway` (backend confirm/refund), `dialogs` (кнопка «Купить»), маппинг `pre_checkout`/`successful_payment` → usecase. **Kit это НЕ знает.** |
| **WebApp / Mini App** ||||
| W1 | Валидатор initData (HMAC-SHA256 + auth_date) | **generic, но Telegram-vendor** → `platform/webapp/init_data.py` (или `tgkit.webapp`, если kit берёт vendor-Telegram-слой) | pure `validate_init_data(raw, bot_token, *, max_age_sec) -> WebAppInitData` — aiogram-agnostic, без I/O. **НЕ** в core-pylibinfra (vendor-specific), но **кандидат в `tgkit.webapp`** (см. §4.2). Шаблон — **ничего**, только зовёт. |
| W2 | Маппинг проверенного initData → identity | **kit-helper** (форма) / **шаблон** (правила линковки) | `tgkit.webapp.to_identity_seed(init) -> {tg_id, username, start_param}` (механический разбор); **бизнес-линковка** `tg_user → backend_user` (09 §2.2) — в `platform/identity` шаблона. |
| W3 | HTTP-эндпоинт `/webapp/*` с проверкой `Authorization: tma <initData>` | **kit** (механика парсинга заголовка + 401/403) / **шаблон** (действия) | (опц.) `tgkit.webapp.InitDataAuthDep` — FastAPI-dependency поверх httpkit (04 §8): дёргает W1, кидает 401/403, отдаёт `WebAppInitData`. Шаблон пишет только `@router.post(...)` с бизнес-действием. |
| W4 | Обработчик `web_app_data` (путь A) | **kit** (регистрация фильтра) / **шаблон** (что делать с payload) | `tgkit.webapp.WebAppDataRouterBuilder(on_data=…)`; payload — клиентский, бизнес-резолв на бэкенде в шаблоне. |
| W5 | `WebApp`-кнопка запуска | **используется как есть из aiogram_dialog** | `aiogram_dialog.widgets.kbd.WebApp` — kit не нужен; в шаблоне HTTPS-url Mini App. |
| W6 | **Что делать с проверенными данными** | **business (шаблон)** | `platform/webapp/gateway.py` + бизнес-действие; передача на бэкенд через `BackendGateway`-порт. **Kit это НЕ знает.** |

> **Читать так:** строки с **kit** — это поверхность `tgkit` (зона 18 встраивает; шаблон только
> конфигурирует/передаёт колбэки); строки с **business** — это `features/payments/` и
> `platform/webapp/`-бизнес, которые форк дорабатывает (§5 — что из этого прунится de-template'ом).
> Принцип границы тот же, что 14 §5 / 01 §6.4: «переиспользуемое aiogram-specific → kit, доменное
> → шаблон». Vendor-Telegram pure-слой (валидатор initData, invoice-нормализация) — **пограничный**:
> по умолчанию в шаблоне (`platform/webapp/`, `payments/`), но спроектирован так, чтобы **подняться
> в `tgkit` без переписывания** (чистые функции, нулевые зависимости от шаблона) — см. §4.2.

### 4.2. Где живёт валидатор initData (обоснование, §4.1 W1)

Три кандидата, выбор — **`platform/webapp/init_data.py` сейчас, `tgkit.webapp` после зоны 18**:

| Кандидат | За | Против | Вердикт |
|---|---|---|---|
| **core-pylibinfra** (`authnkit`/новый) | переиспользуемо, тестируемо | **vendor-specific**: константа `"WebAppData"`, формат `data-check-string`, имена полей — Telegram-доменная специфика, не инфра-примитив (как `JWTParser`). Ломает «kit = vendor-agnostic» (04). | **нет** |
| **`tgkit.webapp`** (bot-infra kit, зона 18) | Telegram-vendor-кит — **ровно его место**; aiogram-agnostic pure-функция переиспользуема между ботами | требует, чтобы зона 18 уже завела `tgkit` | **целевое** (когда kit готов) |
| **`platform/webapp/init_data.py`** (шаблон) | работает без kit; pure → юнит-тест на фикстурах; знает про `BotIdentity`/bot_token-config | дублируется между ботами, если их много | **дефолт сейчас** |

**Решение:** реализуем как **pure-функцию с нулевой зависимостью от шаблона** в
`platform/webapp/init_data.py` — это делает её **механически подъёмной в `tgkit.webapp`** (просто
перенос файла + re-export), как только зона 18 заведёт vendor-Telegram-кит. Generic-кирпичи,
которые она использует (`hmac`/`hashlib`/`compare_digest`) — stdlib, кита не требуют. Pure-ядро
**можно** держать и в `shared/` (как `shared/decision.py`), но `platform/webapp/` логичнее: рядом с
identity-линковкой и bot_token-config. **Та же логика для invoice-нормализации (§4.1 P5) и
`answer_pre_checkout` (P2):** пишем generic-форму так, чтобы зона 18 забрала её в `tgkit` дословно.

## 5. Таблица «что генерим в скелет» (de-template prune-able, как `start`/`profile` 14 §6)

| Артефакт | Путь | Скелет даёт | Прикладное (дорабатывает форк) |
|---|---|---|---|
| Фича `payments/` (полный набор 14 §2) | `src/bot/features/payments/` | **полный reference**: state/dto/errors/policy/ports/usecase/gateway/dialogs/getters/handlers/views/provider/adapters | реальные эндпоинты биллинга бэкенда, реальный каталог, `provider_token` фиата из Vault |
| `pre_checkout` handler (10 с, fail-closed) | `payments/handlers.py` | **рабочий** dispatcher-level хендлер + жёсткий таймаут precheck | политика precheck (стоки/лимиты) на бэкенде |
| `successful_payment` handler (дедуп) | `payments/handlers.py` | **рабочий** + дедуп `paid:<charge_id>` + Idempotency-Key | бизнес-проведение заказа на бэкенде |
| `refund` (`refund_star_payment`) | `payments/usecase.py` + команда саппорта | **набросок** usecase.refund + `authorize_refund`-порт | UI/права саппорта, политика возврата |
| Stars/XTR инвойс (пустой provider_token, 1 price) | `payments/handlers.py::on_buy` | **рабочий** `send_invoice(currency="XTR", provider_token="")` | каталог/цены |
| Фиат-инвойс (provider_token из Vault) | то же, ветка `currency != "XTR"` | **заготовка** + config-кит для provider_token | боевой provider_token, shipping (если `is_flexible`) |
| `platform/webapp/init_data.py` (HMAC) | `src/bot/platform/webapp/` | **рабочий pure-валидатор** + юнит-тесты на фикстурах | — (generic, остаётся) |
| WebApp путь A (`web_app_data`) | `platform/webapp/handlers.py` | **рабочий** dispatcher-level хендлер | парсинг конкретного payload |
| WebApp путь B (httpkit-эндпоинт `/webapp/*`) | `platform/webapp/routes.py` | **набросок** (webhook-режим) + проверка `Authorization: tma <initData>` | реальные действия Mini App; CORS-origin; rate-limit |
| `WebApp`-кнопка запуска | в `dialogs.py` фичи | **пример** `WebApp(Const(...), Const(https-url))` + reply `web_app` для пути A | HTTPS-url боевого Mini App |
| dedup-маркеры (Cache) | `usecase` + outer-middleware | **рабочие** `paid:<charge_id>` + `tg:update:<id>` | — |
| reconcile-джоба (timerkit) | `payments/` (опц.) | **заготовка-гайд** | сверка с `getStarTransactions`/бэкендом |
| import-linter контракты | `importlinter.toml` | `payments`/`webapp` добавлены в independence/layers/forbidden (14 §5) | — |

---

## Сухой остаток

0. **Граница generic↔business (директива архитектора, §4).** В **kit `tgkit`** (зона 18) уходит
   generic-механика: регистрация dispatcher-level pre_checkout/successful_payment как **точка
   расширения** (колбэки-usecase'ы из шаблона), helper `answer_pre_checkout` с **timeout-гардом**
   ≤10с (fail-closed), **dedup платёжных апдейтов** (`update_id` + `charge_id` поверх
   `cachekit.IdempotencyStore`), метрики `tg_payments_*` (поверх `bizmetric`). В **шаблоне** —
   **только бизнес**: `features/payments/` (цены/каталог/диалоги) + `platform/webapp/`-gateway.
   Валидатор initData — vendor-Telegram **pure**-функция: сейчас в `platform/webapp/init_data.py`,
   спроектирована **подъёмной в `tgkit.webapp` без переписывания** (нулевая связь со шаблоном).
1. **`pre_checkout_query` и `successful_payment` — апдейты ДИСПЕТЧЕРА**, не dialog-callback:
   живут на `payments_router` (обычный `Router`), `include_router` **до** `setup_dialogs`; связь
   с диалогом покупки — через **`invoice_payload = order_id`** (+ опц. `BgManager.bg().update`).
2. **Анатомия 14 §2 соблюдена** для `payments/`: pure `policy` (сверка суммы), `usecase`
   (оркестрация + дедуп), `gateway` (backend confirm/refund + Idempotency-Key), `handlers`
   (dialog-кнопка «Купить» + dispatcher-level pre_checkout/successful_payment).
3. **10-секундный дедлайн** pre_checkout — один быстрый gateway-вызов с жёстким таймаутом,
   **fail-closed** (`ok=False` при недоступности). **Stars/XTR:** `currency="XTR"`,
   `provider_token=""`, ровно один `LabeledPrice`.
4. **Идемпотентность двойная** (09 §3): бот — `paid:<telegram_payment_charge_id>` в
   `cachekit.IdempotencyStore` + `tg:update:<id>`; бэкенд — `Idempotency-Key=charge_id`. **Не
   доверять клиенту:** сумму/товар брать с бэкенда по `order_id`, не из callback/payload.
5. **WebApp:** валидатор initData — **pure** `platform/webapp/init_data.py` (HMAC-SHA256,
   `secret=HMAC("WebAppData", bot_token)`, constant-time hash, `auth_date ≤ 5 мин`); **в
   pylibinfra не выносим** (Telegram-специфика, не инфра-примитив). Два пути доставки:
   **A** `web_app_data` (reply-кнопка, one-shot), **B** HTTP с `initData` (httpkit-эндпоинт,
   основной); рекомендация — B как универсальный, A как простой случай.
6. **Reference-фичи `payments/` + `platform/webapp/`** генерятся в скелет, prune-able через
   de-template (как `start`/`profile`, 14 §6).
