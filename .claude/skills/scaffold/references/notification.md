# scaffold › notification — NATS-подписчик → сообщение/диалог

Добавляет реакцию на **событие бэкенда** (NATS-subject) → push в Telegram через `BgManager`. Образец — `features/notifications/` (`build_router` + `deliver.py`). Подписка/доставка/drain/ack — в `tgbotkit` (`NotificationRouter`/`NotificationRunner`/`Delivery`); в шаблоне — **какие subject'ы и что слать**. Соответствует rule `background-updates` (фон не проходит обычные middleware).

> Транспорт push — **JetStream durable + explicit ack** (надёжная доставка), core — для эфемерных. Выбор — `docs/stack/messaging.md`.

## Когда применять

- «Когда бэкенд эмитит `orders.paid` — слать юзеру подтверждение».
- «При событии `subscription.expiring` — напомнить продлить».
- «Push при изменении статуса заказа».

## Когда НЕ применять

- По таймеру, не по событию → `references/job.md`.
- Реакция в контексте апдейта (синхронно) → метод usecase.
- Нужна новая **механика** доставки (новый вид ack, свой dedup-движок) → это PR в `tgbotkit` (`infra-handoff`), не код шаблона.

## 1. Подтвердить контракт события

- `stream` / `subject` / `durable`-имя (формат durable у бота: `bot-<subject-kebab>`).
- Форма payload (минимум: id агрегата + `user_ref` для резолва chat_id).
- Идемпотентность: at-least-once (JetStream) — дедуп по чему (`event_id`/`order_id`)?
- Как резолвить `chat_id` адресата (обычно `link:chat:<user_ref>`, пишется при онбординге — `platform/links.py`)?

## 2. Deliverer — что слать (бизнес)

В `features/notifications/deliver.py` (или новый `*_deliver.py`, если файл разрастается). Получает распарсенный `payload` и `Delivery` (безопасная обёртка над `BgManager` — грабли request_id/локали/пустого стека/throttle закрыты в ней):

```python
from typing import Any
from pylibinfra.cachekit import Cache
from pylibinfra.tgbotkit import Delivery, DeliveryDedup
from bot.platform.links import chat_link_key


class SubExpiringDeliverer:
    def __init__(self, cache: Cache, dedup: DeliveryDedup) -> None:
        self._cache, self._dedup = cache, dedup

    async def on_expiring(self, payload: Any, delivery: Delivery) -> None:
        if not isinstance(payload, dict):
            return
        event_id = str(payload.get("event_id", ""))
        user_ref = str(payload.get("user_ref", ""))
        if not event_id or not user_ref:
            return
        if await self._dedup.seen(f"sub-expiring:{event_id}"):  # at-least-once дедуп
            return
        chat_id = await self._lookup_chat(user_ref)
        if chat_id is None:
            return  # нет link — тихо пропускаем
        await delivery.send_message(chat_id=chat_id, text="⏳ Подписка скоро истекёт.")

    async def _lookup_chat(self, user_ref: str) -> int | None:
        raw, found = await self._cache.get(chat_link_key(user_ref))
        if not found or raw is None:
            return None
        try:
            return int(raw.decode())
        except ValueError:
            return None
```

**Если нужно показать/обновить диалог** (не просто текст) — `Delivery` оборачивает `BgManager` для `bg().start(...)`/обновления. Помни грабли: EDIT не гарантирован (сообщение могло быть удалено), пустой стек безопасен, фон вне middleware → локаль/request_id руками (это уже внутри `Delivery`).

## 3. Зарегистрировать subject в router

В `features/notifications/__init__.py` (`build_router`) — добавь подписку:

```python
def build_router(cache: Cache, client: aioredis.Redis) -> NotificationRouter:
    router = NotificationRouter()
    deliverer = OrderDeliverer(cache, DeliveryDedup(client))
    router.on("orders", "orders.paid", "bot-orders-paid", deliverer.on_order_paid)
    # ↓ новая подписка
    sub = SubExpiringDeliverer(cache, DeliveryDedup(client))
    router.on("subscriptions", "subscription.expiring", "bot-sub-expiring", sub.on_expiring)
    return router
```

`NotificationRouter.on(stream, subject, durable, handler)` — точка расширения; handler = `async (payload, delivery)`. `NotifierBundle` уже собирается в `ExtensionProvider.notifiers` (`app.py`) через `build_router`. `OptionalStreamBus` отдаётся только при включённом JetStream (иначе None → runner пропускает notifications — `ExtensionProvider.stream_bus`).

## 4. Резолв chat_id — общий контракт

`chat_id` берётся из `link:chat:<user_ref>`, который **пишет онбординг** (`start/infra/store.py: CacheOnboardingStore.mark_onboarded` → `chat_link_key`). Если новый источник `user_ref` не совпадает с тем, что пишет start, — заведи запись link на своём пути линковки, иначе доставка молча пропускается (нет адресата). Это продуктовый маппинг, живёт в `deliver.py`/`platform/links.py`.

## 5. Тесты + верификация

- unit-тест deliverer (образец `tests/unit/test_notifications.py`): фейк `Cache` + фейк `Delivery` (`tests/_fakes/delivery.py`) + фейк dedup. Проверь: дедуп срабатывает (второй вызов — no-op), нет link → no send, happy path → один send с нужным текстом/chat_id.
- идемпотентность (at-least-once): два одинаковых payload → одна доставка.
- `make check`. Новый/изменённый subject — это инфра-поверхность → `infra-handoff` (cross-service NATS-subject).

`feat(notifications): deliver subscription.expiring push`

## Anti-patterns

- ❌ `bot.send_message` напрямую вместо `Delivery` — потеряешь корреляцию, наткнёшься на throttle, фон вне middleware.
- ❌ Без дедупа на at-least-once subject — пользователь получит дубли.
- ❌ Тяжёлая логика в deliverer (генерация отчёта) — он должен быть быстрым; вынеси в usecase/джобу.
- ❌ Резолв адресата мимо `link:chat:*` — рассинхрон с тем, что пишет онбординг → тихие пропуски.
- ❌ Новая механика доставки (свой ack/dedup-движок) в шаблоне — это PR в `tgbotkit`.
- ❌ Менять формат subject/payload без согласования с владельцем бэкенда (cross-service контракт → `infra-handoff`).
