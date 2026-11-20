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
