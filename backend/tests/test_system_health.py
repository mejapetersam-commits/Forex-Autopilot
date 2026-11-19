from datetime import datetime, timedelta, timezone

from app.monitoring.health import assess_system_health


def test_health_is_healthy_with_fresh_connected_telemetry():
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    heartbeat = {"terminal_connected": True, "observed_at": stamp}
    account = {"equity": 1000, "margin": 200, "observed_at": stamp}
    quotes = [{"symbol": "EURUSDm", "observed_at": stamp}]
    result = assess_system_health(heartbeat, account, quotes, now=now)
    assert result["status"] == "healthy"
    assert result["alerts"] == []
    assert result["trading_enabled"] is False


def test_health_reports_missing_and_stale_telemetry_as_critical():
    now = datetime.now(timezone.utc)
    result = assess_system_health(None, None, [], now=now)
    assert result["status"] == "critical"
    codes = {alert["code"] for alert in result["alerts"]}
    assert {"HEARTBEAT_MISSING", "ACCOUNT_SNAPSHOT_MISSING", "QUOTES_MISSING"} <= codes


def test_health_warns_on_low_margin_and_stale_quote():
    now = datetime.now(timezone.utc)
    fresh = now.isoformat()
    stale = (now - timedelta(minutes=5)).isoformat()
    heartbeat = {"terminal_connected": True, "observed_at": fresh}
    account = {"equity": 100, "margin": 60, "observed_at": fresh}
    quotes = [{"symbol": "EURUSDm", "observed_at": stale}]
    result = assess_system_health(heartbeat, account, quotes, now=now)
    codes = {alert["code"] for alert in result["alerts"]}
    assert "MARGIN_LEVEL_WARNING" in codes
    assert "QUOTE_STALE" in codes
    assert result["status"] == "degraded"



def test_monitoring_health_api_is_authenticated(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", "test-health-monitoring-token-32-chars")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "health-api.sqlite3"))
    client = TestClient(app)
    denied = client.get("/api/v1/monitoring/health")
    assert denied.status_code == 401
    accepted = client.get(
        "/api/v1/monitoring/health",
        headers={"X-Bridge-Token": "test-health-monitoring-token-32-chars"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "critical"
    assert accepted.json()["trading_enabled"] is False
