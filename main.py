"""
Runs the automated collections pipeline.

This module acts as the composition root: it loads configuration, selects the
external adapters, wires the application components, and starts the pipeline.
"""

import logging
import os
from datetime import date

from dotenv import load_dotenv

from src.clients.galaxpay.mock_client import MockGalaxPayClient
from src.clients.galaxpay.real_client import RealGalaxPayClient
from src.clients.zapi.mock_client import MockZApiClient
from src.clients.zapi.real_client import RealZApiClient
from src.dispatchers.debt_dispatcher import DebtDispatcher
from src.dispatchers.message_dispatcher import MessageDispatcher
from src.performers.message_performer import MessagePerformer
from src.queue.debt_queue_repository import DebtQueueRepository
from src.queue.message_queue_repository import MessageQueueRepository


DEFAULT_DATABASE_PATH = "collection_pipeline.db"
WHATSAPP_DATABASE_PATH = "collection_pipeline_whatsapp.db"


def main() -> None:
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    pipeline_mode = os.getenv(
        "PIPELINE_MODE",
        "demo",
    ).lower()

    # WhatsApp integration tests use a separate database so real delivery tests
    # do not interfere with the state and idempotency of regular demo runs.
    database_path = (
        WHATSAPP_DATABASE_PATH
        if pipeline_mode == "whatsapp"
        else DEFAULT_DATABASE_PATH
    )

    # External dependencies are selected only at the composition root.
    # The core pipeline remains identical regardless of which adapters are used.
    if pipeline_mode == "demo":
        demo_phone = os.getenv(
            "DEMO_PHONE",
            "5511999999999",
        )

        galaxpay_client = MockGalaxPayClient(
            demo_phone=demo_phone
        )

        zapi_client = MockZApiClient()

    elif pipeline_mode == "whatsapp":
        # This mode keeps the source data mocked while exercising the real
        # WhatsApp integration. An explicit phone number is required because
        # the pipeline will perform a real external delivery.
        demo_phone = os.environ["DEMO_PHONE"]

        galaxpay_client = MockGalaxPayClient(
            demo_phone=demo_phone
        )

        zapi_client = RealZApiClient(
            instance_id=os.environ["ZAPI_INSTANCE_ID"],
            instance_token=os.environ["ZAPI_INSTANCE_TOKEN"],
            client_token=os.environ["ZAPI_CLIENT_TOKEN"],
        )

    elif pipeline_mode == "real":
        galaxpay_client = RealGalaxPayClient(
            galax_id=os.environ["GALAXPAY_ID"],
            galax_hash=os.environ["GALAXPAY_HASH"],
        )

        zapi_client = RealZApiClient(
            instance_id=os.environ["ZAPI_INSTANCE_ID"],
            instance_token=os.environ["ZAPI_INSTANCE_TOKEN"],
            client_token=os.environ["ZAPI_CLIENT_TOKEN"],
        )

    else:
        raise ValueError(
            "PIPELINE_MODE must be 'demo', 'whatsapp', or 'real'."
        )

    # Both queues share the same SQLite database so the handoff between them
    # can be committed atomically by the MessageQueueRepository.
    debt_queue_repository = DebtQueueRepository(
        database_path
    )

    message_queue_repository = MessageQueueRepository(
        database_path
    )

    # Application components depend on abstractions/repositories rather than
    # creating infrastructure dependencies internally.
    debt_dispatcher = DebtDispatcher(
        repository=debt_queue_repository
    )

    message_dispatcher = MessageDispatcher(
        debt_repository=debt_queue_repository,
        message_repository=message_queue_repository,
    )

    message_performer = MessagePerformer(
        repository=message_queue_repository,
        zapi_client=zapi_client,
    )

    reference_date = date.today()

    # Stage 1: retrieve candidate transactions and create eligible debt events.
    transactions = galaxpay_client.get_pending_transactions(
        reference_date
    )

    debt_events_queued = debt_dispatcher.dispatch(
        transactions
    )

    # Stage 2: group debt events by customer and atomically transfer
    # responsibility from the debt queue to the message queue.
    messages_queued = message_dispatcher.dispatch()

    # Stage 3: deliver fully prepared messages and own delivery retries/failures.
    messages_processed = message_performer.perform()

    print()
    print(f"Pipeline mode: {pipeline_mode.upper()}")
    print(f"Database: {database_path}")
    print("Pipeline completed.")
    print(f"Transactions retrieved: {len(transactions)}")
    print(f"New collection events queued: {debt_events_queued}")
    print(f"New customer messages queued: {messages_queued}")
    print(f"Customer messages processed: {messages_processed}")


if __name__ == "__main__":
    main()