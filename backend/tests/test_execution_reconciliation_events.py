from app.main import record_reconciliation_events
from app.operations.event_outbox import EventOutbox


def test_reconciliation_manual_review_creates_durable_critical_event(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "events.sqlite3"))
    result = {
        "results": [{
            "intent_id": "intent-123",
            "broker_order_id": "456",
            "result": "manual_review_required",
            "reasons": ["broker_magic_mismatch", "broker_symbol_mismatch"],
            "filled_volume_lots": 0.01,
            "requested_volume_lots": 0.01,
        }]
    }

    assert record_reconciliation_events(result) == 1
    events = EventOutbox().list_events()
    assert len(events) == 1
    assert events[0]["severity"] == "critical"
    assert events[0]["event_type"] == "execution_reconciliation_review"
    assert events[0]["delivery_status"] == "pending"


def test_reconciliation_event_is_idempotent_for_repeated_checks(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "events.sqlite3"))
    result = {
        "results": [{
            "intent_id": "intent-123",
            "result": "manual_review_required",
            "reasons": ["broker_magic_mismatch"],
        }]
    }

    record_reconciliation_events(result)
    record_reconciliation_events(result)
    assert len(EventOutbox().list_events()) == 1


def test_partial_fill_creates_warning_not_critical_event(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "events.sqlite3"))
    result = {
        "results": [{
            "intent_id": "intent-456",
            "broker_order_id": "789",
            "result": "reconciled_partial_fill",
            "filled_volume_lots": 0.004,
            "requested_volume_lots": 0.01,
        }]
    }

    assert record_reconciliation_events(result) == 1
    events = EventOutbox().list_events()
    assert events[0]["severity"] == "warning"
    assert events[0]["payload_json"]
