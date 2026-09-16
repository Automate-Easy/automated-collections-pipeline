"""
Defines the contract for sending collection messages through Z-API.

The interface isolates the collection pipeline from Z-API-specific HTTP
details and allows the real integration to be replaced during testing.
"""

from abc import ABC, abstractmethod

from src.clients.zapi.send_result import ZApiSendResult


class ZApiClient(ABC):

    @abstractmethod
    def send_text(
        self,
        phone: str,
        message: str,
        delay_seconds: int | None = None,
    ) -> ZApiSendResult:
        """
        Sends a regular text message with an optional native Z-API delay.
        """
        pass

    @abstractmethod
    def send_copy_code(
        self,
        phone: str,
        message: str,
        code: str,
    ) -> ZApiSendResult:
        """
        Sends a message containing a button that copies a payment code.
        """
        pass