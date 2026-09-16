"""
Dispatches eligible Galax Pay transactions to the collectible debt queue.

The dispatcher maps external transactions into domain objects, applies the
collection schedule, and creates idempotent scheduled collection events.
"""

from src.clients.galaxpay.transaction_mapper import GalaxPayTransactionMapper
from src.queue.debt_queue_item import DebtQueueItem
from src.queue.debt_queue_repository import DebtQueueRepository
from src.rules.collection_schedule import is_debt_collectible


class DebtDispatcher:

    def __init__(self, repository: DebtQueueRepository):
        self.repository = repository

    def dispatch(self, transactions: list[dict]) -> int:
        enqueued_count = 0

        for transaction in transactions:
            debt = GalaxPayTransactionMapper.to_collectible_debt(transaction)

            if not is_debt_collectible(debt):
                continue

            collection_day = debt.days_from_due_date
            idempotency_key = (
                f"{debt.galaxpay_transaction_id}:{collection_day}"
            )

            item = DebtQueueItem(
                debt=debt,
                collection_day=collection_day,
                idempotency_key=idempotency_key,
            )

            if self.repository.enqueue(item):
                enqueued_count += 1

        return enqueued_count