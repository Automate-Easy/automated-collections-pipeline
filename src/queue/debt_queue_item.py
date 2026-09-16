"""
Represents a scheduled collection event stored in the collectible debt queue.

The queue item combines a debt with processing metadata and identifies each
collection event by transaction and collection schedule day.
"""

from dataclasses import dataclass
from datetime import datetime

from src.models.collectible_debt import CollectibleDebt
from src.queue.queue_status import QueueStatus


@dataclass
class DebtQueueItem:
    debt: CollectibleDebt
    collection_day: int
    idempotency_key: str
    status: QueueStatus = QueueStatus.PENDING
    attempt_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None