"""
Represents the result of a successful message submission to Z-API.

The identifiers returned by Z-API are preserved for logging, traceability,
and future delivery-status tracking.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ZApiSendResult:
    zaap_id: str
    message_id: str
    id: str