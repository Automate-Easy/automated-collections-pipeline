"""
Provides the real HTTP integration with the Galax Pay API.

The client owns authentication, transaction retrieval, pagination, and
provider-specific filtering while keeping collection rules outside the API layer.
"""

import base64
from datetime import date, timedelta

import requests

from src.clients.galaxpay.client import GalaxPayClient


class RealGalaxPayClient(GalaxPayClient):

    SANDBOX_BASE_URL = "https://api.sandbox.cel.cash/v2"
    PRODUCTION_BASE_URL = "https://api-celcash.celcoin.com.br/v2"

    PAGE_SIZE = 100

    def __init__(
        self,
        galax_id: str,
        galax_hash: str,
        base_url: str = SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ):
        self.galax_id = galax_id
        self.galax_hash = galax_hash
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

        self._access_token: str | None = None

    def get_pending_transactions(
        self,
        reference_date: date,
    ) -> list[dict]:
        pay_day_from = reference_date - timedelta(days=15)
        pay_day_to = reference_date + timedelta(days=5)

        transactions = []
        start_at = 0

        while True:
            page = self._get_transactions_page(
                pay_day_from=pay_day_from,
                pay_day_to=pay_day_to,
                start_at=start_at,
            )

            transactions.extend(page)

            # A page smaller than the requested limit means there is no
            # additional page to retrieve.
            if len(page) < self.PAGE_SIZE:
                break

            start_at += self.PAGE_SIZE

        return transactions

    def _get_transactions_page(
        self,
        pay_day_from: date,
        pay_day_to: date,
        start_at: int,
    ) -> list[dict]:
        params = {
            "payDayFrom": pay_day_from.isoformat(),
            "payDayTo": pay_day_to.isoformat(),
            "status": "pendingBoleto",
            "startAt": start_at,
            "limit": self.PAGE_SIZE,
        }

        response = self._request_transactions(params)

        # For this operation, "not found" means that there are no transactions
        # matching the current filters, which is a valid empty result.
        if response.status_code == 404:
            return []

        # An expired or invalid token is refreshed once before the request
        # is considered a real authentication failure.
        if response.status_code == 401:
            self._access_token = None
            response = self._request_transactions(params)

        response.raise_for_status()

        response_data = response.json()

        return self._extract_transactions(response_data)

    def _request_transactions(
        self,
        params: dict,
    ) -> requests.Response:
        access_token = self._get_access_token()

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        return requests.get(
            f"{self.base_url}/transactions",
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )

    def _get_access_token(self) -> str:
        if self._access_token is not None:
            return self._access_token

        credentials = (
            f"{self.galax_id}:{self.galax_hash}"
        ).encode("utf-8")

        encoded_credentials = base64.b64encode(
            credentials
        ).decode("utf-8")

        headers = {
            "Authorization": (
                f"Basic {encoded_credentials}"
            ),
        }

        response = requests.post(
            f"{self.base_url}/token",
            headers=headers,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        response_data = response.json()

        try:
            self._access_token = response_data["access_token"]
        except KeyError as error:
            raise RuntimeError(
                "Galax Pay authentication response did not contain "
                "an access_token."
            ) from error

        return self._access_token

    @staticmethod
    def _extract_transactions(
        response_data: dict | list,
    ) -> list[dict]:
        # Keeping response-shape handling isolated here makes the HTTP layer
        # easy to adjust without affecting the rest of the collection pipeline.
        if isinstance(response_data, list):
            return response_data

        if isinstance(response_data, dict):
            if "Transactions" in response_data:
                return response_data["Transactions"]

            if "transactions" in response_data:
                return response_data["transactions"]

        raise RuntimeError(
            "Unexpected Galax Pay transactions response format."
        )