"""Базовая доменная ошибка фичи. PURE.

FeatureError — общий предок sentinel-ошибок всех фич: presentation (views.error_text)
ловит его, чтобы отличить «ожидаемую доменную» ошибку от настоящего сбоя (тот всплывает
в recovery-middleware tgbotkit → panic-метрика + on_unhandled).
"""

from __future__ import annotations


class FeatureError(Exception):
    """Базовая ожидаемая ошибка бизнес-сценария (не баг, а контролируемый исход)."""
