"""webapp — валидатор initData (поверх tgbotkit) + извлечение WebAppUser."""

from pylibinfra.tgbotkit import InitDataError

from bot.platform.webapp.init_data import WebAppUser, validate_webapp_user

__all__ = ["InitDataError", "WebAppUser", "validate_webapp_user"]
