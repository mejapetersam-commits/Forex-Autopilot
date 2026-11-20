import hashlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.broker.bridge import MT5ExecutionState, MT5OpenPosition
from app.execution.ledger import ExecutionLedger
from app.main import app
from app.market_data.telemetry_store import TelemetryStore

client = TestClient(app)


def test_admin_position_reconciliation_records_orphan_position_event(monkeypatch, tmp_path):
    db = str(tmp_path / "position-reconciliation.sqlite3")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", db)
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", "a" * 40)
    now = datetime.now(timezone.utc)
    tag = hashlib.sha256(b"known-intent").hexdigest()[:12]
    ledger = ExecutionLedger(db)
    ledger.create_intent("known-intent", {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.09, "take_profit": 1.12,
    })
    store = TelemetryStore(db)
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server="Exness-Demo",
        observed_at=now, daily_loss_pct=0,
        positions=[
            MT5OpenPosition(
                ticket="100", position_id="200", symbol="EURUSDm", side="buy",
                volume_lots=0.01, open_price=1.1, stop_loss=1.09,
                take_profit=1.12, magic=61119001, comment="FA:" + tag,
            ),
            MT5OpenPosition(
                ticket="101", position_id="201", symbol="GBPUSDm", side="sell",
                volume_lots=0.01, open_price=1.27, stop_loss=1.28,
                take_profit=1.25, magic=61119001, comment="manual",
            ),
        ],
    ))

    response = client.get(
        "/api/v1/monitoring/positions/reconciliation",
        headers={"X-Admin-Token": "a" * 40},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "review_required"
    assert payload["managed_positions_checked"] == 2
    assert [p["ticket"] for p in payload["orphaned_positions"]] == ["101"]
    assert payload["operational_events_recorded"] == 1
