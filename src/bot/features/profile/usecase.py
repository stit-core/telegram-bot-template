"""usecase.py — оркестрация сценария. Знает ТОЛЬКО порты (Protocol) и policy.

Единственная точка anti-corruption: typed-ошибки httpclient (NotFound/Conflict/Unavailable)
мапятся в sentinel'ы errors.py здесь, не в presentation. Не знает про aiogram/httpx.
"""

from __future__ import annotations

from pylibinfra.httpclient import ConflictError, NotFoundError, UnavailableError
from pylibinfra.logkit import Logger

from bot.features.profile import errors, policy
from bot.features.profile.ports import BackendGateway, OnboardingReader
from bot.pkg.http_client.internal.profile import User
from bot.platform.identity import BotIdentity


class ProfileUsecase:
    def __init__(self, gateway: BackendGateway, onboarding: OnboardingReader, log: Logger) -> None:
        self._gateway = gateway
        self._onboarding = onboarding
        self._log = log

    async def view(self, identity: BotIdentity) -> User:
        decision = policy.can_view_profile(identity.role)
        if not decision.allowed:
            raise errors.ProfileForbidden(decision.reason)
        try:
            return await self._gateway.get_user(identity.backend_user_id)
        except NotFoundError as exc:
            raise errors.ProfileNotFound(str(exc)) from exc
        except UnavailableError as exc:
            raise errors.ProfileError("Сервис временно недоступен") from exc

    async def rename(self, identity: BotIdentity, raw_name: str) -> User:
        decision = policy.validate_name(raw_name)
        if not decision.allowed:
            raise errors.NameRejected(decision.reason)
        try:
            user = await self._gateway.rename_user(identity.backend_user_id, raw_name.strip())
        except NotFoundError as exc:
            raise errors.ProfileNotFound(str(exc)) from exc
        except ConflictError as exc:
            # rename возвращает обновлённый профиль — на 409 тела нет, успех неоднозначен
            raise errors.ProfileError("Не удалось обновить профиль") from exc
        except UnavailableError as exc:
            raise errors.ProfileError("Сервис временно недоступен") from exc
        self._log.info("profile.renamed", tg_id=identity.tg_id)
        return user

    # demo-only: reference cross-feature чтения; нет живого вызывающего — wire или prune.
    async def is_first_time(self, tg_id: int) -> bool:
        return not await self._onboarding.is_onboarded(tg_id)
