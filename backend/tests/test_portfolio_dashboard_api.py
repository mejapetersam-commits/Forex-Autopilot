from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.broker.bridge import (
    MT5AccountSnapshot, MT5ExecutionState, MT5OpenPosition,
    MT5Quote, MT5SymbolSpecification,
)
from app.market_data.telemetry_store import TelemetryStore

client = TestClient(app)

def test_dashboard_portfolio_exposure_uses_fresh_broker_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "portfolio-api.sqlite3"))
    now = datetime.now(timezone.utc)
    store = TelemetryStore()
    store.save_account(MT5AccountSnapshot(
        server="EXNESS-DEMO", account_currency="USD", balance=10000,
        equity=10000, margin=0, free_margin=10000, leverage=200, observed_at=now,
    ))
    store.save_execution_state(MT5ExecutionState(
        terminal_id="test-terminal", environment="demo", server="EXNESS-DEMO",
        observed_at=now, daily_loss_pct=0,
        positions=[MT5OpenPosition(
            ticket="12345", symbol="EURUSDm", side="buy", volume_lots=0.01,
            open_price=1.1, stop_loss=1.09, take_profit=1.12, magic=0,
        )],
    ))
    store.save_quote(MT5Quote(symbol="EURUSDm", bid=1.10, ask=1.1002, timestamp=now))
    store.save_symbol_specification(MT5SymbolSpecification(
        symbol="EURUSDm", digits=5, point=0.00001, tick_size=0.00001,
        tick_value_profit=1, tick_value_loss=1, contract_size=100000,
        volume_min=0.01, volume_max=200, volume_step=0.01,
        stops_level_points=0, freeze_level_points=0, trade_allowed=True,
        base_currency="EUR", profit_currency="USD", margin_currency="EUR",
        account_currency="USD", observed_at=now,
    ))

    response = client.get("/api/v1/dashboard/portfolio")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["open_position_count"] == 1
    assert payload["total_open_stop_risk"] == 10
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert {row["currency"] for row in payload["currencies"]} == {"EUR", "USD"}

def test_dashboard_portfolio_returns_unavailable_without_broker_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "portfolio-empty.sqlite3"))
    response = client.get("/api/v1/dashboard/portfolio")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["total_open_stop_risk"] is None
    assert payload["trading_enabled"] is False
