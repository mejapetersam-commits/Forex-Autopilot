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


def test_health_rejects_mismatched_broker_server_snapshots():
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    heartbeat = {
        "server": "Broker-Demo-1",
        "terminal_connected": True,
        "observed_at": stamp,
    }
    account = {
        "server": "Broker-Demo-2",
        "equity": 1000,
        "margin": 200,
        "observed_at": stamp,
    }
    quotes = [{"symbol": "EURUSDm", "observed_at": stamp}]

    result = assess_system_health(heartbeat, account, quotes, now=now)

    assert result["status"] == "critical"
    assert "BROKER_SERVER_MISMATCH" in {alert["code"] for alert in result["alerts"]}


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



def test_health_ignores_quotes_for_unconfigured_legacy_symbols(monkeypatch):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    stale = (now - timedelta(days=5)).isoformat()
    monkeypatch.delenv("FOREX_AUTOPILOT_MONITORED_SYMBOLS", raising=False)
    monkeypatch.delenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", raising=False)

    result = assess_system_health(
        {"terminal_connected": True, "observed_at": stamp},
        {"equity": 1000, "margin": 200, "observed_at": stamp},
        [
            {"symbol": "EURUSD", "observed_at": stale},
            {"symbol": "EURUSDM", "observed_at": stamp},
            {"symbol": "GBPUSDM", "observed_at": stamp},
        ],
        now=now,
    )

    assert result["status"] == "healthy"
    assert result["alerts"] == []
    market = next(item for item in result["checks"] if item["name"] == "market_quotes")
    assert market["fresh_count"] == 2
    assert market["total_count"] == 2


def test_health_still_alerts_on_stale_configured_symbol(monkeypatch):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    stale = (now - timedelta(minutes=5)).isoformat()
    monkeypatch.setenv("FOREX_AUTOPILOT_MONITORED_SYMBOLS", "EURUSDm,GBPUSDm")

    result = assess_system_health(
        {"terminal_connected": True, "observed_at": stamp},
        {"equity": 1000, "margin": 200, "observed_at": stamp},
        [
            {"symbol": "EURUSDm", "observed_at": stale},
            {"symbol": "GBPUSDm", "observed_at": stamp},
            {"symbol": "EURUSD", "observed_at": stale},
        ],
        now=now,
    )

    stale_alerts = [a for a in result["alerts"] if a["code"] == "QUOTE_STALE"]
    assert len(stale_alerts) == 1
    assert stale_alerts[0]["symbol"] == "EURUSDm"
    market = next(item for item in result["checks"] if item["name"] == "market_quotes")
    assert market["total_count"] == 2


def test_explicit_monitoring_symbols_override_dashboard_symbols(monkeypatch):
    from app.monitoring.health import monitoring_symbols

    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm,GBPUSDm")
    monkeypatch.setenv("FOREX_AUTOPILOT_MONITORED_SYMBOLS", "GBPUSDm")
    assert monitoring_symbols() == {"GBPUSDM"}
