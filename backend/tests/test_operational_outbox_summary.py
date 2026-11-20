from datetime import datetime, timedelta, timezone

from app.operations.event_outbox import EventOutbox


def test_operational_summary_reports_delivery_counts_and_active_alerts(tmp_path):
    now = datetime.now(timezone.utc)
    outbox = EventOutbox(tmp_path / "outbox.sqlite3")
    outbox.record(
        event_key="summary-event-001",
        event_type="test_notice",
        severity="warning",
        message="A test operational event.",
        payload={"private_detail": "must not appear in summary"},
        occurred_at=now - timedelta(minutes=3),
    )
    transitions = outbox.reconcile_health_alerts(
        [{
            "code": "QUOTE_STALE",
            "symbol": "EURUSDm",
            "severity": "critical",
            "message": "Quote telemetry is stale.",
        }],
        now=now,
    )

    summary = outbox.operational_summary(now=now)

    assert transitions["alerts_created"] == 1
    assert summary["delivery"]["pending"] == 2
    assert summary["delivery"]["due_pending"] == 2
    assert summary["delivery"]["total"] == 2
    assert summary["active_alert_count"] == 1
    assert summary["active_alerts"][0]["event_type"] == "QUOTE_STALE"
    assert summary["recent_events"]
    assert summary["read_only"] is True
    assert summary["trading_enabled"] is False
    encoded = str(summary)
    assert "private_detail" not in encoded
    assert "lease_token" not in encoded


def test_operational_summary_reports_recovery_without_stale_active_alert(tmp_path):
    now = datetime.now(timezone.utc)
    outbox = EventOutbox(tmp_path / "outbox-recovery.sqlite3")
    alert = {
        "code": "ACCOUNT_STALE",
        "symbol": "all",
        "severity": "warning",
        "message": "Account snapshot is stale.",
    }
    outbox.reconcile_health_alerts([alert], now=now)
    outbox.reconcile_health_alerts([], now=now + timedelta(minutes=1))

    summary = outbox.operational_summary(now=now + timedelta(minutes=1))

    assert summary["active_alert_count"] == 0
    assert summary["active_alerts"] == []
    assert summary["delivery"]["pending"] == 2
    assert any(item["event_type"] == "HEALTH_RECOVERED" for item in summary["recent_events"])


def test_notification_health_dashboard_endpoint_is_read_only(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "api-outbox.sqlite3"))
    response = TestClient(app).get("/api/v1/dashboard/notification-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery"]["total"] == 0
    assert payload["active_alert_count"] == 0
    assert payload["execution_mode"] == "disabled"
    assert payload["trading_enabled"] is False
    assert payload["read_only"] is True
