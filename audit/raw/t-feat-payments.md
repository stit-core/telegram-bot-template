# Аудит фичи `payments` (id=t-feat-payments)

## Что смотрел

Весь вертикальный срез фичи `src/bot/features/payments/`: `dto.py`, `state.py`, `ports.py`,
`errors.py`, `policy.py`, `usecase.py`, `gateway.py`, `getters.py`, `views.py`, `handlers.py`,
`dialogs.py`, `provider.py`, `__init__.py`. Плюс связанная инфра kit'а
(`pylibinfra/tgbotkit/payments/{invoice,precheckout,guard}.py`, `extension.py`, `module.py`,
`metrics.py`), platform-фасад `bot/platform/backend/*`, регистрация в `extensions.py`,
каталог состояний `platform/dialogs/states.py`, тесты (`tests/unit/test_payments.py`,
`tests/flows/test_payments_flow.py`) и контент (`locales/{ru,en}/payments.ftl`).

Прогнал доказательно:
- `uv run lint-imports --config importlinter.toml` → **3 контракта KEPT** (слои внутри фичи,
  независимость фич, чистое ядро).
- `uv run mypy src/bot/features/payments` → **Success, no issues** (13 файлов).
- `uv run pytest tests/unit/test_payments.py tests/flows/test_payments_flow.py` → **6 passed**.

## Сильные стороны

- **Образцовый гексагон и чистота слоёв.** Ядро (`dto`/`state`/`ports`/`errors`/`policy`) PURE,
  `usecase` знает только Protocol-порт `PaymentsGateway` + `policy`, единственный I/O — в
  `gateway.py` поверх `platform/backend` (не сырой httpx). Контракт import-linter «Чистое ядро»
  держится (проверено). `ports.py:14` — узкий ISP-порт (`get_offer`/`fulfill`), DTO локальный
  (anti-corruption), `gateway.py:23-26` мапит транспорт-ошибки в sentinel'ы фичи.
- **«Не доверять клиенту» реализовано правильно.** `on_pre_checkout` (`handlers.py:50-57`) НЕ
  принимает `q.total_amount`/`q.invoice_payload` как истину — `usecase.confirm` (`usecase.py:25-30`)
  грузит авторитетную цену с бэкенда и сверяет через чистую `policy.amount_matches`. Это ровно тот
  инвариант, который ломают большинство реализаций Telegram-платежей.
- **Fail-closed на pre_checkout.** `answer_pre_checkout` (kit) с `deadline=9.0 < 10с` дедлайна
  Telegram; таймаут/исключение в `decide` → `ok=False` (`precheckout.py:43-44`). `confirm` тоже
  fail-closed при ошибке бэкенда (`usecase.py:28-29`). Покрыто unit-тестом
  `test_confirm_fails_closed_on_backend_error`.
- **Дедуп successful_payment.** at-least-once доставка обрабатывается через `guard_charge` (атомарный
  `SET NX EX` по `telegram_payment_charge_id`, `guard.py:24`), TTL 7 дней. `fulfill` к тому же
  идемпотентен на бэкенде через `Idempotency-Key=charge_id` (`gateway.py:31-34`) — двойная защита.
- **Граница шаблон↔kit держится корректно.** Generic-механика платежей (build_invoice/
  answer_pre_checkout/guard_charge, эмиссия `tg_payments_total`) — в kit'е; в шаблоне только бизнес
  (offer/policy/usecase/gateway/dialog) + регистрация через `CommandSpec` в `__init__.py:16-19`.
  Это by design и сделано чисто.
- **Корректная регистрация dispatcher-level апдейтов.** `pre_checkout_query` и
  `message+F.successful_payment` идут через `CommandBundle` (`__init__.py`), а не как dialog-callback —
  это архитектурно верно (это апдейты диспетчера). DI разнесён правильно: dialog-level `on_buy` —
  `@inject` из `aiogram_dialog`, dispatcher-level — из `aiogram` (`handlers.py:19-20`).
- **State минимален и сериализуем.** `PaymentsSG` = одно окно `OFFER`, `dialog_data`/`start_data`
  фича не пишет вовсе → нет рисков JSON-сериализации. `DEMO_OFFER_ID` вынесен в PURE `state.py:13`,
  чтобы getters и handlers (один слой, не импортят друг друга) брали его, не нарушая контракт.

## Находки

### HIGH

**[correctness] Окно потери fulfill: guard ставит ключ ДО успешного `complete`, ошибка `fulfill`
→ платёж списан, выдачи нет, повтор Telegram заглушается.**
`handlers.py:71-73`:
```python
if await guard_charge(client, sp.telegram_payment_charge_id):
    return
await uc.complete(sp.invoice_payload, sp.telegram_payment_charge_id)
```
`guard_charge` (`guard.py:24`) делает `SET NX` *первым делом* и возвращает `False` (=не дубль) —
ключ дедупа уже записан. Затем `uc.complete` → `gateway.fulfill` может бросить
`errors.PaymentError("Сервис оплаты недоступен")` при `BackendUnavailable` (`gateway.py:36-37`).
Это исключение НЕ ловится в хендлере и всплывает в recovery-middleware kit'а, которая его
**проглатывает** (`errorux.py:56-58`: «panic-метрика + on_unhandled + swallow»). Telegram при
at-least-once может прислать тот же `successful_payment` повторно — но `guard_charge` теперь
вернёт `True` (ключ стоит 7 дней) и хендлер выйдет на `return`, **не выдав товар**.

Итог: при транзиентной недоступности backend в момент `fulfill` пользователь оплачивает звёздами,
а выдачи не получает, и автоматического восстановления нет (дедуп-ключ маскирует ретрай). Это
worst-case для платёжной фичи — потеря денег пользователя.

Усугубляет: backend `Idempotency-Key` (`gateway.py:33`) спасает только если `fulfill` *дошёл и
выполнился*, но ответ потерялся; при breaker-open/connect-refused запрос вообще не доходит, а
дедуп-ключ всё равно поставлен.

*Fix:* инвертировать порядок — сначала `complete`/`fulfill` (он идемпотентен на бэкенде), и только
ПОСЛЕ успеха ставить дедуп-ключ; либо ловить ошибку `fulfill` в хендлере и в этом случае удалять/не
ставить guard-ключ (`DEL tg:charge:*`), чтобы Telegram-redelivery дала вторую попытку. Поскольку
`fulfill` уже идемпотентен по `charge_id`, guard вообще можно низвести до защиты от конкурентной
двойной обработки (ставить ключ с коротким TTL только на время обработки, либо переносить запись
ключа за успешный `complete`). Это решение лежит на стороне kit'а (`guard_charge` — его примитив) и
шаблона совместно — кандидат в INFRA-HANDOFF/PR в tgbotkit.

### MEDIUM

**[observability] Нет метрики успешной выдачи — «золотой путь» платежа не виден в телеметрии.**
`metrics.py:37` объявляет `tg_payments_total`, но он инкрементится только в kit на
`stage=pre_checkout` (`precheckout.py:49`) и `stage=paid,result=duplicate` (`guard.py:27`).
Успешный `stage=paid,result=ok` (фактическая выдача) НЕ эмитится нигде — ни в kit, ни в
`usecase.complete` (`usecase.py:32-34` пишет только лог `payments.fulfilled`). Невозможно
построить алерт «оплат пришло N, выдач M, N>M» — то есть именно тот инцидент из HIGH-находки
не будет виден на дашборде. *Fix:* эмитить `payments_total{stage=paid,result=ok}` после успешного
`complete` (в kit-обёртке или передать инструмент в usecase).

**[errors] `on_buy` молча проглатывает случай `callback.message is None`.**
`handlers.py:44-46`: `send_invoice` шлётся только если `callback.message is not None`, иначе
просто `callback.answer()` без инвойса и без обратной связи — пользователь нажал «Купить», но
ничего не произошло и он не узнает почему. `callback.message` бывает `None` для очень старых
сообщений (Telegram не присылает message в callback). *Fix:* в ветке `else` ответить алертом
(«сообщение устарело, откройте оффер заново») либо использовать `callback.from_user.id` как
`chat_id` (для приватных чатов он равен chat.id), чтобы инвойс всё равно ушёл.

### LOW

**[correctness] Дублирование проверки валюты между `usecase.confirm` и `policy`.**
`usecase.py:30` проверяет `order.currency == currency`, а `policy.amount_matches`
(`policy.py:10`) — только сумму. Сверка валюты — такое же правило «не доверять клиенту», но живёт в
usecase, а не в чистой `policy` (где её было бы естественно тестировать рядом с суммой). Не баг
(валюта проверяется), но размывает single-responsibility policy. *Fix:* перенести проверку валюты
в `policy` (напр. `offer_matches(expected: Order, amount, currency) -> bool`).

**[correctness] `Order.amount` не валидируется как положительный на входе DTO.**
`dto.py:16` — `amount: int` без `Field(gt=0)`. Защита от нуля/отрицательного есть только в
`policy.amount_matches` (`got > 0`), но она проверяет *присланную клиентом* сумму, а не
*авторитетную* `order.amount` с бэкенда. Если бэкенд вернёт `amount=0`/отрицательное, `confirm`
сравнит `got == 0` и при клиентском `0` это `False` (ок), но `build_invoice` с `amount<=0`
(`invoice.py:30`) уйдёт в Telegram и упадёт там некрасиво. *Fix:* `amount: int = Field(gt=0)` в DTO
(fail-fast на маппинге `_to_order`). CONF=medium — зависит от гарантий бэкенда.

### INFO

- **`amount` для XTR — целые звёзды, не сотые доли.** Зафиксировано в docstring `dto.py:3` и
  `invoice.py:1-3`. Это корректно для XTR, но **жёстко завязано на XTR**: для фиатной оплаты
  (`provider_token`, суммы в сотых) тот же `Order.amount: int` будет означать другое (центы), и
  `policy`/getter (`💎 {amount} ⭐` в `dialogs.py:15`) этого не различают. Обобщаемость за пределы
  Stars **частичная**: `build_invoice` уже умеет `provider_token` для non-XTR (`invoice.py:24`), но
  presentation и семантика `amount` заточены под звёзды. Для мульти-валюты понадобится правка DTO/
  getter/окна — это by design тонкого шаблона (одна reference-фича = один сценарий), но потребитель
  должен это осознавать. CONF=high, SEV=info.
- **`provider.py` фичи — Scope.REQUEST**, `BackendProvider` — Scope.APP (`backend/provider.py:13`).
  Это корректная иерархия: APP-клиент переиспользуется, usecase/gateway пересоздаются на Update.
  Замечу для смежной области (t-platform): единственный `BackendClient`/`BackendProvider` означает,
  что фича payments не может ходить в *другой* платёжный API, не заведя второй клиент — но для
  тонкого шаблона с одним бэкендом это норм by design.
- **Тесты адекватны, но клик «Купить» не покрыт.** `test_payments_flow.py:1-5` честно отмечает, что
  `on_buy`/`send_invoice` не тестируется (требует реального бота). HIGH-находка (потеря fulfill) и
  MEDIUM (`message is None`) находятся именно в непокрытой зоне — нет flow-теста на
  `on_successful_payment` с падающим `fulfill`. Покрытие `policy`/`confirm` — хорошее.

## Ответ на вопросы заказчика (в этой области)

1. **Можно ли строить нормальных ботов?** Да — для платёжного флоу архитектура зрелая: правильное
   «не доверять клиенту», fail-closed pre_checkout, дедуп at-least-once, идемпотентный fulfill,
   чистый гексагон. Это заметно выше среднего уровня реализаций Telegram-платежей. НО есть один
   реальный correctness-баг (HIGH: окно потери выдачи при сбое `fulfill`), который для платежей
   критичен и должен быть закрыт до прода.
2. **Насколько гибкая?** Внутри парадигмы «Telegram Stars / один backend-API» — гибкая и чистая:
   порт/usecase/policy легко переиспользовать, kit-примитивы переносимы. За пределы Stars (фиат,
   мульти-валюта, несколько платёжных провайдеров) — потребуется ручная доработка DTO/getter/окна:
   `amount: int` и presentation заточены под звёзды. Это осознанный trade-off тонкого reference-
   шаблона, не дефект, но и не «из коробки мультивалютно».
3. **Про один `BackendClient`/`BackendProvider`** (смежно): для payments это не мешает — фича ходит
   в один бэкенд через узкий порт. Если у заказчика платежи и, скажем, контент-API — это **разные**
   внешние сервисы, текущий единственный APP-scope `BackendClient` придётся размножать (второй
   провайдер/второй клиент). Это симптом «один бэкенд by design», а не негибкости *фичи* payments —
   разбор по существу в области t-platform.
