from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.broker.bridge import MT5ExecutionState, MT5OpenPosition
from app.execution.ledger import ExecutionLedger
from app.main import app
from app.market_data.telemetry_store import TelemetryStore

client = TestClient(app)


def test_dashboard_operations_exposes_read_only_reconciliation_and_risk(monkeypatch, tmp_path):
    db = str(tmp_path / "dashboard-operations.sqlite3")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", db)
    now = datetime.now(timezone.utc)
    ledger = ExecutionLedger(db)
    ledger.create_intent("known-dashboard-intent", {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.09, "take_profit": 1.12,
    })
    store = TelemetryStore(db)
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server="Exness-Demo",
        observed_at=now, daily_loss_pct=0,
        positions=[
            MT5OpenPosition(
                ticket="501", position_id="601", symbol="EURUSDm", side="buy",
                volume_lots=0.01, open_price=1.1, stop_loss=1.09,
                take_profit=1.12, magic=61119001, comment="manual",
            )
        ],
    ))
    response = client.get("/api/v1/dashboard/operations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["reconciliation"]["status"] == "review_required"
    assert payload["reconciliation"]["orphaned_positions"][0]["ticket"] == "501"
    assert payload["lifecycle"]["status"] == "baseline_only"
    assert payload["portfolio_risk_gate"]["approved"] is False
    assert payload["trading_enabled"] is False
    assert payload["read_only"] is True


def test_dashboard_operations_waits_for_terminal_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "empty.sqlite3"))
    response = client.get("/api/v1/dashboard/operations")
    assert response.status_code == 200
    assert response.json()["reconciliation"]["status"] == "waiting_for_terminal_snapshot"
