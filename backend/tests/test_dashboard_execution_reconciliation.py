from fastapi.testclient import TestClient

import app.main as main
from app.execution.ledger import ExecutionLedger
from app.operations.event_outbox import EventOutbox


def test_execution_reconciliation_dashboard_exposes_sanitized_partial_fill(tmp_path, monkeypatch):
    path = str(tmp_path / "shared.sqlite3")
    ledger = ExecutionLedger(path)
    outbox = EventOutbox(path)
    key = "dashboard-partial"
    ledger.create_intent(key, {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.099, "take_profit": 1.102,
    })
    ledger.transition(key, "approved", event_type="preflight_approved")
    ledger.transition(key, "submitted", event_type="broker_submit")
    ledger.transition(key, "acknowledged", event_type="broker_ack", broker_order_id="12345")
    ledger.transition(
        key, "partially_filled", event_type="broker_history_partial_fill",
        broker_order_id="12345",
        details={
            "filled_volume_lots": 0.006, "requested_volume_lots": 0.01,
            "average_fill_price": 1.1005,
            "fill_details": [{
                "deal_ticket": "1001", "volume_lots": 0.006,
                "price": 1.1005, "position_id": "9001",
                "occurred_at": "2026-11-20T08:00:00+00:00",
            }],
            "deal_tickets": ["1001"], "position_ids": ["9001"],
        },
    )
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "EventOutbox", lambda: outbox)

    response = TestClient(main.app).get("/api/v1/dashboard/execution-reconciliation")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["partial_fill_count"] == 1
    assert body["intents"][0]["result"] == "partial_fill_confirmed"
    assert body["intents"][0]["average_fill_price"] == 1.1005
    assert body["intents"][0]["position_ids"] == ["9001"]
    assert "payload" not in body["intents"][0]
    assert body["read_only"] is True
    assert body["trading_enabled"] is False


def test_execution_reconciliation_dashboard_surfaces_manual_review_events(tmp_path, monkeypatch):
    path = str(tmp_path / "events.sqlite3")
    ledger = ExecutionLedger(path)
    outbox = EventOutbox(path)
    outbox.record(
        event_key="exec-recon:dashboard:manual-review",
        event_type="execution_reconciliation_review",
        severity="critical",
        message="Broker execution evidence requires manual review.",
        payload={
            "intent_id": "unknown-intent",
            "outcome": "manual_review_required",
            "reasons": ["broker_magic_mismatch"],
            "broker_order_id": "12345",
        },
    )
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "EventOutbox", lambda: outbox)

    body = TestClient(main.app).get(
        "/api/v1/dashboard/execution-reconciliation"
    ).json()
    assert body["status"] == "review_required"
    assert body["counts"]["manual_review_count"] == 1
    assert body["manual_review_events"][0]["reasons"] == ["broker_magic_mismatch"]
