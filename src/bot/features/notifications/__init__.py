"""Фасад фичи notifications: build_router(cache, redis) → Notifier для NotifierBundle.

Не dishka-Provider: Notifier'у нужны cache+redis из контейнера, поэтому его собирает
ExtensionProvider (см. bot/app.py), вызывая build_router. Какие stream/subject/durable
и deliver_* — здесь; механика подписки/доставки/drain — в tgbotkit.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from pylibinfra.cachekit import Cache
from pylibinfra.tgbotkit import DeliveryDedup, LocalePrefStore, NotificationRouter

from bot.features.notifications.deliver import OrderDeliverer


def build_router(cache: Cache, client: aioredis.Redis) -> NotificationRouter:
    router = NotificationRouter()
    deliverer = OrderDeliverer(cache, DeliveryDedup(client), LocalePrefStore(cache))
    # stream=orders, subject=orders.paid, durable=bot-orders-paid (JetStream explicit-ack)
    router.on("orders", "orders.paid", "bot-orders-paid", deliverer.on_order_paid)
    return router


__all__ = ["OrderDeliverer", "build_router"]
