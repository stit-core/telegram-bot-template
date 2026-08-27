"""errors.py — sentinel-ошибки фичи profile. PURE.

gateway мапит сетевые сбои в эти типы; views мапит эти типы в user-текст. Базовый
FeatureError — в shared, чтобы recovery/ErrorUX отличал доменную ошибку от настоящего сбоя.
"""

from __future__ import annotations

from bot.shared.errors import FeatureError


class ProfileError(FeatureError):
    """Базовая ошибка фичи profile."""


class ProfileNotFound(ProfileError):
    """Бэкенд не знает такого профиля."""


class ProfileForbidden(ProfileError):
    """Политика запретила операцию (роль/доступ)."""


class NameRejected(ProfileError):
    """Имя не прошло валидацию (для on_error ввода)."""


class ProfileConflict(ProfileError):
    """Бэкенд ответил конфликтом состояния — результат мутации неоднозначен."""


class ProfileUnavailable(ProfileError):
    """Бэкенд профиля недоступен или нарушил контракт."""
