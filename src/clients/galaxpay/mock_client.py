"""
Provides a mock implementation of the Galax Pay client for local execution.

The mock reproduces the relevant structure of Galax Pay transaction responses,
allowing the complete collection pipeline to run without external credentials.
"""

from datetime import date, timedelta

from src.clients.galaxpay.client import GalaxPayClient


class MockGalaxPayClient(GalaxPayClient):

    def __init__(self, demo_phone: str):
        self.demo_phone = demo_phone

    def get_pending_transactions(
        self,
        reference_date: date,
    ) -> list[dict]:

        return [
            self._create_transaction(
                1001, 501, "John Doe", -5, reference_date
            ),
            self._create_transaction(
                1002, 502, "Jane Smith", -3, reference_date
            ),
            self._create_transaction(
                1003, 503, "Michael Brown", 0, reference_date
            ),
            self._create_transaction(
                1004, 504, "Sarah Wilson", 5, reference_date
            ),
            self._create_transaction(
                1005, 505, "David Miller", 7, reference_date
            ),
            self._create_transaction(
                1006,
                506,
                "Emily Davis",
                10,
                reference_date,
                amount_cents=12999,
            ),
            self._create_transaction(
                1007, 507, "Robert Taylor", 15, reference_date
            ),

            # Emily has a second collectible debt event. Both events should be
            # consolidated into one customer communication by MessageDispatcher.
            self._create_transaction(
                1008,
                506,
                "Emily Davis",
                15,
                reference_date,
                amount_cents=24990,
            ),
        ]

    def _create_transaction(
        self,
        transaction_id: int,
        customer_id: int,
        customer_name: str,
        days_from_due_date: int,
        reference_date: date,
        amount_cents: int = 12999,
    ) -> dict:

        # A positive value means the debt is already overdue.
        # A negative value means its due date is still in the future.
        due_date = reference_date - timedelta(days=days_from_due_date)

        return {
            "galaxPayId": transaction_id,
            "value": amount_cents,
            "payday": due_date.isoformat(),

            # The mock intentionally preserves the external Galax Pay structure.
            # This ensures the same mapper is exercised in both demo and real modes.
            "Boleto": {
                "bankLine": (
                    f"23793{transaction_id}"
                    "000000000000000000000000000"
                ),
            },

            "Charge": [
                {
                    "Customer": {
                        "galaxPayId": customer_id,
                        "name": customer_name,
                        "phones": [self.demo_phone],
                    }
                }
            ],
        }