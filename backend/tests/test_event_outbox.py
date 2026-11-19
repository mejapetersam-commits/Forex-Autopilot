from datetime import datetime, timedelta, timezone

import pytest

from app.operations.event_outbox import EventOutbox


def test_record_is_idempotent_and_filterable(tmp_path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    first = outbox.record(
        event_key="heartbeat:missing:2026-11-19",
        event_type="HEARTBEAT_MISSING",
        severity="critical",
        message="MT5 heartbeat is missing.",
        payload={"component": "mt5"},
    )
    second = outbox.record(
        event_key="heartbeat:missing:2026-11-19",
        event_type="HEARTBEAT_MISSING",
        severity="critical",
        message="duplicate should not replace original",
    )
    assert first["event_id"] == second["event_id"]
    assert len(outbox.list_events(severity="critical")) == 1
    assert outbox.list_events()[0]["message"] == "MT5 heartbeat is missing."


def test_lease_delivery_and_retry(tmp_path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    event = outbox.record(
        event_key="quote:stale:eurusdm",
        event_type="QUOTE_STALE",
        severity="warning",
        message="Quote is stale.",
        occurred_at=now,
    )
    leased = outbox.lease_due(now=now)
    assert len(leased) == 1
    assert leased[0]["event_id"] == event["event_id"]
    assert outbox.complete(
        event["event_id"], leased[0]["lease_token"], delivered=False,
        error="provider unavailable", retry_after_seconds=30, now=now,
    ) == "pending"
    assert outbox.lease_due(now=now + timedelta(seconds=31))[0]["event_id"] == event["event_id"]


def test_stale_worker_cannot_complete_released_lease(tmp_path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    event = outbox.record(
        event_key="margin:warning:1", event_type="MARGIN_WARNING",
        severity="warning", message="Margin is low.", occurred_at=now,
    )
    first = outbox.lease_due(now=now, lease_seconds=5)[0]
    second = outbox.lease_due(now=now + timedelta(seconds=6), lease_seconds=5)[0]
    with pytest.raises(ValueError, match="lease"):
        outbox.complete(event["event_id"], first["lease_token"], delivered=True, now=now)
    assert outbox.complete(event["event_id"], second["lease_token"], delivered=True, now=now) == "delivered"


def test_invalid_severity_and_key_are_rejected(tmp_path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError):
        outbox.record(event_key="bad key", event_type="X", severity="critical", message="x")
    with pytest.raises(ValueError):
        outbox.record(event_key="valid.key", event_type="X", severity="fatal", message="x")
