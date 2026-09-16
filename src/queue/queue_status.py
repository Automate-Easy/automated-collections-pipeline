"""
Defines the valid processing states for queue items.

Using an enum prevents arbitrary status values and provides a shared lifecycle
definition across the collection pipeline.
"""

from enum import Enum


class QueueStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"