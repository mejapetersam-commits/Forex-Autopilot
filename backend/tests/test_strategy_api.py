from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = "test-only-bridge-token-with-32-plus-chars"


def candle_payload(direction=1, count=100):
    rows = []
    price = 1.10
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for index in range(count):
        next_price = price + direction * (0.0002 + index * 0.00001)
        rows.append({
            "opened_at": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": max(price, next_price) + 0.0002,
            "low": min(price, next_price) - 0.0002,
            "close": next_price,
            "tick_volume": 100,
        })
        price = next_price
    return rows


def test_strategy_signal_endpoint_reads_stored_candles_and_never_enables_execution(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "strategy.sqlite3")
    )
    headers = {"X-Bridge-Token": TOKEN}

    ingested = client.post(
        "/api/v1/mt5/candles",
        headers=headers,
        json={
            "symbol": "EURUSDm",
            "timeframe": "H1",
            "candles": candle_payload(),
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["candles_received"] == 100

    response = client.get(
        "/api/v1/strategy/signal/EURUSDm/H1",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["signal"] == "buy"
    assert payload["execution_enabled"] is False
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert payload["candidate_levels"]["stop_loss"] < payload["candidate_levels"]["reference_close"]


def test_strategy_signal_endpoint_requires_bridge_authentication(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv(
        "FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "strategy-auth.sqlite3")
    )
    response = client.get("/api/v1/strategy/signal/EURUSDm/H1")
    assert response.status_code == 401
