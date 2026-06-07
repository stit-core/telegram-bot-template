"""FakeDelivery — заглушка tgbotkit.Delivery: записывает отправленные сообщения/диалоги."""

from __future__ import annotations

from typing import Any


class FakeDelivery:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.dialogs: list[tuple[int, int]] = []

    async def send_message(self, *, chat_id: int, text: str, **kwargs: Any) -> None:
        self.messages.append((chat_id, text))

    async def start_dialog(self, *, user_id: int, chat_id: int, **kwargs: Any) -> None:
        self.dialogs.append((user_id, chat_id))
