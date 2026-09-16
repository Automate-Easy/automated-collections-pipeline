"""
Provides a local Z-API replacement for demo execution.

The mock preserves the real messaging client contract while printing delivery
operations locally instead of sending actual WhatsApp messages.
"""

from src.clients.zapi.client import ZApiClient
from src.clients.zapi.send_result import ZApiSendResult


class MockZApiClient(ZApiClient):

    def send_text(
        self,
        phone: str,
        message: str,
        delay_seconds: int | None = None,
    ) -> ZApiSendResult:
        print()
        print("[MOCK Z-API | TEXT]")
        print(f"Phone: {phone}")
        print(f"Native delay: {delay_seconds}s")
        print(message)

        return ZApiSendResult(
            zaap_id="mock-zaap-text",
            message_id="mock-message-text",
            id="mock-id-text",
        )

    def send_copy_code(
        self,
        phone: str,
        message: str,
        code: str,
    ) -> ZApiSendResult:
        print()
        print("[MOCK Z-API | COPY CODE]")
        print(f"Phone: {phone}")
        print(message)
        print(f"Code: {code}")

        return ZApiSendResult(
            zaap_id="mock-zaap-copy-code",
            message_id="mock-message-copy-code",
            id="mock-id-copy-code",
        )