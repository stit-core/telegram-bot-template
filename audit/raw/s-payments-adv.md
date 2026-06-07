# Стресс-тест: нетривиальные платежи (id=s-payments-adv)

## Сценарий

Пройти по реальному коду фичи `payments` и kit-механики платежей **четыре** платёжных сценария за
пределами «одноразовый Stars-платёж»:

1. **Подписки (recurring)** — Telegram Stars subscription (`subscription_period`), продление,
   `is_recurring`/`is_first_recurring`, отмена.
2. **Возвраты (refund)** — `refund_star_payment`, апдейт `message.refunded_payment`.
3. **Частичные оплаты** — несколько `LabeledPrice`, чаевые (`max_tip_amount`/`suggested_tip_amounts`),
   частичный refund.
4. **НЕ Telegram Stars** — внешний фиатный провайдер (`provider_token`), мультивалюта с сотыми
   долями (минорные единицы — центы/копейки).

Дополнительно — состояние платежа, сверка с провайдером (reconciliation), идемпотентность при
ретраях, и известный HIGH-баг «окно потери fulfill».

## Что смотрел (по реальному коду, обоих репо)

Фича целиком: `features/payments/{dto,state,ports,errors,policy,usecase,gateway,getters,views,
dialogs,handlers,provider,__init__}.py`. Kit-механика: `tgbotkit/payments/{invoice,precheckout,
guard}.py` + `metrics.py` + `extension.py` (CommandSpec). Платформа: `platform/backend/{client,
errors}.py`. Тесты: `tests/unit/test_payments.py`, `tests/flows/test_payments_flow.py`.

Эмпирика (template `.venv`, aiogram 3.28.2, python3.13):
- Проверил API-поверхность aiogram: `Bot.refund_star_payment` ✅, `Bot.edit_user_star_subscription`
  ✅, `Bot.get_star_transactions` ✅, `Bot.create_invoice_link` ✅ — **всё это уже есть в фреймворке**.
- `SuccessfulPayment` несёт `subscription_expiration_date`, `is_recurring`, `is_first_recurring`,
  `provider_payment_charge_id`, `order_info` — модель полная.
- `Message.refunded_payment` ✅ существует (апдейт о возврате доходит).
- **`Bot.send_invoice` НЕ принимает `subscription_period`** (нет в сигнатуре); `subscription_period`
  есть **только** у `Bot.create_invoice_link`. Это ключевой структурный факт для recurring.
- `Bot.send_invoice` принимает `max_tip_amount`/`suggested_tip_amounts`/`provider_token`/
  `provider_data` — то есть фиат и чаевые упираются не в фреймворк, а в kit-обёртку `build_invoice`.
- Прогнал `pytest tests/unit/test_payments.py tests/flows/test_payments_flow.py` → **6 passed**
  (green-baseline зафиксирован).
- `grep -rniE "refund|subscription|recurring|provider_token|cents|minor"` по `src` обоих репо: ни
  одного попадания, кроме `provider_token` в `invoice.py` и одного `USD` в тесте. **Refund/recurring/
  минорные единицы в коде отсутствуют как класс.**

Примечание: `docs/` намеренно очищен — отсутствие документации платежей НЕ считаю находкой.

## Краткий вердикт по сценариям

| Сценарий | Вердикт | Где ломается |
|---|---|---|
| Одноразовый Stars (baseline) | **supported** | работает, чисто (но HIGH-баг fulfill — ниже) |
| Фиат (`provider_token`, не-XTR) | **awkward** | `build_invoice` умеет токен, но `amount:int`/`policy`/presentation заточены под звёзды; минорные единицы не различаются |
| Мультивалюта с сотыми долями | **awkward→blocked** | нет понятия минорной единицы; `policy.amount_matches`/getter/`💎{amount}⭐` ломаются на центах |
| Частичные оплаты / чаевые | **awkward** | один `LabeledPrice` хардкодом; tip не сверяется policy → дыра в «не доверять клиенту» |
| Refund (возврат) | **blocked** | нет порта, нет usecase, нет апдейт-хендлера `refunded_payment`, нет вызова `refund_star_payment`, нет состояния платежа |
| Recurring (подписка) | **blocked** | механика построена на `send_invoice`, а recurring требует `create_invoice_link(subscription_period=…)`; guard-дедуп по `charge_id` не различает первый платёж и продление; нет `edit_user_star_subscription` |

Итоговый вердикт стресса: **blocked** для refund/recurring, **awkward** для фиата/мультивалюты/
частичных. Одноразовый Stars — supported, но с непочиненным HIGH-багом потери выдачи.

---

## BREAKING_POINTS

### [SEV=high] Recurring структурно невозможен через текущую механику: `build_invoice`→`send_invoice`, а подписка требует `create_invoice_link(subscription_period)`
`tgbotkit/payments/invoice.py:13-33`, `features/payments/handlers.py:37-45`

`build_invoice` собирает kwargs **ровно под `bot.send_invoice`** (`invoice.py:25-32`: title/
description/payload/currency/prices/provider_token), а `on_buy` зовёт `bot.send_invoice(...)`
(`handlers.py:45`). Эмпирически проверено: `Bot.send_invoice` **не имеет** параметра
`subscription_period` — он есть **только** у `Bot.create_invoice_link`. Telegram Stars subscription
оформляется именно через ссылку-инвойс с периодом, не через `send_invoice`. Значит для подписки
надо: (а) новый kit-примитив `build_subscription_link`/`create_invoice_link`-путь, (б) другой
дизайн UX (ссылка вместо инлайн-инвойса). Текущая обёртка это не покрывает и не параметризуется до
этого.
**workaround:** обойти `build_invoice`, вызвать `bot.create_invoice_link(subscription_period=…)`
руками в хендлере — но это инфра-вызов в шаблоне (нарушает границу tgbotkit↔шаблон, rule
`tgbotkit-boundary`), плюс дублирует то, что должно жить в kit. Чистого обхода нет → kit-доработка.

### [SEV=high] Дедуп `guard_charge` по `telegram_payment_charge_id` ломает recurring: каждое продление — новый charge, но `is_recurring`/первый платёж неразличимы, а fulfill один на всех
`tgbotkit/payments/guard.py:23-28`, `features/payments/handlers.py:60-73`, `usecase.py:32-34`

`on_successful_payment` дедупит по `charge_id` и зовёт `uc.complete(payload, charge_id)`. Для
подписки Telegram присылает `successful_payment` **на каждое продление** с **новым** charge_id и
флагами `is_recurring=True`/`is_first_recurring`. Текущий код их **не читает** (`handlers.py:67` —
берёт только `telegram_payment_charge_id`), `fulfill(order_id, charge_id)` идемпотентен **по
charge_id** (`gateway.py:29-34`), а `order_id` = `invoice_payload` — один и тот же на все продления.
Итог: бэкенд не получает сигнала «это N-е продление подписки до даты X», а только повторный fulfill
того же `order_id` с разными charge_id. Бизнес-логику «продлить доступ до
`subscription_expiration_date`» построить не на чем — поле не пробрасывается.
**workaround:** читать `sp.is_recurring`/`sp.subscription_expiration_date` руками и расширить порт —
но это уже новая бизнес-модель платежа, а не правка. Чистого нет.

### [SEV=high] Refund — отсутствует целиком: нет порта, usecase, апдейт-хендлера и вызова `refund_star_payment`
`features/payments/ports.py:14-17`, `features/payments/__init__.py:16-19`, весь kit `tgbotkit/payments/`

Порт `PaymentsGateway` знает только `get_offer`/`fulfill` (`ports.py:15-17`) — **нет** `refund`. В
`command_specs` зарегистрированы только `pre_checkout_query` и `message+F.successful_payment`
(`__init__.py:17-18`) — **нет** `message+F.refunded_payment` (а `Message.refunded_payment` в
aiogram 3.28 существует, проверено). Нигде не вызывается `bot.refund_star_payment(user_id,
charge_id)` (его наличие в Bot подтверждено). Возврат — это: (1) инициатива (бот/саппорт жмёт
«вернуть») → вызов `refund_star_payment`; (2) реакция на апдейт `refunded_payment` → ревок выдачи на
бэкенде. **Оба контура отсутствуют как класс.** CommandSpec **технически** позволяет
зарегистрировать `refunded_payment` (observer — просто строка `"message"` + фильтр), но ни хендлера,
ни порт-метода, ни kit-обёртки нет.
**workaround:** дописать порт + usecase + gateway-метод + dispatcher-хендлер + CommandSpec + kit-
guard для дедупа refund-апдейта. Это полноценный вертикальный срез, не обход.

### [SEV=high] Окно потери fulfill (подтверждаю known HIGH): guard ставит ключ ДО `complete`, ошибка fulfill → деньги списаны, выдачи нет, Telegram-redelivery заглушён
`features/payments/handlers.py:71-73`, `tgbotkit/payments/guard.py:23-28`, `gateway.py:29-37`

```python
if await guard_charge(client, sp.telegram_payment_charge_id):  # SET NX — ставит ключ ПЕРВЫМ
    return
await uc.complete(sp.invoice_payload, sp.telegram_payment_charge_id)  # может бросить PaymentError
```
`guard_charge` (`guard.py:24`) делает `SET NX EX` сразу (TTL 7д). Затем `uc.complete`→`gateway.fulfill`
бросает `PaymentError` при `BackendUnavailable` (breaker-open/5xx/timeout, `gateway.py:36-37`).
Исключение не ловится в хендлере → всплывает в recovery-middleware kit'а и проглатывается. Telegram
по at-least-once присылает тот же `successful_payment` снова — но `guard_charge` теперь вернёт `True`
→ хендлер выходит на `return`, **выдачи опять нет**. Авто-восстановления нет; дедуп-ключ маскирует
ретрай. Для подписок/частичных это окно **умножается** (больше successful_payment-событий = больше
шансов попасть в сбой). Усугубляет: `BackendConflict` (409 — штатный ответ на идемпотентный повтор
fulfill) `payments/gateway.py` **не ловит** (`gateway.py:36` ловит только `BackendUnavailable`) →
всплывёт как паника.
**workaround:** «mark-after-success» — сначала `complete`, потом ставить ключ; либо при ошибке
fulfill `DEL tg:charge:*`. Решение совместное kit (`guard_charge` → reserve/commit) + шаблон. Это
известная находка t-feat-payments/d-resilience; подтверждаю на коде.

### [SEV=high] Фиат/мультивалюта: `amount: int` перегружен — для XTR это звёзды, для USD это центы; ничто в коде не различает минорную единицу
`features/payments/dto.py:16`, `policy.py:10-11`, `dialogs.py:15`, `getters.py:20`, `invoice.py:30`

`Order.amount: int` (`dto.py:16`) документирован как «звёзды XTR» (`dto.py:3`). Для фиата Telegram
требует сумму в **минорных единицах** (центы для USD/EUR, при этом валюты вроде JPY/UGX имеют 0
знаков, а KWD/BHD — 3). `policy.amount_matches(expected, got)` (`policy.py:10`) сравнивает голые
int'ы — это корректно для сверки, но **семантика суммы теряется**: одно и то же поле означает то
звёзды, то центы, и presentation `💎 {amount} ⭐` (`dialogs.py:15`) хардкодит звёздную подачу. Getter
кладёт `amount` сырым (`getters.py:21`→`views.to_offer`). `build_invoice` сбрасывает токен только
для XTR (`invoice.py:24`) — токен поддержан, но `LabeledPrice(amount=amount)` (`invoice.py:30`) уйдёт
с центами без какого-либо различения exponent'а валюты. Нет типа `Money`/(currency, minor_units).
Для мультивалюты с сотыми долями это **breaking**: придётся переделать DTO (`amount`→`Money`),
policy, getter, presentation и `.ftl`.
**workaround:** для одной фиксированной фиат-валюты — терпимо (трактовать `amount` как центы и
поправить presentation). Для **мульти**-валюты с разными exponent'ами — нет чистого обхода без
ввода понятия минорной единицы.

### [SEV=medium] Частичные оплаты / чаевые: `build_invoice` — ровно один `LabeledPrice`, а tip не сверяется в pre_checkout → дыра в «не доверять клиенту»
`tgbotkit/payments/invoice.py:30`, `features/payments/usecase.py:25-30`, `policy.py:10`

`build_invoice` собирает `prices=[LabeledPrice(label, amount)]` — **один** прайс (`invoice.py:30`),
нет приёма списка позиций (частичная/составная оплата = несколько `LabeledPrice`). При включённых
чаевых (`max_tip_amount`) пользователь добавляет чаевые → `pre_checkout.total_amount` =
base+tip > `order.amount`. Текущий `confirm` (`usecase.py:30`) делает `policy.amount_matches(order.
amount, total_amount)` = строгое равенство (`policy.py:11`: `got == expected`) → **любой платёж с
чаевыми будет отклонён** (false-reject), либо, если кто-то ослабит проверку до `>=`, открывается
дыра: tip не верифицируется, клиент может прислать произвольную «надбавку». Механика заточена под
fixed-amount без tip и без позиций.
**workaround:** расширить `build_invoice` (принимать `prices: list`/`max_tip_amount`) и policy
(разделить base/tip-диапазон) — это правка kit + policy, не обход.

### [SEV=medium] Нет понятия «состояние платежа» и сверки с провайдером (reconciliation): платёж — fire-and-forget, нет `get_star_transactions`/статуса
`features/payments/usecase.py:32-34`, `ports.py:14-17`, весь kit `tgbotkit/payments/`

Платёж не имеет состояния: `confirm`→`complete` и всё. Нет сущности «платёж со статусом»
(pending/paid/fulfilled/refunded/failed), нет порта на чтение статуса, нет периодической сверки.
Для подписок/refund это критично: продление/возврат меняют состояние во времени, и без
reconciliation (напр. через `bot.get_star_transactions` — метод есть в aiogram, проверено, но нигде
не используется) расхождение «деньги списаны / выдачи нет» (см. HIGH про fulfill) **никогда не
закроется автоматически**. Метрика успешной выдачи `payments_total{stage=paid,result=ok}` тоже не
эмитится (`metrics.py:37`, есть только `pre_checkout` и `duplicate` в `guard.py:27`) → инцидент
невидим. Для нетривиальных платежей отсутствие state-machine + reconciliation — архитектурный
пробел, а не недосмотр в одной строке.
**workaround:** ввести платёж-сущность и reconciliation-джобу (timerkit) + порт на статус. Это новая
подсистема, не обход.

### [SEV=low] Recurring-апдейты не различает CommandSpec-фильтр: `F.successful_payment` ловит и первый платёж, и продление одинаково
`features/payments/__init__.py:18`, `handlers.py:60-73`

`CommandSpec("message", on_successful_payment, (F.successful_payment,))` ловит **любой**
successful_payment. Для подписки это и есть проблема: первый платёж и каждое продление идут одним
хендлером, который не ветвится по `is_first_recurring`/`is_recurring`. Технически фильтр можно
разделить (`F.successful_payment.is_recurring`), но текущий код одну ветку обрабатывает как все.
**workaround:** ветвление по флагам в хендлере + расширение порта — правка фичи.

---

## REQUIRED_CHANGES

Чтобы нетривиальные платежи стали «чистыми», нужно (kit и шаблон — раздельно):

**В kit (`pylibinfra/tgbotkit/payments/`) — новая generic-механика (PR через infra-handoff):**
1. `build_subscription_link` / путь через `create_invoice_link(subscription_period=…)` — recurring
   физически невозможен на `send_invoice`.
2. `build_invoice`: принимать `prices: list[LabeledPrice]` (составные/частичные), `max_tip_amount`/
   `suggested_tip_amounts` (чаевые), и **тип валюты с exponent** (минорные единицы) вместо голого
   `amount: int`.
3. `refund_charge`-обёртка над `bot.refund_star_payment` + guard-дедуп для апдейта
   `refunded_payment` (атомарный по charge_id, но **отдельный** namespace от fulfill-guard).
4. `guard_charge` → reserve/commit (mark-after-success), чтобы закрыть окно потери fulfill **и** не
   ломать recurring (каждое продление — свой commit).
5. Метрики: `payments_total{stage=paid,result=ok}`, `{stage=refund}`, `{stage=renewal}`; добавить
   лейбл провайдера/валюты при необходимости.
6. (опц.) обёртка над `get_star_transactions` для reconciliation.

**В шаблоне (`features/payments/`):**
1. `dto.py`: `amount: int` → `Money(amount_minor: int, currency: str)` (или `Field(gt=0)` как
   минимум) с понятием exponent; различать XTR/фиат в presentation (`dialogs.py`/`.ftl`).
2. `ports.py`: добавить `refund(order_id, charge_id)`, `renew(order_id, charge_id, expires_at)`,
   `payment_status(order_id)`; gateway-реализации + маппинг `BackendConflict`→«уже выполнено».
3. `policy.py`: сверка с учётом валюты (перенести из usecase) + диапазон tip/частичной оплаты.
4. `handlers.py`: ветвить `successful_payment` по `is_recurring`/`is_first_recurring`, читать
   `subscription_expiration_date`/`provider_payment_charge_id`; новый хендлер на `refunded_payment`;
   ловить `PaymentError` вокруг `complete` (закрыть окно потери).
5. `__init__.py`: `CommandSpec("message", on_refund, (F.refunded_payment,))` + разделить
   recurring-фильтр.
6. Состояние платежа (если бизнесу нужно): сущность + reconciliation-джоба.
7. Тесты: refund-флоу, recurring-продление, фиат-минорные-единицы, fail-fulfill (regression на
   HIGH-баг) — сейчас покрыты только policy/confirm на XTR.

Объём работ: **значительный**. Для одноразового Stars шаблон — образцовый reference. Для refund/
recurring это **новая подсистема в kit + переписанный вертикальный срез в шаблоне** (не «допилить
параметр»). Для фиата/мультивалюты — переделка модели суммы сквозь DTO/policy/getter/presentation.
Это **осознанный trade-off тонкого reference-шаблона** («одна reference-фича = один сценарий»), но
потребитель должен понимать: «из коробки» он получает только одноразовый Stars.

---

## FINDINGS

- [SEV=high|CAT=flexibility|CONF=high|KEY=yes] Recurring структурно невозможен через `build_invoice`/`send_invoice` :: `tgbotkit/payments/invoice.py:13-33`, `handlers.py:37-45` (send_invoice не имеет subscription_period; он только у create_invoice_link — проверено эмпирически) :: подписки требуют другого Telegram-API и другого UX-пути, текущая обёртка их не покрывает :: fix: kit-примитив `build_subscription_link` через `create_invoice_link(subscription_period)`.
- [SEV=high|CAT=flexibility|CONF=high|KEY=yes] Refund отсутствует как класс — нет порта, usecase, апдейт-хендлера и вызова `refund_star_payment` :: `ports.py:14-17`, `__init__.py:16-19`, весь kit `tgbotkit/payments/` :: возврат денег нельзя ни инициировать, ни обработать (`Message.refunded_payment` не слушается, хотя поле есть в aiogram 3.28) :: fix: добавить refund-порт+usecase+gateway+CommandSpec(`F.refunded_payment`)+kit-обёртку `refund_charge`.
- [SEV=high|CAT=correctness|CONF=high|KEY=yes] Окно потери fulfill: `guard_charge` ставит ключ ДО `complete`, ошибка fulfill → деньги списаны, выдачи нет, redelivery заглушён :: `handlers.py:71-73`, `guard.py:23-28`, `gateway.py:36` (BackendConflict не ловится) :: транзиентный сбой backend на fulfill = потеря денег пользователя без авто-восстановления; для подписок умножается :: fix: mark-after-success (сначала complete, потом ключ) / reserve+commit в guard; ловить BackendConflict как «выполнено».
- [SEV=high|CAT=flexibility|CONF=high|KEY=no] `amount: int` перегружен (звёзды vs центы), нет понятия минорной единицы валюты :: `dto.py:16`, `policy.py:10`, `dialogs.py:15`, `invoice.py:30` :: мультивалюта с сотыми долями и разными exponent'ами (USD 2 / JPY 0 / KWD 3) ломает сверку и presentation :: fix: ввести `Money(amount_minor, currency)` с exponent сквозь DTO/policy/getter/presentation/`.ftl`.
- [SEV=medium|CAT=flexibility|CONF=high|KEY=no] Частичные/чаевые не поддержаны: `build_invoice` = один `LabeledPrice`, tip не сверяется policy (строгое `==`) :: `invoice.py:30`, `usecase.py:30`, `policy.py:11` :: платёж с чаевыми будет false-reject, а ослабление до `>=` открывает неверифицируемый tip :: fix: `prices: list` + `max_tip_amount` в build_invoice; разделить base/tip-диапазон в policy.
- [SEV=medium|CAT=architecture|CONF=high|KEY=no] Нет состояния платежа и reconciliation — fire-and-forget, `get_star_transactions` не используется :: `usecase.py:32-34`, `ports.py:14-17` :: для подписок/возвратов нужна state-machine + сверка с провайдером; иначе расхождение деньги/выдача не закрывается :: fix: платёж-сущность (pending/paid/fulfilled/refunded) + reconciliation-джоба (timerkit) + порт статуса.
- [SEV=medium|CAT=correctness|CONF=high|KEY=no] Recurring-метаданные не пробрасываются: `is_recurring`/`is_first_recurring`/`subscription_expiration_date` игнорируются, fulfill один на все продления :: `handlers.py:67`, `gateway.py:29-34` :: бэкенд не получает сигнала «N-е продление до даты X», бизнес-логику подписки построить не на чем :: fix: читать флаги SuccessfulPayment, расширить порт `renew(order_id, charge_id, expires_at)`.
- [SEV=low|CAT=flexibility|CONF=high|KEY=no] CommandSpec-фильтр `F.successful_payment` не различает первый платёж и продление :: `__init__.py:18`, `handlers.py:60-73` :: один хендлер обрабатывает первый платёж и каждое продление одинаково :: fix: ветвить по `is_first_recurring`/`is_recurring` в хендлере или фильтре.
- [SEV=info|CAT=flexibility|CONF=high|KEY=no] Фреймворк (aiogram 3.28) уже всё умеет — пробел в kit/шаблоне, не в Telegram-API :: эмпирически `Bot.refund_star_payment`/`edit_user_star_subscription`/`get_star_transactions`/`create_invoice_link` + `SuccessfulPayment.{is_recurring,subscription_expiration_date}` присутствуют :: значит нетривиальные платежи — реалистичная доработка kit'а, а не «нельзя в принципе» :: fix: kit-PR закрывает большинство пунктов аддитивно.
