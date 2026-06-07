"""Unit: payments.handlers — error/edge-ветки dispatcher- и dialog-level хендлеров.

Хендлеры обёрнуты dishka @inject: зависимости резолвятся из request-контейнера
(`dishka_container` для dispatcher-level, `manager.middleware_data` для dialog-level).
Собираем APP-контейнер с фейками инфры (FakeBot/FakeRedis) и подменённым PaymentsUsecase.

Покрываем:
- on_buy: callback без message (инвойс не шлём, но answer есть) и happy-path send_invoice;
- on_pre_checkout: decide=True/False/исключение → answer_pre_checkout_query(ok=...) fail-closed;
- on_successful_payment: sp=None ранний выход; reserve=False (дубликат); commit после выдачи;
  release+raise при сбое complete.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import redis.asyncio as aioredis
from aiogram import Bot
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from pylibinfra.logkit import nop
from tests._fakes.redis import FakeRedis

from bot.features.payments import errors, handlers
from bot.features.payments.dto import Order
from bot.features.payments.usecase import PaymentsUsecase

pytestmark = pytest.mark.unit

_ORDER = Order(order_id="o1", title="Премиум", description="30д", amount=100, currency="XTR")


class _Gateway:
    def __init__(self, order: Order | None = None, fulfill_error: Exception | None = None) -> None:
        self._order = order
        self._fulfill_error = fulfill_error
        self.fulfilled: list[tuple[str, str]] = []

    async def get_offer(self, offer_id: str) -> Order:
        assert self._order is not None
        return self._order

    async def fulfill(self, order_id: str, charge_id: str) -> None:
        if self._fulfill_error is not None:
            raise self._fulfill_error
        self.fulfilled.append((order_id, charge_id))


class _FakeBot:
    def __init__(self) -> None:
        self.invoices: list[tuple[int, dict[str, Any]]] = []
        self.pre_checkout: list[tuple[str, bool]] = []

    async def send_invoice(self, chat_id: int, **invoice: Any) -> None:
        self.invoices.append((chat_id, invoice))

    async def answer_pre_checkout_query(
        self, query_id: str, *, ok: bool, error_message: str | None = None
    ) -> None:
        self.pre_checkout.append((query_id, ok))


class _Deps(Provider):
    scope = Scope.APP

    def __init__(self, gateway: _Gateway, bot: _FakeBot, redis: FakeRedis) -> None:
        super().__init__()
        self._gateway = gateway
        self._bot = bot
        self._redis = redis

    @provide
    def usecase(self) -> PaymentsUsecase:
        return PaymentsUsecase(self._gateway, nop())  # type: ignore[arg-type]

    @provide
    def bot(self) -> Bot:
        return self._bot  # type: ignore[return-value]

    @provide
    def redis(self) -> aioredis.Redis:
        return self._redis  # type: ignore[return-value]


def _container(gateway: _Gateway, bot: _FakeBot, redis: FakeRedis) -> AsyncContainer:
    return make_async_container(_Deps(gateway, bot, redis))


class _Callback:
    def __init__(self, message: Any) -> None:
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


async def test_on_buy_sends_invoice_and_answers() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_ORDER), bot, FakeRedis())
    cb = _Callback(SimpleNamespace(chat=SimpleNamespace(id=555)))
    async with container() as rc:
        manager = SimpleNamespace(middleware_data={"dishka_container": rc})
        await handlers.on_buy(cb, None, manager)  # type: ignore[arg-type]
    assert bot.invoices[0][0] == 555
    assert bot.invoices[0][1]["payload"] == "o1"  # связь с pre_checkout/successful_payment
    assert cb.answered is True
    await container.close()


async def test_on_buy_without_message_skips_invoice_but_answers() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_ORDER), bot, FakeRedis())
    cb = _Callback(message=None)  # инлайн-сообщение могло быть удалено
    async with container() as rc:
        manager = SimpleNamespace(middleware_data={"dishka_container": rc})
        await handlers.on_buy(cb, None, manager)  # type: ignore[arg-type]
    assert bot.invoices == []
    assert cb.answered is True
    await container.close()


async def _pre_checkout(gateway: _Gateway, *, amount: int, currency: str) -> list[tuple[str, bool]]:
    bot = _FakeBot()
    container = _container(gateway, bot, FakeRedis())
    query = SimpleNamespace(id="pq1", invoice_payload="o1", total_amount=amount, currency=currency)
    async with container() as rc:
        await handlers.on_pre_checkout(query, dishka_container=rc)  # type: ignore[arg-type]
    await container.close()
    return bot.pre_checkout


async def test_on_pre_checkout_confirms_matching_amount() -> None:
    assert await _pre_checkout(_Gateway(_ORDER), amount=100, currency="XTR") == [("pq1", True)]


async def test_on_pre_checkout_rejects_wrong_amount() -> None:
    # клиент прислал заниженную сумму — не доверяем, сверка с бэкендом → отказ
    assert await _pre_checkout(_Gateway(_ORDER), amount=50, currency="XTR") == [("pq1", False)]


async def test_on_pre_checkout_fails_closed_on_backend_error() -> None:
    class _Down:
        async def get_offer(self, offer_id: str) -> Order:
            raise errors.PaymentError("down")

        async def fulfill(self, order_id: str, charge_id: str) -> None:
            pass

    assert await _pre_checkout(_Down(), amount=100, currency="XTR") == [("pq1", False)]  # type: ignore[arg-type]


def _payment_message(sp: Any) -> Any:
    return SimpleNamespace(successful_payment=sp)


async def _complete(gateway: _Gateway, message: Any, redis: FakeRedis) -> None:
    container = _container(gateway, _FakeBot(), redis)
    try:
        async with container() as rc:
            await handlers.on_successful_payment(message, dishka_container=rc)  # type: ignore[arg-type]
    finally:
        await container.close()


async def test_on_successful_payment_no_sp_returns() -> None:
    # message без successful_payment — ранний выход, выдачи нет
    gw = _Gateway(_ORDER)
    await _complete(gw, _payment_message(None), FakeRedis())
    assert gw.fulfilled == []


async def test_on_successful_payment_fulfills_and_commits() -> None:
    gw = _Gateway(_ORDER)
    redis = FakeRedis()
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    await _complete(gw, _payment_message(sp), redis)
    assert gw.fulfilled == [("o1", "charge-1")]
    assert redis.store["tg:charge:charge-1"] == b"1"  # commit оставил ключ


async def test_on_successful_payment_duplicate_skips_fulfill() -> None:
    gw = _Gateway(_ORDER)
    redis = FakeRedis()
    redis.store["tg:charge:charge-1"] = b"1"  # ключ уже занят → reserve вернёт дубликат
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    await _complete(gw, _payment_message(sp), redis)
    assert gw.fulfilled == []  # at-least-once: повтор апдейта не выдаёт второй раз


async def test_on_successful_payment_releases_on_failure() -> None:
    gw = _Gateway(_ORDER, fulfill_error=errors.PaymentError("backend down"))
    redis = FakeRedis()
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    with pytest.raises(errors.PaymentError):
        await _complete(gw, _payment_message(sp), redis)
    # сбой выдачи → ключ снят, чтобы повтор апдейта смог выдать
    assert "tg:charge:charge-1" not in redis.store
