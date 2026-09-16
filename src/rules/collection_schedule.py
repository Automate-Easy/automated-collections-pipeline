"""
Defines the collection schedule used to determine when a debt should be processed.

A debt is eligible for collection only when its distance from the due date
matches one of the configured collection days.
"""

from src.models.collectible_debt import CollectibleDebt


COLLECTION_DAYS = {-5, 0, 5, 10, 15}


def is_debt_collectible(debt: CollectibleDebt) -> bool:
    return debt.days_from_due_date in COLLECTION_DAYS