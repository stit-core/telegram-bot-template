"""Unit: profile.views — единственная точка маппинга доменной ошибки → ключ user-текста.

error_text покрывает каждую ветку match: NotFound / Forbidden / NameRejected / Conflict /
базовая ProfileError / не-наша ошибка (пробрасывается в recovery-middleware kit'а).
"""

from __future__ import annotations

import pytest

from bot.features.profile import errors, views
from bot.pkg.http_client.internal.profile import User

pytestmark = pytest.mark.unit


def test_to_window_premium_badge() -> None:
    data = views.to_window(User(name="Алиса", email="a@x.io", premium=True))
    assert data == {"name": "Алиса", "email": "a@x.io", "badge": "⭐ premium"}


def test_to_window_no_badge_when_not_premium() -> None:
    data = views.to_window(User(name="Боб", email="b@x.io", premium=False))
    assert data["badge"] == ""


def test_error_text_maps_each_sentinel_to_key() -> None:
    cases = [
        (errors.ProfileNotFound(), "profile-error-not-found"),
        (errors.ProfileForbidden("banned"), "profile-error-forbidden"),
        (errors.NameRejected("слишком длинное"), "profile-error-name-rejected"),
        (errors.ProfileConflict(), "profile-error-conflict"),
        (errors.ProfileUnavailable(), "profile-error-unavailable"),
        (errors.ProfileError("base"), "profile-error-unavailable"),
    ]
    for err, key in cases:
        assert views.error_text(err) == key


def test_error_text_reraises_foreign_error() -> None:
    # не доменная ошибка профиля — не глотаем, пусть всплывёт в recovery-middleware
    boom = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        views.error_text(boom)
