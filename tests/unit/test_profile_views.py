"""Unit: profile.views — единственная точка маппинга доменной ошибки → user-текст.

error_text покрывает каждую ветку match: NotFound / Forbidden|NameRejected / базовая
ProfileError / не-наша ошибка (пробрасывается в recovery-middleware kit'а).
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


def test_error_text_not_found_hints_start() -> None:
    assert "/start" in views.error_text(errors.ProfileNotFound("gone"))


def test_error_text_forbidden_uses_reason() -> None:
    assert views.error_text(errors.ProfileForbidden("banned")) == "banned"


def test_error_text_name_rejected_uses_reason() -> None:
    assert views.error_text(errors.NameRejected("слишком длинное")) == "слишком длинное"


def test_error_text_forbidden_without_reason_falls_back() -> None:
    assert views.error_text(errors.ProfileForbidden("")) == "Действие недоступно."


def test_error_text_base_profile_error_is_soft() -> None:
    assert "недоступен" in views.error_text(errors.ProfileError("down"))


def test_error_text_reraises_foreign_error() -> None:
    # не доменная ошибка профиля — не глотаем, пусть всплывёт в recovery-middleware
    boom = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        views.error_text(boom)
