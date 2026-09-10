"""Unit: payments.handlers — error/edge-ветки dispatcher- и dialog-level хендлеров.

Хендлеры обёрнуты dishka @inject: зависимости резолвятся из request-контейнера
(`dishka_container` для dispatcher-level, `manager.middleware_data` для dialog-level).
Собираем APP-контейнер с фейками инфры (FakeBot, MemoryRedis под гвардами) и подменённым
PaymentsUsecase.

Покрываем:
- on_buy: callback без message (инвойс не шлём, но answer есть) и happy-path send_invoice;
- on_pre_checkout: decide=True/False/исключение → answer_pre_checkout_query(ok=...) fail-closed;
- on_successful_payment: sp=None ранний выход; чужой резерв (дубликат); commit после выдачи;
  release+raise при сбое complete.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from pylibinfra.httpclient import UnavailableError
from pylibinfra.logkit import Logger, nop
from pylibinfra.testkit.bottest import MemoryRedis
from pylibinfra.tgbotkit import ChargeGuard, RefundGuard

from bot.features.payments import errors, handlers
from bot.features.payments.usecase import PaymentsUsecase
from bot.pkg.http_client.internal.payments import Charge, Offer
from bot.platform.identity import BotIdentity

pytestmark = pytest.mark.unit

_OFFER = Offer(id="o1", title="Премиум", description="30д", amount=100, currency="XTR")


class _Gateway:
    def __init__(
        self,
        offer: Offer | None = None,
        fulfill_error: Exception | None = None,
        payer: int | None = None,
    ) -> None:
        self._offer = offer
        self._fulfill_error = fulfill_error
        self._payer = payer
        self.fulfilled: list[tuple[str, str]] = []
        self.revoked: list[tuple[str, str]] = []

    async def get_offer(self, offer_id: str) -> Offer:
        assert self._offer is not None
        return self._offer

    async def fulfill_order(self, order_id: str, charge_id: str) -> None:
        if self._fulfill_error is not None:
            raise self._fulfill_error
        self.fulfilled.append((order_id, charge_id))

    async def revoke_order(self, order_id: str, charge_id: str) -> None:
        self.revoked.append((order_id, charge_id))

    async def find_charge(self, charge_id: str) -> Charge | None:
        return Charge(user_id=self._payer) if self._payer is not None else None


class _FakeBot:
    def __init__(self, refund_ok: bool = True) -> None:
        self.invoices: list[tuple[int, dict[str, Any]]] = []
        self.pre_checkout: list[tuple[str, bool]] = []
        self.subscription_links: list[dict[str, Any]] = []
        self.refunds: list[tuple[int, str]] = []
        self._refund_ok = refund_ok

    async def send_invoice(self, chat_id: int, **invoice: Any) -> None:
        self.invoices.append((chat_id, invoice))

    async def answer_pre_checkout_query(
        self, query_id: str, *, ok: bool, error_message: str | None = None
    ) -> None:
        self.pre_checkout.append((query_id, ok))

    async def create_invoice_link(self, **kwargs: Any) -> str:
        self.subscription_links.append(kwargs)
        return "https://t.me/$sub-link"

    async def refund_star_payment(self, user_id: int, telegram_payment_charge_id: str) -> bool:
        self.refunds.append((user_id, telegram_payment_charge_id))
        return self._refund_ok


class _Deps(Provider):
    scope = Scope.APP

    def __init__(
        self, gateway: _Gateway, bot: _FakeBot, redis: MemoryRedis, role: str = "user"
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._bot = bot
        self._redis = redis
        self._role = role

    @provide
    def usecase(self) -> PaymentsUsecase:
        return PaymentsUsecase(self._gateway, nop())

    @provide
    def bot(self) -> Bot:
        return self._bot  # type: ignore[return-value]

    @provide
    def charge_guard(self) -> ChargeGuard:
        return ChargeGuard(self._redis)  # type: ignore[arg-type]

    @provide
    def refund_guard(self) -> RefundGuard:
        return RefundGuard(self._redis)  # type: ignore[arg-type]

    @provide
    def log(self) -> Logger:
        return nop()

    @provide
    def identity(self) -> BotIdentity:
        return BotIdentity(tg_id=1, backend_user_id="1", role=self._role)


def _container(
    gateway: _Gateway, bot: _FakeBot, redis: MemoryRedis, role: str = "user"
) -> AsyncContainer:
    return make_async_container(_Deps(gateway, bot, redis, role))


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class _Callback:
    def __init__(self, message: Any) -> None:
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


async def test_on_buy_sends_invoice_and_answers() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_OFFER), bot, MemoryRedis())
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
    container = _container(_Gateway(_OFFER), bot, MemoryRedis())
    cb = _Callback(message=None)  # инлайн-сообщение могло быть удалено
    async with container() as rc:
        manager = SimpleNamespace(middleware_data={"dishka_container": rc})
        await handlers.on_buy(cb, None, manager)  # type: ignore[arg-type]
    assert bot.invoices == []
    assert cb.answered is True
    await container.close()


async def _pre_checkout(gateway: _Gateway, *, amount: int, currency: str) -> list[tuple[str, bool]]:
    bot = _FakeBot()
    container = _container(gateway, bot, MemoryRedis())
    query = SimpleNamespace(id="pq1", invoice_payload="o1", total_amount=amount, currency=currency)
    async with container() as rc:
        await handlers.on_pre_checkout(query, dishka_container=rc)  # type: ignore[call-arg, arg-type]
    await container.close()
    return bot.pre_checkout


async def test_on_pre_checkout_confirms_matching_amount() -> None:
    assert await _pre_checkout(_Gateway(_OFFER), amount=100, currency="XTR") == [("pq1", True)]


async def test_on_pre_checkout_rejects_wrong_amount() -> None:
    # клиент прислал заниженную сумму — не доверяем, сверка с бэкендом → отказ
    assert await _pre_checkout(_Gateway(_OFFER), amount=50, currency="XTR") == [("pq1", False)]


async def test_on_pre_checkout_fails_closed_on_backend_error() -> None:
    class _Down:
        async def get_offer(self, offer_id: str) -> Offer:
            raise UnavailableError("down")

        async def fulfill_order(self, order_id: str, charge_id: str) -> None:
            pass

    assert await _pre_checkout(_Down(), amount=100, currency="XTR") == [("pq1", False)]  # type: ignore[arg-type]


def _payment_message(sp: Any) -> Any:
    return SimpleNamespace(successful_payment=sp)


async def _complete(gateway: _Gateway, message: Any, redis: MemoryRedis) -> None:
    container = _container(gateway, _FakeBot(), redis)
    try:
        async with container() as rc:
            await handlers.on_successful_payment(message, dishka_container=rc)  # type: ignore[call-arg]
    finally:
        await container.close()


async def test_on_successful_payment_no_sp_returns() -> None:
    # message без successful_payment — ранний выход, выдачи нет
    gw = _Gateway(_OFFER)
    await _complete(gw, _payment_message(None), MemoryRedis())
    assert gw.fulfilled == []


async def test_on_successful_payment_fulfills_and_commits() -> None:
    gw = _Gateway(_OFFER)
    redis = MemoryRedis()
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    await _complete(gw, _payment_message(sp), redis)
    assert gw.fulfilled == [("o1", "charge-1")]
    # commit зафиксировал ключ: повторный апдейт того же платежа — дубликат
    assert "tg:charge:charge-1" in redis.store
    assert await ChargeGuard(redis).reserve("charge-1") is None  # type: ignore[arg-type]


async def test_on_successful_payment_duplicate_skips_fulfill() -> None:
    gw = _Gateway(_OFFER)
    redis = MemoryRedis()
    # соседний воркер уже держит резерв этого платежа → reserve отдаёт None
    assert await ChargeGuard(redis).reserve("charge-1") is not None  # type: ignore[arg-type]
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    await _complete(gw, _payment_message(sp), redis)
    assert gw.fulfilled == []  # at-least-once: повтор апдейта не выдаёт второй раз


async def test_on_successful_payment_releases_on_failure() -> None:
    gw = _Gateway(_OFFER, fulfill_error=UnavailableError("backend down"))
    redis = MemoryRedis()
    sp = SimpleNamespace(telegram_payment_charge_id="charge-1", invoice_payload="o1")
    with pytest.raises(errors.PaymentError):
        await _complete(gw, _payment_message(sp), redis)
    # сбой выдачи → резерв снят, чтобы повтор апдейта смог выдать
    assert "tg:charge:charge-1" not in redis.store


async def test_on_subscribe_builds_link_and_sends() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_OFFER), bot, MemoryRedis())
    msg = _Message()
    cb = _Callback(msg)
    async with container() as rc:
        manager = SimpleNamespace(middleware_data={"dishka_container": rc})
        await handlers.on_subscribe(cb, None, manager)  # type: ignore[arg-type]
    assert bot.subscription_links[0]["payload"] == "o1"
    assert msg.answers == ["https://t.me/$sub-link"]  # i18n в тесте off → шлём голый линк
    assert cb.answered is True
    await container.close()


def _refunded_message(rp: Any) -> Any:
    return SimpleNamespace(refunded_payment=rp)


async def test_on_refunded_payment_reverses_and_commits() -> None:
    gw = _Gateway(_OFFER)
    redis = MemoryRedis()
    rp = SimpleNamespace(telegram_payment_charge_id="ch-1", invoice_payload="o1")
    container = _container(gw, _FakeBot(), redis)
    async with container() as rc:
        await handlers.on_refunded_payment(_refunded_message(rp), dishka_container=rc)  # type: ignore[call-arg]
    await container.close()
    assert gw.revoked == [("o1", "ch-1")]
    assert "tg:refund:ch-1" in redis.store


async def test_on_refunded_payment_duplicate_skips_reverse() -> None:
    gw = _Gateway(_OFFER)
    redis = MemoryRedis()
    assert await RefundGuard(redis).reserve("ch-1") is not None  # type: ignore[arg-type]
    rp = SimpleNamespace(telegram_payment_charge_id="ch-1", invoice_payload="o1")
    container = _container(gw, _FakeBot(), redis)
    async with container() as rc:
        await handlers.on_refunded_payment(_refunded_message(rp), dishka_container=rc)  # type: ignore[call-arg]
    await container.close()
    assert gw.revoked == []


async def test_on_refund_command_admin_refunds_payer() -> None:
    bot = _FakeBot()
    gw = _Gateway(_OFFER, payer=42)
    container = _container(gw, bot, MemoryRedis(), role="admin")
    msg = _Message()
    cmd = SimpleNamespace(args="ch-1")
    async with container() as rc:
        await handlers.on_refund_command(msg, cmd, dishka_container=rc)  # type: ignore[call-arg, arg-type]
    await container.close()
    assert bot.refunds == [(42, "ch-1")]


async def test_on_refund_command_denies_non_admin() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_OFFER, payer=42), bot, MemoryRedis(), role="user")
    msg = _Message()
    cmd = SimpleNamespace(args="ch-1")
    async with container() as rc:
        await handlers.on_refund_command(msg, cmd, dishka_container=rc)  # type: ignore[call-arg, arg-type]
    await container.close()
    assert bot.refunds == []  # не-админ не инициирует возврат
    assert msg.answers  # получил отказ


async def test_on_refund_command_unknown_payer() -> None:
    bot = _FakeBot()
    container = _container(_Gateway(_OFFER, payer=None), bot, MemoryRedis(), role="admin")
    msg = _Message()
    cmd = SimpleNamespace(args="ghost")
    async with container() as rc:
        await handlers.on_refund_command(msg, cmd, dishka_container=rc)  # type: ignore[call-arg, arg-type]
    await container.close()
    assert bot.refunds == []  # плательщик не найден → без обращения к Telegram
