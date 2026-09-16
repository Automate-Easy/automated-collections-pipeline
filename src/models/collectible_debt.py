"""
Domain model representing a collectible customer debt.

A CollectibleDebt contains only business data required by the collection
pipeline. Processing state, retry attempts, and queue metadata are intentionally
kept outside this model.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CollectibleDebt:
    galaxpay_transaction_id: int
    customer_id: int
    customer_name: str
    customer_phones: list[str]
    amount_cents: int
    due_date: date

    # The bank line must travel with the debt because it will eventually be
    # delivered to the customer as the payment code for this specific charge.
    bank_line: str

    @property
    def days_from_due_date(self) -> int:
        return (date.today() - self.due_date).days