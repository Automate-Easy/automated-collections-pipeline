"""
Represents a fully prepared customer communication in the message queue.

All business and presentation decisions are resolved before this item is
created, keeping the MessagePerformer focused exclusively on delivery.
"""

from dataclasses import dataclass
from datetime import datetime

from src.models.charge_message import ChargeMessage
from src.queue.queue_status import QueueStatus


@dataclass
class MessageQueueItem:
    # One customer may have multiple phone numbers available for delivery.
    customer_phones: list[str]

    # Contains the greeting and singular/plural introduction already prepared
    # by the MessageDispatcher.
    main_message: str

    # Each charge contains exactly what the performer needs to deliver:
    # its prepared text followed by its copyable bank line.
    charges: list[ChargeMessage]

    # References the debt queue events consumed to create this message.
    # This provides traceability between both queues.
    source_event_keys: list[str]

    # Prevents the same set of debt events from creating duplicate messages.
    idempotency_key: str

    # Delivery processing state belongs exclusively to the message queue.
    status: QueueStatus = QueueStatus.PENDING
    attempt_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None