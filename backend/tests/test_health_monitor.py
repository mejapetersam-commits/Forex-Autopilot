from datetime import datetime, timezone
from app.market_data.telemetry_store import TelemetryStore
from app.operations.event_outbox import EventOutbox
from app.operations.health_monitor import run_health_monitor_cycle

def test_health_monitor_persists_idempotent_operator_events(monkeypatch, tmp_path):
    database = tmp_path / "health-monitor.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    first = run_health_monitor_cycle(now=now)
    second = run_health_monitor_cycle(now=now)
    events = EventOutbox(database).list_events(limit=20)
    assert first["health_status"] == "critical"
    assert first["alerts_detected"] == 3
    assert second["alerts_detected"] == 3
    assert len(events) == 3
    assert {event["event_type"] for event in events} == {
        "HEARTBEAT_MISSING", "ACCOUNT_SNAPSHOT_MISSING", "QUOTES_MISSING"
    }
    assert all(event["delivery_status"] == "pending" for event in events)

def test_health_monitor_rejects_naive_clock(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "health-naive.sqlite3"))
    try:
        run_health_monitor_cycle(now=datetime(2026, 11, 19))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive monitor time must fail")


def test_health_monitor_records_recovery_and_reactivation(monkeypatch, tmp_path):
    import app.operations.health_monitor as monitor

    database = tmp_path / "health-recovery.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))
    alert = {
        "code": "QUOTE_STALE",
        "severity": "warning",
        "message": "Quote telemetry is stale.",
        "symbol": "EURUSDM",
    }
    states = [
        {"status": "warning", "alerts": [alert], "assessed_at": "2026-11-19T12:00:00+00:00"},
        {"status": "healthy", "alerts": [], "assessed_at": "2026-11-19T12:01:00+00:00"},
        {"status": "warning", "alerts": [alert], "assessed_at": "2026-11-19T12:02:00+00:00"},
    ]
    monkeypatch.setattr(monitor, "assess_system_health", lambda *args, **kwargs: states.pop(0))
    first = run_health_monitor_cycle(now=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))
    recovered = run_health_monitor_cycle(now=datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc))
    again = run_health_monitor_cycle(now=datetime(2026, 11, 19, 12, 2, tzinfo=timezone.utc))

    events = EventOutbox(database).list_events(limit=20)
    assert first["events_recorded"] == 1
    assert first["alerts_still_active"] == 1
    assert recovered["events_resolved"] == 1
    assert recovered["alerts_still_active"] == 0
    assert again["events_recorded"] == 1
    assert again["alerts_still_active"] == 1
    assert [event["event_type"] for event in events].count("HEALTH_RECOVERED") == 1
    assert len(events) == 3
