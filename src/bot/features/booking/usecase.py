"""usecase.py — ВСЕ шаги wizard'а (включая passthrough) + отправка заказа.

Handlers не принимают доменных решений: каждый шаг — метод здесь; результат-данные
(GuestsStep.address_required) говорит handler'у, какой экран следующий, но сами экраны
usecase не знает. Anti-corruption: typed-ошибки HTTP-границы → sentinel'ы errors.py
(Conflict → BookingConflict, catch-all ApiError → BookingUnavailable).
"""

from __future__ import annotations

from pylibinfra.logkit import Logger

from bot.features.booking import errors, policy
from bot.features.booking.dto import GuestsStep
from bot.features.booking.ports import BookingGateway
from bot.features.booking.state import BookingDraft
from bot.pkg.http_client.errors import ApiError, ConflictError
from bot.pkg.http_client.internal.booking import BookingConfirmation


class BookingUsecase:
    def __init__(self, gateway: BookingGateway, log: Logger) -> None:
        self._gateway = gateway
        self._log = log

    def set_services(self, draft: BookingDraft, selected: list[str]) -> BookingDraft:
        draft.services = list(selected)
        return draft

    def set_guests(self, draft: BookingDraft, guests: int) -> GuestsStep:
        decision = policy.validate_guests(guests)
        if not decision.allowed:
            raise errors.GuestsRejected(decision.reason)
        draft.guests = guests
        return GuestsStep(draft=draft, address_required=policy.needs_address(draft.services))

    def set_address(self, draft: BookingDraft, address: str) -> BookingDraft:
        decision = policy.validate_address(address)
        if not decision.allowed:
            raise errors.AddressRejected(decision.reason)
        draft.address = address
        return draft

    async def submit(self, user_id: str, draft: BookingDraft, draft_id: str) -> BookingConfirmation:
        try:
            result = await self._gateway.submit_booking(
                draft_id=draft_id,
                user_id=user_id,
                services=draft.services,
                guests=draft.guests,
                address=draft.address,
            )
        except ConflictError as exc:
            raise errors.BookingConflict from exc
        except ApiError as exc:
            self._log.warn("booking.backend_fault", kind=type(exc).__name__, status=exc.status_code)
            raise errors.BookingUnavailable from exc
        self._log.info("booking.submitted", confirmation_id=result.confirmation_id)
        return result
