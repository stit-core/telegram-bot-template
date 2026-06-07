"""dialogs — единый каталог StatesGroup (states), общие виджеты (common), error-UX (errors)."""

from bot.platform.dialogs import common, states
from bot.platform.dialogs.errors import AppErrorUX

__all__ = ["AppErrorUX", "common", "states"]
