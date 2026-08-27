"""errors.py — sentinel-ошибки фичи payments. PURE."""

from __future__ import annotations

from bot.shared.errors import FeatureError


class PaymentError(FeatureError):
    """Базовая ошибка оплаты."""


class OrderNotFound(PaymentError):
    """Бэкенд не знает такого оффера/заказа."""


class PaymentUnavailable(PaymentError):
    """Платёжный бэкенд недоступен или нарушил контракт."""
