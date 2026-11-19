from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = "test-only-backtest-bridge-token-with-32-chars"


def candles(count=180):
    rows = []
    price = 1.10
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(count):
        next_price = price + 0.0002 + index * 0.000008
        rows.append({
            "opened_at": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": max(price, next_price) + 0.00015,
            "low": min(price, next_price) - 0.00015,
            "close": next_price,
            "tick_volume": 100,
        })
        price = next_price
    return rows


def test_backtest_api_uses_stored_candles_and_is_research_only(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "backtest.sqlite3"))
    headers = {"X-Bridge-Token": TOKEN}
    stored = client.post(
        "/api/v1/mt5/candles",
        headers=headers,
        json={"symbol": "EURUSDm", "timeframe": "H1", "candles": candles()},
    )
    assert stored.status_code == 200

    response = client.get(
        "/api/v1/backtests/run/EURUSDm/H1?pip_value_per_lot=10&spread_pips=1.2",
        headers=headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["candles_tested"] == 180
    assert result["execution_mode"] == "disabled"
    assert result["trading_enabled"] is False
    assert result["assumptions"]["spread_pips"] == 1.2
    assert "total_trades" in result
    assert "max_drawdown_pct" in result


def test_backtest_api_requires_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "backtest-auth.sqlite3"))
    response = client.get("/api/v1/backtests/run/EURUSDm/H1?pip_value_per_lot=10")
    assert response.status_code == 401
