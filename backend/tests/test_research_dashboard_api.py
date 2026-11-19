from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = "test-only-market-quality-token-with-32chars"


def test_quality_endpoint_reports_stored_candle_integrity(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "quality-api.sqlite3"))
    start = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    candles = []
    for index in range(3):
        price = 1.10 + index * 0.0001
        candles.append({
            "opened_at": (start + timedelta(minutes=5 * index)).isoformat(),
            "open": price, "high": price + 0.0002,
            "low": price - 0.0002, "close": price + 0.0001,
            "tick_volume": 100,
        })
    response = client.post(
        "/api/v1/mt5/candles",
        headers={"X-Bridge-Token": TOKEN},
        json={"symbol": "EURUSDm", "timeframe": "M5", "candles": candles},
    )
    assert response.status_code == 200

    result = client.get(
        "/api/v1/market-data/quality/EURUSDm/M5",
        headers={"X-Bridge-Token": TOKEN},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "healthy"
    assert result.json()["candles_checked"] == 3


def test_quality_endpoint_requires_bridge_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "quality-auth.sqlite3"))
    response = client.get("/api/v1/market-data/quality/EURUSDm/M5")
    assert response.status_code == 401


def test_local_dashboard_research_feed_never_enables_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "dashboard-research.sqlite3"))
    response = client.get("/api/v1/dashboard/research")
    assert response.status_code == 200
    payload = response.json()
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert len(payload["items"]) == 6
    assert all(item["signal"] == "insufficient_data" for item in payload["items"])
