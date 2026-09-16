"""
Tests message delivery, retry behavior, exponential backoff,
and final queue item status.

The tests use a fake Z-API client and an injected sleep function so delivery
behavior can be validated without external API calls or real delays.
"""

import sqlite3
from datetime import date
from unittest.mock import patch

from src.clients.zapi.client import ZApiClient
from src.clients.zapi.send_result import ZApiSendResult
from src.dispatchers.message_dispatcher import MessageDispatcher
from src.models.collectible_debt import CollectibleDebt
from src.performers.message_performer import MessagePerformer
from src.queue.debt_queue_item import DebtQueueItem
from src.queue.debt_queue_repository import DebtQueueRepository
from src.queue.message_queue_repository import MessageQueueRepository
from src.queue.queue_status import QueueStatus


class FakeZApiClient(ZApiClient):

    def __init__(
        self,
        failures_before_success: dict[str, int] | None = None,
    ):
        self.failures_before_success = failures_before_success or {}
        self.attempts = {}
        self.successful_messages = []
        self.text_delays = []

    def send_text(
        self,
        phone: str,
        message: str,
        delay_seconds: int | None = None,
    ) -> ZApiSendResult:
        self.text_delays.append(delay_seconds)

        return self._send(
            message_key="main",
            phone=phone,
            message=message,
        )

    def send_copy_code(
        self,
        phone: str,
        message: str,
        code: str,
    ) -> ZApiSendResult:
        return self._send(
            message_key=code,
            phone=phone,
            message=message,
        )

    def _send(
        self,
        message_key: str,
        phone: str,
        message: str,
    ) -> ZApiSendResult:
        current_attempt = self.attempts.get(message_key, 0) + 1
        self.attempts[message_key] = current_attempt

        failures_required = self.failures_before_success.get(
            message_key,
            0,
        )

        if current_attempt <= failures_required:
            raise RuntimeError(
                f"Simulated Z-API failure for {message_key}"
            )

        self.successful_messages.append(
            (
                message_key,
                phone,
                message,
            )
        )

        return ZApiSendResult(
            zaap_id=f"zaap-{message_key}",
            message_id=f"message-{message_key}",
            id=f"id-{message_key}",
        )


def create_message_queue_item(
    database_path: str,
) -> tuple[
    DebtQueueRepository,
    MessageQueueRepository,
]:
    debt_repository = DebtQueueRepository(database_path)
    message_repository = MessageQueueRepository(database_path)

    debts = [
        DebtQueueItem(
            debt=CollectibleDebt(
                galaxpay_transaction_id=1001,
                customer_id=5001,
                customer_name="John Doe",
                customer_phones=["5511999999999"],
                amount_cents=100000,
                due_date=date(2026, 9, 11),
                bank_line="BANK-LINE-1001",
            ),
            collection_day=5,
            idempotency_key="1001:5",
        ),
        DebtQueueItem(
            debt=CollectibleDebt(
                galaxpay_transaction_id=1002,
                customer_id=5001,
                customer_name="John Doe",
                customer_phones=["5511999999999"],
                amount_cents=50000,
                due_date=date(2026, 9, 21),
                bank_line="BANK-LINE-1002",
            ),
            collection_day=-5,
            idempotency_key="1002:-5",
        ),
    ]

    for item in debts:
        debt_repository.enqueue(item)

    dispatcher = MessageDispatcher(
        debt_repository=debt_repository,
        message_repository=message_repository,
    )

    dispatcher.dispatch()

    return debt_repository, message_repository


def get_message_status(
    database_path: str,
) -> tuple[str, str | None]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT
                status,
                last_error
            FROM message_queue
            LIMIT 1
            """
        ).fetchone()

    return row[0], row[1]


@patch(
    "src.performers.message_performer.random.randint",
    return_value=7,
)
def test_performer_retries_only_failed_message_and_processes_item(
    mocked_randint,
    tmp_path,
):
    database_path = str(tmp_path / "test.db")

    _, message_repository = create_message_queue_item(
        database_path
    )

    # The second charge fails twice and succeeds on its third attempt.
    fake_client = FakeZApiClient(
        failures_before_success={
            "BANK-LINE-1002": 2,
        }
    )

    retry_delays = []

    performer = MessagePerformer(
        repository=message_repository,
        zapi_client=fake_client,
        sleep_fn=retry_delays.append,
    )

    processed_count = performer.perform()

    status, last_error = get_message_status(database_path)

    assert processed_count == 1
    assert status == QueueStatus.PROCESSED.value
    assert last_error is None

    assert fake_client.attempts["main"] == 1
    assert fake_client.attempts["BANK-LINE-1001"] == 1
    assert fake_client.attempts["BANK-LINE-1002"] == 3

    # Previous successful messages must not be repeated when a later
    # individual message requires a retry.
    assert len(fake_client.successful_messages) == 3

    # Two consecutive failures produce exponential delays of 1s and 2s.
    assert retry_delays == [1, 2]

    # Native Z-API pacing is applied only to regular text messages.
    assert fake_client.text_delays == [7]

    mocked_randint.assert_called_once_with(1, 10)


@patch(
    "src.performers.message_performer.random.randint",
    return_value=4,
)
def test_performer_fails_item_after_three_attempts_of_same_message(
    mocked_randint,
    tmp_path,
):
    database_path = str(tmp_path / "test.db")

    _, message_repository = create_message_queue_item(
        database_path
    )

    # Three required failures mean the second charge never succeeds.
    fake_client = FakeZApiClient(
        failures_before_success={
            "BANK-LINE-1002": 3,
        }
    )

    retry_delays = []

    performer = MessagePerformer(
        repository=message_repository,
        zapi_client=fake_client,
        sleep_fn=retry_delays.append,
    )

    processed_count = performer.perform()

    status, last_error = get_message_status(database_path)

    assert processed_count == 0
    assert status == QueueStatus.FAILED.value
    assert last_error is not None
    assert "BANK-LINE-1002" in last_error

    assert fake_client.attempts["main"] == 1
    assert fake_client.attempts["BANK-LINE-1001"] == 1
    assert fake_client.attempts["BANK-LINE-1002"] == 3

    # Main and charge #1 succeeded exactly once. They were not replayed
    # when charge #2 exhausted its retry limit.
    successful_keys = [
        message[0]
        for message in fake_client.successful_messages
    ]

    assert successful_keys == [
        "main",
        "BANK-LINE-1001",
    ]

    # There is no delay after the final failed attempt because no retry follows.
    assert retry_delays == [1, 2]

    assert fake_client.text_delays == [4]

    mocked_randint.assert_called_once_with(1, 10)