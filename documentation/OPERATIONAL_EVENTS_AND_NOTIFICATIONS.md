# Operational events and notification outbox

## What is implemented

`app.operations.event_outbox.EventOutbox` provides a durable event journal and
notification outbox in the configured telemetry SQLite database. Events are
idempotent by caller-supplied event key. Severity is restricted to info, warning
and critical. Event payloads are JSON-encoded with non-finite numbers rejected.

Outbox workers can lease due messages, record delivery success, or schedule a
retry with a bounded attempt count. Lease tokens prevent a stale worker from
acknowledging a message after another worker has reclaimed its expired lease.
Terminal failures become `dead` for operator review. Event records themselves
are never updated by this module.

## Current limitation

This is the persistence and worker-coordination layer, not a live notification
service. No email, SMS, Telegram, Slack or webhook request is sent. A provider
adapter must be added separately with explicit credentials, destination
allowlists, TLS, strict timeouts, payload redaction, rate limits and delivery
tests. Do not store credentials in event payloads.

## Example use

```python
from app.operations.event_outbox import EventOutbox

events = EventOutbox()
event = events.record(
    event_key="monitoring:heartbeat-missing:2026-11-19T12",
    event_type="HEARTBEAT_MISSING",
    severity="critical",
    message="MT5 heartbeat is missing.",
    payload={"component": "mt5"},
)
```

A worker leases messages with `lease_due()`, sends them through an approved
provider adapter, then calls `complete()`. Failed attempts are rescheduled;
after the configured maximum, the message is marked dead. The worker must not
automatically convert notification failure into a trading-state change.

The event journal is operational observability only. It does not authorise,
queue or execute trades. Trading remains disabled by the system's existing
configuration and controls.


## Periodic health-event publishing

The `telemetry-health-monitor` Compose service checks broker heartbeat,
account snapshots and quotes every 30 seconds by default. It records each
distinct alert code/symbol once per UTC day in the durable event journal, using
an idempotency key to avoid repeated dashboard refreshes or polling cycles
creating duplicate events. The dashboard then displays those events and their
outbox status.

The outbox currently persists and leases notification work only. No email,
SMS, Telegram or other external delivery is configured or claimed. Add a
provider adapter only after an operator selects a destination and secret
management policy.


## Broker execution reconciliation events

The admin-only `GET /api/v1/monitoring/reconciliation` endpoint compares
persisted execution intents with authenticated MT5 demo order/deal history.
It does not infer rejection from missing history, and partial fills remain
distinct from full fills. Identity mismatches, multiple matching broker orders,
overfills and other ambiguous evidence are returned for manual review.

Reconciliation results are also published to the operational event journal:
manual-review outcomes create critical events, while partial fills create
warning events. Stable hashed event keys make repeated reconciliation checks
idempotent. Event payloads contain intent/order references and mismatch reasons,
not credentials. These events are operator alerts only; they do not retry or
resubmit a broker command.

The reconciliation endpoint is admin-authenticated and requires a fresh demo
terminal snapshot. It is not evidence that a live broker execution has been
validated; the demo execution adapter remains disabled unless separately
configured and explicitly enabled.
