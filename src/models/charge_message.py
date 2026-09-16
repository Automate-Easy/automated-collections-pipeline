"""
Represents one charge prepared for customer communication.

The MessageDispatcher creates this object with all presentation decisions
already resolved, allowing the MessagePerformer to remain delivery-only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChargeMessage:
    # Human-readable description already prepared by the MessageDispatcher.
    message: str

    # Payment code is kept separately because the WhatsApp integration sends
    # it through a dedicated copy-code operation rather than regular text.
    bank_line: str