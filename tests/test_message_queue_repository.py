"""
Tests the transactional behavior of the collection message queue.

The tests verify that transferring responsibility from the debt queue to the
message queue happens atomically: either every source event is completed and
the message is persisted, or no state change is committed.
"""

from datetime import date

import pytest

from src.models.charge_message import ChargeMessage
from src.models.collectible_debt import CollectibleDebt
from src.queue.debt_queue_item import DebtQueueItem
from src.queue.debt_queue_repository import DebtQueueRepository
from src.queue.message_queue_item import MessageQueueItem
from src.queue.message_queue_repository import MessageQueueRepository


def create_debt_queue_item(
    transaction_id: int,
    customer_id: int,
    idempotency_key: str,
) -> DebtQueueItem:
    """Creates a debt queue item for repository integration tests."""

    debt = CollectibleDebt(
        galaxpay_transaction_id=transaction_id,
        customer_id=customer_id,
        customer_name="Luciano",
        customer_phones=["5511999999999"],
        amount_cents=100000,
        due_date=date(2026, 9, 16),
        bank_line=f"23793{transaction_id}000000000000000000000000000",
    )

    return DebtQueueItem(
        debt=debt,
        collection_day=0,
        idempotency_key=idempotency_key,
    )


def create_message_queue_item(
    source_event_keys: list[str],
) -> MessageQueueItem:
    """Creates a fully prepared message queue item for repository tests."""

    return MessageQueueItem(
        customer_phones=["5511999999999"],
        main_message=(
            "Bom dia, Luciano.\n\n"
            "Esta mensagem é referente aos seguintes débitos:"
        ),
        charges=[
            ChargeMessage(
                message=(
                    "Fatura no valor de R$ 1.000,00 que venceu no dia "
                    "16/09/2026. Segue a linha digitável:"
                ),
                bank_line="237931001000000000000000000000000000",
            ),
            ChargeMessage(
                message=(
                    "Fatura no valor de R$ 1.000,00 que venceu no dia "
                    "16/09/2026. Segue a linha digitável:"
                ),
                bank_line="237931002000000000000000000000000000",
            ),
        ],
        source_event_keys=source_event_keys,
        idempotency_key="message-test-001",
    )


def test_transfers_source_events_to_message_queue_atomically(tmp_path):
    database_path = tmp_path / "test.db"

    debt_repository = DebtQueueRepository(str(database_path))
    message_repository = MessageQueueRepository(str(database_path))

    # Both source events start in the first queue as PENDING.
    debt_repository.enqueue(
        create_debt_queue_item(1001, 501, "1001:0")
    )
    debt_repository.enqueue(
        create_debt_queue_item(1002, 501, "1002:0")
    )

    message = create_message_queue_item(
        ["1001:0", "1002:0"]
    )

    result = message_repository.enqueue_and_complete_source_events(message)

    assert result is True

    # Once the message queue assumes responsibility, the source events must no
    # longer be returned as pending by the first queue.
    assert debt_repository.get_pending_items() == []

    pending_messages = message_repository.get_pending_items()

    assert len(pending_messages) == 1
    assert pending_messages[0].main_message == message.main_message
    assert len(pending_messages[0].charges) == 2
    assert pending_messages[0].source_event_keys == [
        "1001:0",
        "1002:0",
    ]


def test_rolls_back_message_when_a_source_event_cannot_be_completed(tmp_path):
    database_path = tmp_path / "test.db"

    debt_repository = DebtQueueRepository(str(database_path))
    message_repository = MessageQueueRepository(str(database_path))

    # Only one of the two source events actually exists.
    debt_repository.enqueue(
        create_debt_queue_item(1001, 501, "1001:0")
    )

    message = create_message_queue_item(
        ["1001:0", "1002:0"]
    )

    # The repository must reject a partial responsibility transfer.
    with pytest.raises(
        RuntimeError,
        match="Not all source debt events could be completed",
    ):
        message_repository.enqueue_and_complete_source_events(message)

    # The existing source event must still be pending because the UPDATE was
    # rolled back together with the failed message INSERT.
    pending_debts = debt_repository.get_pending_items()

    assert len(pending_debts) == 1
    assert pending_debts[0].idempotency_key == "1001:0"

    # Most importantly, no orphan message may remain in the second queue.
    assert message_repository.get_pending_items() == []