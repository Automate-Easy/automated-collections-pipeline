# Automated Collections Pipeline

A Python-based automated collections pipeline designed around queue-driven processing, idempotency, transactional consistency, and clear separation of responsibilities.

## About This Project

This repository is a **simplified and sanitized reconstruction of an automation architecture I originally designed for a real collections process in a corporate environment**.

The original solution operated within an enterprise ecosystem and included company-specific infrastructure, integrations, configurations, operational requirements, and proprietary code that cannot be shared publicly.

This version intentionally removes those details and reduces the process to its essential engineering concepts.

It is **not a copy of the original production code**. Instead, I rebuilt the core architecture in Python to demonstrate the design decisions behind the original automation in a small, readable, and self-contained project.

The implementation intentionally avoids RPA platforms so the underlying software engineering concepts are visible directly in the code.

---

## Overview

The pipeline identifies pending customer debts, determines which ones should trigger a collection event, groups eligible debts by customer, prepares the complete communication, and delivers it through WhatsApp.

The simplified implementation integrates with:

- **Galax Pay / Celcoin** for retrieving pending boleto transactions.
- **Z-API** for WhatsApp delivery.

Both integrations also have mock implementations, allowing the complete pipeline to run locally without credentials or external API calls.

---

## Architecture

![Automated Collections Pipeline Architecture](docs/architecture.png)

```text
                    ┌──────────────────────┐
                    │      Galax Pay       │
                    │   Real / Mock API    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    DebtDispatcher    │
                    │                      │
                    │ Collection schedule  │
                    │ Event idempotency    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Collectible Debt     │
                    │ Queue                │
                    │                      │
                    │ One item per debt    │
                    │ collection event     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ MessageDispatcher    │
                    │                      │
                    │ Groups by customer   │
                    │ Prepares messages    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Collection Message   │
                    │ Queue                │
                    │                      │
                    │ One item per         │
                    │ customer message     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ MessagePerformer     │
                    │                      │
                    │ Delivery + retries   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │        Z-API         │
                    │   Real / Mock API    │
                    └──────────┬───────────┘
                               │
                               ▼
                           WhatsApp
```

The production environment that inspired this project contained additional enterprise-specific components and operational concerns. They are intentionally omitted here to keep the repository focused on the architecture and engineering fundamentals.

---

## Why Two Queues?

The two queues represent different transactional units.

### Collectible Debt Queue

Each item represents a specific debt reaching a specific collection milestone.

For example:

```text
transaction 84721 at day -5 → 84721:-5
transaction 84721 at day  0 → 84721:0
transaction 84721 at day  5 → 84721:5
```

This allows the same unpaid debt to legitimately generate multiple collection events while preventing the same event from being processed twice.

### Collection Message Queue

Customers may have multiple debts requiring collection on the same day.

Instead of treating each debt as an independent WhatsApp process, the `MessageDispatcher` groups pending events by customer and creates one communication containing all currently eligible charges.

Once that message has been successfully persisted, responsibility moves from the debt queue to the message queue.

The message creation and completion of its source debt events happen inside the **same SQLite transaction**.

Either both operations succeed, or neither does.

---

## Collection Schedule

A pending debt becomes eligible when its distance from the due date matches:

```python
COLLECTION_DAYS = {-5, 0, 5, 10, 15}
```

Meaning:

| Day | Action |
|---:|---|
| -5 | 5 days before due date |
| 0 | Due date |
| 5 | 5 days overdue |
| 10 | 10 days overdue |
| 15 | 15 days overdue |

The Galax Pay client retrieves pending boleto transactions from the relevant date window, but it does **not** decide whether a debt should be collected.

That responsibility belongs to the business layer.

---

## Idempotency

Idempotency exists at both queue boundaries.

### Debt Event

A collection event is identified by:

```text
transaction_id + collection_day
```

Example:

```text
84721:5
```

This means transaction `84721` may legitimately be processed at different collection milestones, but the day-5 event cannot be created twice.

### Customer Message

A customer message is identified from:

```text
customer_id + sorted(source_event_keys)
```

The resulting identity is hashed with SHA-256.

This ensures that the exact same group of source events cannot accidentally generate duplicate message queue items.

---

## Message Preparation

The `MessageDispatcher` prepares all customer-facing content before creating the second queue item.

A message queue item already contains:

- Customer phone numbers
- Main message
- Prepared charge messages
- Boleto bank lines
- Source event keys
- Idempotency key
- Processing metadata

This keeps the `MessagePerformer` intentionally simple.

It does not know about Galax Pay transactions, debt rules, currency formatting, due-date semantics, or customer grouping.

Its responsibility is delivery.

---

## Failure Handling

Retries happen at the **individual outbound message level**, rather than replaying the entire customer communication.

Each outbound message may be attempted up to three times.

If a later message fails temporarily, messages that were already delivered successfully are not repeated during that processing execution.

If the same message fails three times, the corresponding message queue item is marked as:

```text
FAILED
```

Successful queue items are marked:

```text
PROCESSED
```

The Z-API integration uses its native delay capability for regular text messages, with a randomized delay between 1 and 10 seconds.

---

## Galax Pay Integration

The real Galax Pay client handles:

- API authentication
- Bearer token management
- Pending boleto filtering
- Date-window filtering
- Pagination
- Token refresh after an unauthorized response
- HTTP failures
- Empty result handling
- Unexpected response validation

Collection eligibility remains outside the API client.

This keeps provider-specific concerns separated from business rules.

---

## Demo and Real Modes

The repository can be executed without access to the original corporate environment.

### Demo

```env
PIPELINE_MODE=demo
```

Uses:

```text
MockGalaxPayClient
        ↓
Core pipeline
        ↓
MockZApiClient
```

No credentials are required and no external messages are sent.

Demo mode is the default.

### Real Integrations

```env
PIPELINE_MODE=real
```

Uses:

```text
RealGalaxPayClient
        ↓
Core pipeline
        ↓
RealZApiClient
```

This mode demonstrates how the simplified pipeline connects to the external providers used by this implementation and requires valid API credentials.

---

## Configuration

Create a `.env` file based on `.env.example`:

```env
PIPELINE_MODE=demo

GALAXPAY_ID=
GALAXPAY_HASH=

ZAPI_INSTANCE_ID=
ZAPI_INSTANCE_TOKEN=
ZAPI_CLIENT_TOKEN=
```

The real `.env` file is excluded from version control.

---

## Running the Project

Create and activate a virtual environment, then install the dependencies:

```bash
pip install -r requirements.txt
```

Run the pipeline:

```bash
python main.py
```

Without additional configuration, the application runs in safe demo mode.

---

## Tests

Run the test suite with:

```bash
python -m pytest -v
```

The tests cover core behaviors including:

- Collection eligibility
- Debt-event idempotency
- Queue persistence
- Customer grouping
- Message idempotency
- Atomic transfer between queues
- Transaction rollback
- Message-level retry behavior
- Failed queue item handling
- Galax Pay authentication
- Galax Pay request filtering
- Pagination
- Token refresh
- API error handling

External HTTP behavior is mocked in automated tests, so no real credentials are required.

---

## Design Principles

This simplified implementation intentionally emphasizes:

- Clear separation of responsibilities
- Dependency inversion through client interfaces
- Queue-based processing
- Explicit transactional boundaries
- Idempotent operations
- Failure isolation
- Provider-independent business rules
- Testable external integrations
- Safe local execution

The purpose of this repository is **not to reproduce the full enterprise solution**.

Its purpose is to provide a concise, sanitized implementation of the architecture and engineering principles behind a real automation system, making those decisions easy to inspect, run, test, and discuss.