"""Unit: BookingUsecase — шаги wizard'а (валидация, ветвление адреса как данные)
+ anti-corruption submit (Conflict → BookingConflict, catch-all ApiError → BookingUnavailable).
"""

from __future__ import annotations

from typing import Any

import pytest
from pylibinfra.logkit import nop

from bot.features.booking import errors
from bot.features.booking.state import BookingDraft
from bot.features.booking.usecase import BookingUsecase
from bot.pkg.http_client.errors import ConflictError, InvalidRequestError, UnavailableError
from bot.pkg.http_client.internal.booking import BookingConfirmation

pytestmark = pytest.mark.unit


class _Gateway:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.submits: list[dict[str, Any]] = []

    async def submit_booking(self, **kwargs: Any) -> BookingConfirmation:
        if self._error is not None:
            raise self._error
        self.submits.append(kwargs)
        return BookingConfirmation(confirmation_id="BK-1")


def _uc(gateway: _Gateway | None = None) -> BookingUsecase:
    return BookingUsecase(gateway or _Gateway(), nop())


def test_set_services_overwrites_selection() -> None:
    draft = _uc().set_services(BookingDraft(services=["gift_wrap"]), ["delivery"])
    assert draft.services == ["delivery"]


def test_set_guests_requires_address_for_delivery() -> None:
    step = _uc().set_guests(BookingDraft(services=["delivery"]), 3)
    assert step.address_required is True
    assert step.draft.guests == 3


def test_set_guests_skips_address_without_delivery() -> None:
    step = _uc().set_guests(BookingDraft(services=["window_seat"]), 2)
    assert step.address_required is False


def test_set_guests_out_of_range_rejected() -> None:
    with pytest.raises(errors.GuestsRejected):
        _uc().set_guests(BookingDraft(), 0)
    with pytest.raises(errors.GuestsRejected):
        _uc().set_guests(BookingDraft(), 11)


def test_set_address_too_short_rejected() -> None:
    with pytest.raises(errors.AddressRejected):
        _uc().set_address(BookingDraft(), "ул")


async def test_submit_passes_draft_and_draft_id() -> None:
    gw = _Gateway()
    draft = BookingDraft(services=["delivery"], guests=2, address="Тверская 7")
    result = await _uc(gw).submit("u1", draft, "draft-42")
    assert result.confirmation_id == "BK-1"
    assert gw.submits == [
        {
            "draft_id": "draft-42",
            "user_id": "u1",
            "services": ["delivery"],
            "guests": 2,
            "address": "Тверская 7",
        }
    ]


async def test_submit_maps_unavailable() -> None:
    gw = _Gateway(error=UnavailableError("503"))
    with pytest.raises(errors.BookingUnavailable):
        await _uc(gw).submit("u1", BookingDraft(), "k")


async def test_submit_maps_conflict() -> None:
    gw = _Gateway(error=ConflictError("409"))
    with pytest.raises(errors.BookingConflict):
        await _uc(gw).submit("u1", BookingDraft(), "k")


async def test_submit_catches_full_taxonomy() -> None:
    # catch-all по ApiError: 422 не протекает в recovery как generic crash
    gw = _Gateway(error=InvalidRequestError("422", status_code=422))
    with pytest.raises(errors.BookingUnavailable):
        await _uc(gw).submit("u1", BookingDraft(), "k")
