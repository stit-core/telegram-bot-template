"""AppErrorUX — пользовательский error-UX шаблона (реализует tgbotkit.ErrorUX структурно).

Регистрацию error-handlers делает kit; шаблон лишь даёт тексты/поведение через провайдер
(ExtensionProvider override'ит дефолт kit'а). На устаревших кнопках (UnknownIntent/State
после рестарта/TTL) гасим «часики» callback'а и подсказываем /start; на прочем — нейтральное
сообщение (panic-метрику уже эмитит recovery-middleware kit'а).
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import ErrorEvent

_STALE = "Сессия устарела. Нажмите /start, чтобы начать заново."
_OOPS = "Что-то пошло не так. Попробуйте позже."


class AppErrorUX:
    async def on_unknown_intent(self, event: ErrorEvent, bot: Bot) -> None:
        await self._answer_callback(event, _STALE)

    async def on_unknown_state(self, event: ErrorEvent, bot: Bot) -> None:
        await self._answer_callback(event, _STALE)

    async def on_unhandled(self, event: ErrorEvent, bot: Bot) -> None:
        cq = event.update.callback_query
        if cq is not None:
            await cq.answer(_OOPS, show_alert=False)
            return
        msg = event.update.message
        if msg is not None:
            await msg.answer(_OOPS)

    async def _answer_callback(self, event: ErrorEvent, text: str) -> None:
        # Сообщение трогать небезопасно (могло быть удалено) — только answer на callback.
        cq = event.update.callback_query
        if cq is not None:
            await cq.answer(text, show_alert=False)
