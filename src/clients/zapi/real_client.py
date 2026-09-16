"""
Provides the real HTTP integration with Z-API.

This client is responsible only for translating application-level send
requests into Z-API HTTP calls and exposing successful submission results.
"""

import requests

from src.clients.zapi.client import ZApiClient
from src.clients.zapi.send_result import ZApiSendResult


class RealZApiClient(ZApiClient):

    BASE_URL = "https://api.z-api.io/instances"

    def __init__(
        self,
        instance_id: str,
        instance_token: str,
        client_token: str,
        timeout_seconds: int = 30,
    ):
        self.instance_id = instance_id
        self.instance_token = instance_token
        self.client_token = client_token
        self.timeout_seconds = timeout_seconds

    def send_text(
        self,
        phone: str,
        message: str,
        delay_seconds: int | None = None,
    ) -> ZApiSendResult:
        payload = {
            "phone": phone,
            "message": message,
        }

        # Z-API can apply the pacing delay natively for regular text messages.
        if delay_seconds is not None:
            payload["delayMessage"] = delay_seconds

        return self._post(
            endpoint="send-text",
            payload=payload,
        )

    def send_copy_code(
        self,
        phone: str,
        message: str,
        code: str,
    ) -> ZApiSendResult:
        payload = {
            "phone": phone,
            "message": message,
            "code": code,
            "buttonText": "Copy code",
        }

        return self._post(
            endpoint="send-button-otp",
            payload=payload,
        )

    def _post(
        self,
        endpoint: str,
        payload: dict,
    ) -> ZApiSendResult:
        url = (
            f"{self.BASE_URL}/"
            f"{self.instance_id}/token/"
            f"{self.instance_token}/"
            f"{endpoint}"
        )

        headers = {
            "Client-Token": self.client_token,
            "Content-Type": "application/json",
        }

        # A single client call represents exactly one delivery attempt.
        # Retry decisions intentionally belong to the MessagePerformer.
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        response_data = response.json()

        return ZApiSendResult(
            zaap_id=response_data["zaapId"],
            message_id=response_data["messageId"],
            id=response_data["id"],
        )