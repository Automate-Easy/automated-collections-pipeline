"""
Tests the DebtDispatcher and collectible debt queue behavior.

The tests verify collection eligibility, idempotent dispatching, and the
reconstruction of pending queue items from persistent storage.
"""

from datetime import date, timedelta

from src.dispatchers.debt_dispatcher import DebtDispatcher
from src.queue.debt_queue_repository import DebtQueueRepository
from src.queue.queue_status import QueueStatus


def create_transaction(
    transaction_id: int,
    customer_id: int,
    days_from_due_date: int,
) -> dict:
    """
    Creates a Galax Pay-shaped transaction for testing.

    The helper preserves the relevant external API structure so tests exercise
    the same mapper used by the real and mock integrations.
    """

    return {
        "galaxPayId": transaction_id,
        "value": 12999,
        "payday": (
            date.today() - timedelta(days=days_from_due_date)
        ).isoformat(),

        # Each fake transaction receives a deterministic bank line so tests can
        # verify that payment information survives the persistence round trip.
        "Boleto": {
            "bankLine": f"23793{transaction_id}000000000000000000000000000",
        },

        "Charge": [
            {
                "Customer": {
                    "galaxPayId": customer_id,
                    "name": f"Customer {customer_id}",
                    "phones": [5511999999999],
                }
            }
        ],
    }


def test_dispatches_only_collectible_debts_and_prevents_duplicates(tmp_path):
    database_path = tmp_path / "test.db"

    repository = DebtQueueRepository(str(database_path))
    dispatcher = DebtDispatcher(repository)

    # Five transactions match the collection schedule.
    # The remaining three should be ignored by the dispatcher.
    transactions = [
        create_transaction(1001, 501, -5),
        create_transaction(1002, 502, -3),
        create_transaction(1003, 503, 0),
        create_transaction(1004, 504, 5),
        create_transaction(1005, 505, 7),
        create_transaction(1006, 506, 10),
        create_transaction(1007, 507, 15),
        create_transaction(1008, 508, 20),
    ]

    first_run = dispatcher.dispatch(transactions)
    second_run = dispatcher.dispatch(transactions)

    # The first run creates five collection events.
    # Reprocessing the same input must not create duplicates.
    assert first_run == 5
    assert second_run == 0


def test_retrieves_pending_queue_items(tmp_path):
    database_path = tmp_path / "test.db"

    repository = DebtQueueRepository(str(database_path))
    dispatcher = DebtDispatcher(repository)

    transactions = [
        create_transaction(2001, 601, 0),
        create_transaction(2002, 602, 5),
        create_transaction(2003, 603, 7),
    ]

    dispatcher.dispatch(transactions)

    # Queue records should be reconstructed as complete DebtQueueItem objects,
    # not exposed as raw SQLite rows.
    pending_items = repository.get_pending_items()

    assert len(pending_items) == 2

    first_item = pending_items[0]

    assert first_item.debt.galaxpay_transaction_id == 2001
    assert first_item.debt.customer_id == 601
    assert first_item.debt.customer_name == "Customer 601"
    assert first_item.debt.customer_phones == ["5511999999999"]
    assert first_item.debt.amount_cents == 12999

    # Payment information must remain associated with the original debt after
    # being persisted and reconstructed from the queue.
    expected_bank_line = f"23793{2001}000000000000000000000000000"
    assert first_item.debt.bank_line == expected_bank_line

    # Processing metadata must also survive the persistence round trip.
    assert first_item.collection_day == 0
    assert first_item.idempotency_key == "2001:0"
    assert first_item.status == QueueStatus.PENDING
    assert first_item.attempt_count == 0
    assert first_item.created_at is not None
    assert first_item.updated_at is not None
    assert first_item.last_error is None