"""
Delivers pending collection messages through the configured messaging client.

The performer executes delivery instructions prepared by the MessageDispatcher,
applies message-level retries with exponential backoff, native Z-API pacing,
and final queue item status.
"""

import logging
import random
import time
from datetime import datetime
from typing import Callable

from src.clients.zapi.client import ZApiClient
from src.clients.zapi.send_result import ZApiSendResult
from src.queue.message_queue_item import MessageQueueItem
from src.queue.message_queue_repository import MessageQueueRepository


logger = logging.getLogger(__name__)


class MessagePerformer:

    MAX_SEND_ATTEMPTS = 3
    RETRY_BASE_DELAY_SECONDS = 1

    MIN_DELAY_SECONDS = 1
    MAX_DELAY_SECONDS = 10

    def __init__(
        self,
        repository: MessageQueueRepository,
        zapi_client: ZApiClient,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.repository = repository
        self.zapi_client = zapi_client
        self.sleep_fn = sleep_fn

    def perform(self) -> int:
        pending_items = self.repository.get_pending_items()
        processed_count = 0

        for item in pending_items:
            if self._process_item(item):
                processed_count += 1

        return processed_count

    def _process_item(
        self,
        item: MessageQueueItem,
    ) -> bool:
        try:
            for phone in item.customer_phones:
                main_message = self._resolve_greeting(
                    item.main_message
                )

                # Regular text messages use Z-API's native pacing instead of
                # blocking the worker with a local sleep.
                delay_seconds = random.randint(
                    self.MIN_DELAY_SECONDS,
                    self.MAX_DELAY_SECONDS,
                )

                self._send_with_retry(
                    send_operation=lambda: self.zapi_client.send_text(
                        phone=phone,
                        message=main_message,
                        delay_seconds=delay_seconds,
                    ),
                    item=item,
                    message_description="main message",
                )

                for charge in item.charges:
                    # The copy-code endpoint does not use our pacing parameter.
                    # Retry behavior remains identical for every message type.
                    self._send_with_retry(
                        send_operation=lambda charge=charge: (
                            self.zapi_client.send_copy_code(
                                phone=phone,
                                message=charge.message,
                                code=charge.bank_line,
                            )
                        ),
                        item=item,
                        message_description="charge message",
                    )

            self.repository.mark_as_processed(
                item.idempotency_key
            )

            logger.info(
                "Message queue item processed successfully: %s",
                item.idempotency_key,
            )

            return True

        except Exception as error:
            self.repository.mark_as_failed(
                idempotency_key=item.idempotency_key,
                error_message=str(error),
            )

            logger.error(
                "Message queue item failed: %s - %s",
                item.idempotency_key,
                error,
            )

            return False

    def _send_with_retry(
        self,
        send_operation: Callable[[], ZApiSendResult],
        item: MessageQueueItem,
        message_description: str,
    ) -> None:
        for attempt in range(1, self.MAX_SEND_ATTEMPTS + 1):
            try:
                result = send_operation()

                logger.info(
                    "%s sent successfully for queue item %s "
                    "(attempt %s/%s, message_id=%s)",
                    message_description,
                    item.idempotency_key,
                    attempt,
                    self.MAX_SEND_ATTEMPTS,
                    result.message_id,
                )

                return

            except Exception as error:
                logger.warning(
                    "%s failed for queue item %s "
                    "(attempt %s/%s): %s",
                    message_description,
                    item.idempotency_key,
                    attempt,
                    self.MAX_SEND_ATTEMPTS,
                    error,
                )

                if attempt == self.MAX_SEND_ATTEMPTS:
                    raise

                # Exponential backoff reduces pressure on the external service
                # while keeping retry behavior deterministic and testable.
                retry_delay = (
                    self.RETRY_BASE_DELAY_SECONDS
                    * (2 ** (attempt - 1))
                )

                logger.info(
                    "Retrying %s for queue item %s in %s second(s)",
                    message_description,
                    item.idempotency_key,
                    retry_delay,
                )

                self.sleep_fn(retry_delay)

    @staticmethod
    def _resolve_greeting(
        message: str,
    ) -> str:
        current_hour = datetime.now().hour

        if current_hour < 12:
            greeting = "Good morning"
        elif current_hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return message.replace(
            "{{greeting}}",
            greeting,
        )