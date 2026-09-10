"""deliver.py — доставка событий бэкенда в Telegram (deliver_*).

Каждый deliver получает распарсенный payload и Delivery (безопасная обёртка над BgManager).
Грабли фона (request_id/локаль/пустой стек) закрыты в Delivery — здесь только бизнес: дедуп
(at-least-once JetStream: резерв с токеном → доставка → commit), резолв chat_id по link tg→chat
(его пишет start при онбординге), отправка. Маппинг user_ref→chat_id — продуктовый, живёт тут.
"""

from __future__ import annotations

from typing import Any

from pylibinfra.cachekit import Cache
from pylibinfra.logkit import Logger
from pylibinfra.tgbotkit import Delivery, DeliveryDedup, LocalePrefStore

from bot.platform.links import chat_link_key


class OrderDeliverer:
    def __init__(
        self, cache: Cache, dedup: DeliveryDedup, locales: LocalePrefStore, log: Logger
    ) -> None:
        self._cache = cache
        self._dedup = dedup
        self._locales = locales
        self._log = log

    async def on_order_paid(self, payload: Any, delivery: Delivery) -> None:
        order_id = str(payload.get("order_id", "")) if isinstance(payload, dict) else ""
        user_ref = str(payload.get("user_ref", "")) if isinstance(payload, dict) else ""
        if not order_id or not user_ref:
            return
        chat_id = await self._lookup_chat(user_ref)
        if chat_id is None:
            return  # нет link tg→chat (пользователь не онбордился) — тихо пропускаем
        key = f"order-paid:{order_id}"
        token = await self._dedup.reserve(key)
        if token is None:
            return  # уже доставлено или доставка в процессе у другого консьюмера
        try:
            # фон вне I18nMiddleware → локаль резолвим сами: chat_id == user_id для DM
            locale = await self._locales.get(chat_id)
            text = delivery.localize(locale, "notifications-order-paid", {"order_id": order_id})
            await delivery.send_message(chat_id=chat_id, text=text)
        except Exception:
            await self._dedup.release(key, token)  # сбой доставки → JsBus nak → redelivery повторит
            raise
        if not await self._dedup.commit(key, token):
            # резерв истёк на медленной доставке и ушёл соседнему воркеру — push мог задвоиться
            self._log.warn("notifications.reservation_lost", key=key, chat_id=chat_id)

    async def _lookup_chat(self, user_ref: str) -> int | None:
        raw = await self._cache.get(chat_link_key(user_ref))
        if raw is None:
            return None
        try:
            return int(raw.decode())
        except ValueError:
            return None
