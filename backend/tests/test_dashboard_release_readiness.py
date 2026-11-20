from fastapi.testclient import TestClient

import app.main as main


def healthy_inputs(monkeypatch):
    monkeypatch.setattr(main, "dashboard_overview", lambda: {
        "bridge_connected": True,
        "heartbeat": {"fresh": True},
        "account": {"fresh": True},
    })
    monkeypatch.setattr(main, "dashboard_data_readiness", lambda **kwargs: {
        "status": "ready", "ready_series": 8, "series_checked": 8,
        "minimum_candles": 500,
    })
    monkeypatch.setattr(main, "dashboard_operations", lambda: {
        "reconciliation": {
            "status": "complete", "protection_issues": [],
            "orphaned_positions": [], "mismatched_positions": [],
        },
    })
    monkeypatch.setattr(main, "dashboard_recovery_status", lambda: {
        "backups": {"fresh_verified_backup": True, "invalid_count": 0},
        "backup_worker": {"fresh": True},
    })
    monkeypatch.setattr(main, "dashboard_execution_reconciliation", lambda **kwargs: {
        "intents_checked": 1,
        "counts": {
            "partial_fill_count": 0, "reconciled_count": 1,
            "awaiting_history_count": 0, "unknown_count": 0,
            "manual_review_count": 0,
        },
        "order_counts": {"total": 1, "pending": 0, "terminal": 1},
    })
    monkeypatch.setattr(main, "dashboard_demo_observation", lambda **kwargs: {
        "deal_totals": {"deal_count": 2},
    })


def test_release_readiness_reports_automated_pass_but_keeps_manual_gates_open(monkeypatch):
    healthy_inputs(monkeypatch)
    response = TestClient(main.app).get("/api/v1/dashboard/release-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["automated_passed"] == body["automated_total"]
    assert body["manual_validation_required"] == 4
    assert all(gate["status"] == "operator_validation_required" for gate in body["manual_gates"])
    assert body["execution_enabled"] is False
    assert body["trading_enabled"] is False
    assert body["live_trading_supported"] is False
    assert body["read_only"] is True


def test_release_readiness_flags_stale_telemetry_and_unresolved_execution(monkeypatch):
    healthy_inputs(monkeypatch)
    monkeypatch.setattr(main, "dashboard_overview", lambda: {
        "bridge_connected": False, "heartbeat": {"fresh": False},
        "account": {"fresh": False},
    })
    monkeypatch.setattr(main, "dashboard_execution_reconciliation", lambda **kwargs: {
        "intents_checked": 1,
        "counts": {
            "partial_fill_count": 1, "reconciled_count": 0,
            "awaiting_history_count": 1, "unknown_count": 1,
            "manual_review_count": 0,
        },
        "order_counts": {"total": 1, "pending": 1, "terminal": 0},
    })
    body = TestClient(main.app).get("/api/v1/dashboard/release-readiness").json()
    states = {gate["key"]: gate["status"] for gate in body["automated_gates"]}
    assert states["broker_telemetry"] == "attention_required"
    assert states["broker_reconciliation"] == "attention_required"
    assert body["status"] == "not_ready"
