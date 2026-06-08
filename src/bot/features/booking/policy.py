"""policy.py — чистые правила wizard'а (без I/O). Возвращают Decision.

validate_guests/validate_address — валидация шагов; needs_address — условный переход
(доставка выбрана → нужен шаг адреса). Источник «условного switch_to из policy».
"""

from __future__ import annotations

from bot.features.booking.state import DELIVERY_SERVICE, MAX_GUESTS
from bot.shared.decision import Decision, allow, deny


def validate_guests(guests: int) -> Decision:
    if guests < 1 or guests > MAX_GUESTS:
        return deny(f"1..{MAX_GUESTS}")
    return allow()


def validate_address(address: str) -> Decision:
    if len(address.strip()) < 5:
        return deny("too short")
    return allow()


def needs_address(services: list[str]) -> bool:
    return DELIVERY_SERVICE in services
