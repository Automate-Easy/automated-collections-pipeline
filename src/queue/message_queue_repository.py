"""
Provides persistent storage for collection message queue items.

The repository persists fully prepared customer communications and guarantees
that message creation, source debt completion, and collection tracking records
are created atomically.
"""

import json
import sqlite3
from datetime import datetime

from src.models.charge_message import ChargeMessage
from src.queue.message_queue_item import MessageQueueItem
from src.queue.queue_status import QueueStatus


class MessageQueueRepository:

    def __init__(self, database_path: str = "collection_pipeline.db"):
        self.database_path = database_path
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize_database(self) -> None:
        # The second queue stores communications that are already fully prepared.
        # The performer should only need to read these instructions and deliver them.
        with self._get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS message_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_phones TEXT NOT NULL,
                    main_message TEXT NOT NULL,
                    charges TEXT NOT NULL,
                    source_event_keys TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,

                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )

            # Reporting is debt-oriented even though delivery is message-oriented.
            # Each row represents one collectible debt event and records the
            # communication responsible for delivering that collection notice.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    galaxpay_transaction_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    customer_name TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    due_date TEXT NOT NULL,
                    collection_day INTEGER NOT NULL,

                    collection_event_key TEXT NOT NULL UNIQUE,

                    message_id TEXT NOT NULL,
                    message_status TEXT NOT NULL,
                    message_sent_at TEXT,
                    message_last_error TEXT,

                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def enqueue_and_complete_source_events(
        self,
        item: MessageQueueItem,
    ) -> bool:
        now = datetime.now()

        # Charge instructions are stored as JSON because they form part of the
        # delivery payload and do not require independent relational processing.
        serialized_charges = json.dumps(
            [
                {
                    "message": charge.message,
                    "bank_line": charge.bank_line,
                }
                for charge in item.charges
            ]
        )

        with self._get_connection() as connection:
            try:
                # These operations belong to one logical transaction:
                #
                # 1. responsibility for delivery moves to the message queue;
                # 2. the originating debt events are considered completed;
                # 3. one tracking record is created for each collection event.
                #
                # If any operation fails, none of the state changes are committed.
                cursor = connection.execute(
                    """
                    INSERT INTO message_queue (
                        customer_phones,
                        main_message,
                        charges,
                        source_event_keys,
                        idempotency_key,
                        status,
                        attempt_count,
                        created_at,
                        updated_at,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (
                        json.dumps(item.customer_phones),
                        item.main_message,
                        serialized_charges,
                        json.dumps(item.source_event_keys),
                        item.idempotency_key,
                        item.status.value,
                        item.attempt_count,
                        now.isoformat(),
                        now.isoformat(),
                        item.last_error,
                    ),
                )

                # If this exact message already exists, there is nothing new to
                # transfer between queues.
                if cursor.rowcount == 0:
                    return False

                placeholders = ",".join(
                    "?" for _ in item.source_event_keys
                )

                # Read the source events before changing their processing state.
                # These records provide the debt-level business data used by the
                # collection tracking table.
                source_rows = connection.execute(
                    f"""
                    SELECT
                        galaxpay_transaction_id,
                        customer_id,
                        customer_name,
                        amount_cents,
                        due_date,
                        collection_day,
                        idempotency_key
                    FROM debt_queue
                    WHERE
                        idempotency_key IN ({placeholders})
                        AND status = ?
                    """,
                    (
                        *item.source_event_keys,
                        QueueStatus.PENDING.value,
                    ),
                ).fetchall()

                # Every event represented in the message must still be available
                # for transfer. Otherwise the transaction would be inconsistent.
                if len(source_rows) != len(item.source_event_keys):
                    raise RuntimeError(
                        "Not all source debt events could be completed."
                    )

                # Only pending source events may be consumed by the dispatcher.
                # This protects already completed events from being modified again.
                update_cursor = connection.execute(
                    f"""
                    UPDATE debt_queue
                    SET
                        status = ?,
                        updated_at = ?
                    WHERE
                        idempotency_key IN ({placeholders})
                        AND status = ?
                    """,
                    (
                        QueueStatus.PROCESSED.value,
                        now.isoformat(),
                        *item.source_event_keys,
                        QueueStatus.PENDING.value,
                    ),
                )

                # Every source event used to build the message must have been
                # transferred successfully. A partial update would leave the two
                # queues inconsistent, so the whole transaction must fail.
                if update_cursor.rowcount != len(item.source_event_keys):
                    raise RuntimeError(
                        "Not all source debt events could be completed."
                    )

                # Reporting keeps debt events as its unit of analysis.
                # Multiple debt events may therefore reference the same message.
                for row in source_rows:
                    connection.execute(
                        """
                        INSERT INTO collection_tracking (
                            galaxpay_transaction_id,
                            customer_id,
                            customer_name,
                            amount_cents,
                            due_date,
                            collection_day,
                            collection_event_key,
                            message_id,
                            message_status,
                            message_sent_at,
                            message_last_error,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                            row[6],
                            item.idempotency_key,
                            QueueStatus.PENDING.value,
                            None,
                            None,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )

                connection.commit()
                return True

            except Exception:
                # Explicit rollback makes the atomic boundary visible:
                # message creation, source completion, and tracking creation
                # either all succeed or none of them do.
                connection.rollback()
                raise

    def get_pending_items(self) -> list[MessageQueueItem]:
        with self._get_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    customer_phones,
                    main_message,
                    charges,
                    source_event_keys,
                    idempotency_key,
                    status,
                    attempt_count,
                    created_at,
                    updated_at,
                    last_error
                FROM message_queue
                WHERE status = ?
                ORDER BY created_at
                """,
                (QueueStatus.PENDING.value,),
            ).fetchall()

        items = []

        for row in rows:
            # Reconstruct the exact delivery instructions prepared by the
            # MessageDispatcher. No business decisions are made here.
            charges = [
                ChargeMessage(
                    message=charge["message"],
                    bank_line=charge["bank_line"],
                )
                for charge in json.loads(row[2])
            ]

            items.append(
                MessageQueueItem(
                    customer_phones=json.loads(row[0]),
                    main_message=row[1],
                    charges=charges,
                    source_event_keys=json.loads(row[3]),
                    idempotency_key=row[4],
                    status=QueueStatus(row[5]),
                    attempt_count=row[6],
                    created_at=datetime.fromisoformat(row[7]),
                    updated_at=datetime.fromisoformat(row[8]),
                    last_error=row[9],
                )
            )

        return items

    def mark_as_processed(
        self,
        idempotency_key: str,
    ) -> None:
        now = datetime.now()

        with self._get_connection() as connection:
            try:
                # Delivery state is updated both at message level and at the
                # debt-oriented tracking level within the same transaction.
                connection.execute(
                    """
                    UPDATE message_queue
                    SET
                        status = ?,
                        updated_at = ?,
                        last_error = NULL
                    WHERE idempotency_key = ?
                    """,
                    (
                        QueueStatus.PROCESSED.value,
                        now.isoformat(),
                        idempotency_key,
                    ),
                )

                connection.execute(
                    """
                    UPDATE collection_tracking
                    SET
                        message_status = ?,
                        message_sent_at = ?,
                        message_last_error = NULL,
                        updated_at = ?
                    WHERE message_id = ?
                    """,
                    (
                        QueueStatus.PROCESSED.value,
                        now.isoformat(),
                        now.isoformat(),
                        idempotency_key,
                    ),
                )

                connection.commit()

            except Exception:
                connection.rollback()
                raise

    def mark_as_failed(
        self,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        now = datetime.now()

        with self._get_connection() as connection:
            try:
                connection.execute(
                    """
                    UPDATE message_queue
                    SET
                        status = ?,
                        updated_at = ?,
                        last_error = ?
                    WHERE idempotency_key = ?
                    """,
                    (
                        QueueStatus.FAILED.value,
                        now.isoformat(),
                        error_message,
                        idempotency_key,
                    ),
                )

                connection.execute(
                    """
                    UPDATE collection_tracking
                    SET
                        message_status = ?,
                        message_sent_at = NULL,
                        message_last_error = ?,
                        updated_at = ?
                    WHERE message_id = ?
                    """,
                    (
                        QueueStatus.FAILED.value,
                        error_message,
                        now.isoformat(),
                        idempotency_key,
                    ),
                )

                connection.commit()

            except Exception:
                connection.rollback()
                raise