"""
Provides persistent storage for collectible debt queue items.

The repository uses SQLite to keep queue state across executions and isolates
database operations from the collection pipeline's business logic.
"""

import json
import sqlite3
from datetime import date, datetime

from src.models.collectible_debt import CollectibleDebt
from src.queue.debt_queue_item import DebtQueueItem
from src.queue.queue_status import QueueStatus


class DebtQueueRepository:

    def __init__(self, database_path: str = "collection_pipeline.db"):
        self.database_path = database_path
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize_database(self) -> None:
        # Queue data is persisted so processing state survives application restarts.
        with self._get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS debt_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    galaxpay_transaction_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_phones TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    due_date TEXT NOT NULL,
                    bank_line TEXT NOT NULL,

                    collection_day INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,

                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )

    def enqueue(self, item: DebtQueueItem) -> bool:
        now = datetime.now()

        try:
            with self._get_connection() as connection:
                # Domain objects are flattened into a single queue record.
                # The unique idempotency key prevents the same collection event
                # from being queued more than once.
                connection.execute(
                    """
                    INSERT INTO debt_queue (
                        galaxpay_transaction_id,
                        customer_id,
                        customer_name,
                        customer_phones,
                        amount_cents,
                        due_date,
                        bank_line,
                        collection_day,
                        idempotency_key,
                        status,
                        attempt_count,
                        created_at,
                        updated_at,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.debt.galaxpay_transaction_id,
                        item.debt.customer_id,
                        item.debt.customer_name,
                        json.dumps(item.debt.customer_phones),
                        item.debt.amount_cents,
                        item.debt.due_date.isoformat(),
                        item.debt.bank_line,
                        item.collection_day,
                        item.idempotency_key,
                        item.status.value,
                        item.attempt_count,
                        now.isoformat(),
                        now.isoformat(),
                        item.last_error,
                    ),
                )

            return True

        except sqlite3.IntegrityError:
            # A duplicate idempotency key means this scheduled collection event
            # has already been queued and should not be processed again.
            return False

    def get_pending_items(self) -> list[DebtQueueItem]:
        with self._get_connection() as connection:
            # Only pending events are exposed to the next stage of the pipeline.
            rows = connection.execute(
                """
                SELECT
                    galaxpay_transaction_id,
                    customer_id,
                    customer_name,
                    customer_phones,
                    amount_cents,
                    due_date,
                    bank_line,
                    collection_day,
                    idempotency_key,
                    status,
                    attempt_count,
                    created_at,
                    updated_at,
                    last_error
                FROM debt_queue
                WHERE status = ?
                ORDER BY created_at
                """,
                (QueueStatus.PENDING.value,),
            ).fetchall()

        items = []

        for row in rows:
            # Reconstruct the original debt from its persisted representation.
            # The bank line remains attached to the same debt throughout the
            # pipeline so it can later be included in the customer communication.
            debt = CollectibleDebt(
                galaxpay_transaction_id=row[0],
                customer_id=row[1],
                customer_name=row[2],
                customer_phones=json.loads(row[3]),
                amount_cents=row[4],
                due_date=date.fromisoformat(row[5]),
                bank_line=row[6],
            )

            # Queue metadata is reconstructed separately from the debt itself,
            # preserving the separation between domain data and processing state.
            item = DebtQueueItem(
                debt=debt,
                collection_day=row[7],
                idempotency_key=row[8],
                status=QueueStatus(row[9]),
                attempt_count=row[10],
                created_at=datetime.fromisoformat(row[11]),
                updated_at=datetime.fromisoformat(row[12]),
                last_error=row[13],
            )

            items.append(item)

        return items