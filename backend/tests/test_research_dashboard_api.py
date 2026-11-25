from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app import main as main_module

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



def test_dashboard_data_readiness_reports_history_shortfall_and_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "readiness.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm")
    response = client.get("/api/v1/dashboard/data-readiness?minimum_candles=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "attention_required"
    assert payload["series_checked"] == 4
    assert payload["ready_series"] == 0
    assert all(item["status"] == "insufficient_history" for item in payload["items"])
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"


def test_dashboard_research_exposes_history_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "research-readiness.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm")
    response = client.get("/api/v1/dashboard/research")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["readiness_status"] == "insufficient_history"
    assert item["coverage_pct"] == 0
    assert item["valid_candles"] == 0


def test_dashboard_data_readiness_exposes_integrity_and_gap_detail(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "readiness-detail.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm")
    start = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    candles = []
    for index, minutes in enumerate((0, 5, 25)):
        price = 1.10 + index * 0.0001
        candles.append({
            "opened_at": (start + timedelta(minutes=minutes)).isoformat(),
            "open": price, "high": price + 0.0002,
            "low": price - 0.0002, "close": price + 0.0001,
            "tick_volume": 100,
        })
    upload = client.post(
        "/api/v1/mt5/candles/bulk",
        headers={"X-Bridge-Token": TOKEN},
        json={"batches": [{"symbol": "EURUSDm", "timeframe": "M5", "candles": candles}]},
    )
    assert upload.status_code == 200

    response = client.get("/api/v1/dashboard/data-readiness?minimum_candles=3&limit=50")
    assert response.status_code == 200
    payload = response.json()
    m5 = next(item for item in payload["items"] if item["timeframe"] == "M5")
    assert m5["candles_available"] == 3
    assert m5["quality"]["valid_ohlc_candles"] == 3
    assert m5["quality"]["gap_count"] == 1
    assert m5["ready_for_research"] is True
    assert payload["trading_enabled"] is False
    assert payload["read_only"] is True

    ledger_response = client.get("/api/v1/dashboard/candle-ingestion")
    assert ledger_response.status_code == 200
    ledger = ledger_response.json()
    assert ledger["batch_count"] == 1
    assert ledger["series_count"] == 1
    assert ledger["recent_batches"][0]["received_count"] == 3
    assert ledger["recent_batches"][0]["symbol"] == "EURUSDM"
    assert ledger["trading_enabled"] is False
    assert ledger["read_only"] is True


def test_dashboard_cost_sensitivity_compares_cost_multipliers_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_BRIDGE_TOKEN", TOKEN)
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "cost-sensitivity.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_DASHBOARD_SYMBOLS", "EURUSDm")
    monkeypatch.setattr(main_module, "resolve_backtest_pip_values", lambda *args: (0.0001, 10.0, "test_fixture"))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 1.10
    for index in range(180):
        next_price = price + 0.0002 + index * 0.000002
        candles.append({
            "opened_at": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": max(price, next_price) + 0.00015,
            "low": min(price, next_price) - 0.00015,
            "close": next_price,
            "tick_volume": 100,
        })
        price = next_price
    upload = client.post(
        "/api/v1/mt5/candles",
        headers={"X-Bridge-Token": TOKEN},
        json={"symbol": "EURUSDm", "timeframe": "H1", "candles": candles},
    )
    assert upload.status_code == 200

    response = client.get("/api/v1/dashboard/cost-sensitivity?symbol=EURUSDm&timeframe=H1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["candles_available"] == 180
    assert [item["cost_multiplier"] for item in payload["scenarios"]] == [1.0, 1.5, 2.0, 3.0]
    assert payload["scenarios"][0]["assumptions"]["spread_pips"] == 1.0
    assert payload["scenarios"][-1]["assumptions"]["spread_pips"] == 3.0
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert payload["read_only"] is True
