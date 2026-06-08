"""Unit: booking.policy — валидация шагов wizard'а + условие шага адреса."""

from __future__ import annotations

import pytest

from bot.features.booking import policy

pytestmark = pytest.mark.unit


def test_validate_guests_range() -> None:
    assert policy.validate_guests(1).allowed is True
    assert policy.validate_guests(10).allowed is True
    assert policy.validate_guests(0).allowed is False
    assert policy.validate_guests(11).allowed is False


def test_validate_address_min_length() -> None:
    assert policy.validate_address("Тверская 7").allowed is True
    assert policy.validate_address("ул").allowed is False
    assert policy.validate_address("     ").allowed is False  # пробелы не считаются


def test_needs_address_only_for_delivery() -> None:
    assert policy.needs_address(["delivery"]) is True
    assert policy.needs_address(["window_seat", "gift_wrap"]) is False
    assert policy.needs_address([]) is False
