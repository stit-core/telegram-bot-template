"""state.py — состояние фичи payments + id демо-оффера. PURE.

DEMO_OFFER_ID живёт здесь (pure), чтобы getters и handlers (независимые слои) брали его,
не импортя друг друга. В реальном боте оффер приходит из start_data/диалога.
"""

from __future__ import annotations

from bot.platform.dialogs import states

PaymentsSG = states.Payments

DEMO_OFFER_ID = "premium-30d"
