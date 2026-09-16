"""
Defines the contract for retrieving collectible transaction candidates from Galax Pay.

The client is responsible for external data retrieval and provider-specific
filtering, while collection eligibility remains part of the business layer.
"""

from abc import ABC, abstractmethod
from datetime import date


class GalaxPayClient(ABC):

    @abstractmethod
    def get_pending_transactions(
        self,
        reference_date: date,
    ) -> list[dict]:
        """
        Retrieves pending boleto transactions within the collection window.
        """
        pass