"""FakeDelivery — заглушка tgbotkit.Delivery: записывает отправленные сообщения/диалоги.

`fail_next` инъецирует сбой доставки: ближайшие N вызовов `send_message` бросают (как реальный
`Delivery` после снятия проглатывания) — чтобы тест мог проверить проброс→release→redelivery.
"""

from __future__ import annotations

from typing import Any


class DeliveryInjectedError(RuntimeError):
    pass


class FakeDelivery:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.dialogs: list[tuple[int, int]] = []
        self.fail_next = 0

    def localize(self, locale: str | None, key: str, args: dict[str, Any] | None = None) -> str:
        return key  # i18n не установлен в тестах → ключ (как боевой Delivery без translator)

    async def send_message(self, *, chat_id: int, text: str, **kwargs: Any) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise DeliveryInjectedError("injected delivery failure")
        self.messages.append((chat_id, text))

    async def start_dialog(self, *, user_id: int, chat_id: int, **kwargs: Any) -> None:
        self.dialogs.append((user_id, chat_id))
