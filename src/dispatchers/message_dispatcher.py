"""
Groups pending debt events by customer and prepares collection messages.

The dispatcher owns the business and presentation decisions required to
transform debt events into fully prepared delivery instructions.
"""

import hashlib
from collections import defaultdict

from src.models.charge_message import ChargeMessage
from src.queue.debt_queue_item import DebtQueueItem
from src.queue.debt_queue_repository import DebtQueueRepository
from src.queue.message_queue_item import MessageQueueItem
from src.queue.message_queue_repository import MessageQueueRepository


class MessageDispatcher:

    def __init__(
        self,
        debt_repository: DebtQueueRepository,
        message_repository: MessageQueueRepository,
    ):
        self.debt_repository = debt_repository
        self.message_repository = message_repository

    def dispatch(self) -> int:
        # Only pending debt events are eligible to move to the message queue.
        pending_items = self.debt_repository.get_pending_items()

        # The first queue works at debt-event level, while the second queue works
        # at customer-message level. Grouping performs that responsibility shift.
        items_by_customer = self._group_by_customer(pending_items)

        enqueued_count = 0

        for customer_items in items_by_customer.values():
            message_item = self._build_message_queue_item(customer_items)

            # Message persistence and source-event completion happen atomically
            # inside the repository.
            if self.message_repository.enqueue_and_complete_source_events(
                message_item
            ):
                enqueued_count += 1

        return enqueued_count

    @staticmethod
    def _group_by_customer(
        items: list[DebtQueueItem],
    ) -> dict[int, list[DebtQueueItem]]:
        grouped_items = defaultdict(list)

        for item in items:
            grouped_items[item.debt.customer_id].append(item)

        return dict(grouped_items)

    def _build_message_queue_item(
        self,
        items: list[DebtQueueItem],
    ) -> MessageQueueItem:
        # Every debt in this group belongs to the same customer.
        first_item = items[0]
        customer = first_item.debt

        # Each debt becomes an independent delivery instruction containing
        # prepared text and its corresponding copyable bank line.
        charges = [
            self._build_charge_message(item)
            for item in items
        ]

        # Source keys preserve traceability between the debt queue and the
        # message queue. Sorting also makes message identity deterministic.
        source_event_keys = sorted(
            item.idempotency_key
            for item in items
        )

        return MessageQueueItem(
            customer_phones=customer.customer_phones,
            main_message=self._build_main_message(
                customer.customer_name,
                len(items),
            ),
            charges=charges,
            source_event_keys=source_event_keys,
            idempotency_key=self._build_idempotency_key(
                customer.customer_id,
                source_event_keys,
            ),
        )

    @staticmethod
    def _build_main_message(
        customer_name: str,
        charge_count: int,
    ) -> str:
        # The domain preserves the customer's full name as received from the
        # provider, while customer-facing communication uses only the first name.
        first_name = MessageDispatcher._get_first_name(customer_name)

        # Singular/plural presentation is resolved before the item reaches the
        # message queue, so the performer never needs this business knowledge.
        if charge_count == 1:
            debt_reference = "the following outstanding balance:"
        else:
            debt_reference = "the following outstanding balances:"

        # The greeting is intentionally left as a delivery-time placeholder.
        # The MessagePerformer will resolve it immediately before sending so the
        # greeting reflects the actual delivery time rather than dispatch time.
        return (
            f"{{{{greeting}}}}, {first_name}.\n\n"
            f"This message is regarding {debt_reference}"
        )

    @staticmethod
    def _get_first_name(full_name: str) -> str:
        # Normalize surrounding and repeated whitespace before extracting the
        # first name from the full customer name provided by Galax Pay.
        normalized_name = " ".join(full_name.split())

        if not normalized_name:
            return "Customer"

        return normalized_name.split()[0]

    @staticmethod
    def _build_charge_message(
        item: DebtQueueItem,
    ) -> ChargeMessage:
        debt = item.debt

        # Currency and date formatting are presentation concerns resolved here,
        # before the delivery instructions enter the message queue.
        formatted_amount = MessageDispatcher._format_brl(
            debt.amount_cents
        )
        formatted_due_date = debt.due_date.strftime("%m/%d/%Y")

        # collection_day is the historical schedule event captured when the debt
        # entered the first queue. It should not be recalculated at this stage.
        if item.collection_day > 0:
            charge_text = (
                f"Invoice of {formatted_amount} that was due on "
                f"{formatted_due_date}."
            )
        elif item.collection_day < 0:
            charge_text = (
                f"Invoice of {formatted_amount} due on "
                f"{formatted_due_date}."
            )
        else:
            charge_text = (
                f"Invoice of {formatted_amount} due today, "
                f"{formatted_due_date}."
            )

        message = (
            f"{charge_text} "
            "Here is the payment code:"
        )

        return ChargeMessage(
            message=message,
            bank_line=debt.bank_line,
        )

    @staticmethod
    def _format_brl(amount_cents: int) -> str:
        # Monetary values remain as integer cents until presentation time.
        amount = amount_cents / 100

        # Customer-facing messages use English numeric separators while
        # preserving BRL as the original currency.
        return f"R$ {amount:,.2f}"

    @staticmethod
    def _build_idempotency_key(
        customer_id: int,
        source_event_keys: list[str],
    ) -> str:
        # A message is uniquely identified by the customer and the exact set of
        # debt events that originated it. Input order must not affect identity.
        raw_identity = (
            f"{customer_id}|"
            f"{'|'.join(sorted(source_event_keys))}"
        )

        return hashlib.sha256(
            raw_identity.encode("utf-8")
        ).hexdigest()