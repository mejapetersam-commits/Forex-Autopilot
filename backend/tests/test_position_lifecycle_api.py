from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.broker.bridge import (
    MT5ExecutionDeal, MT5ExecutionHistory, MT5ExecutionState, MT5OpenPosition,
)
from app.main import app
from app.market_data.telemetry_store import TelemetryStore

client = TestClient(app)


def test_lifecycle_endpoint_confirms_close_only_with_full_deal_evidence(monkeypatch, tmp_path):
    db = str(tmp_path / "position-lifecycle.sqlite3")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", db)
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", "b" * 40)
    now = datetime.now(timezone.utc)
    store = TelemetryStore(db)
    position = MT5OpenPosition(
        ticket="700", position_id="900", symbol="EURUSDm", side="buy",
        volume_lots=0.02, open_price=1.1, stop_loss=1.09,
        take_profit=1.12, magic=61119001, comment="FA:tag",
    )
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server="Exness-Demo",
        observed_at=now - timedelta(seconds=10), daily_loss_pct=0, positions=[position],
    ))
    store.save_execution_history(MT5ExecutionHistory(
        terminal_id="demo-terminal", environment="demo", server="Exness-Demo",
        history_from=now - timedelta(minutes=2), history_to=now,
        observed_at=now,
        deals=[
            MT5ExecutionDeal(
                deal_ticket="1", order_ticket="11", position_id="900",
                symbol="EURUSDm", side="buy", entry="in", volume_lots=0.02,
                price=1.1, magic=61119001, occurred_at=now - timedelta(minutes=1),
            ),
            MT5ExecutionDeal(
                deal_ticket="2", order_ticket="12", position_id="900",
                symbol="EURUSDm", side="sell", entry="out", volume_lots=0.02,
                price=1.11, magic=61119001, occurred_at=now - timedelta(seconds=5),
            ),
        ],
    ))
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server="Exness-Demo",
        observed_at=now, daily_loss_pct=0, positions=[],
    ))

    response = client.get(
        "/api/v1/monitoring/positions/lifecycle",
        headers={"X-Admin-Token": "b" * 40},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["events"][0]["event_type"] == "position_closed_confirmed"
    assert payload["events"][0]["closed_volume_lots"] == 0.02
    assert payload["trading_enabled"] is False


def test_lifecycle_endpoint_requires_admin_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_ADMIN_TOKEN", "c" * 40)
    response = client.get("/api/v1/monitoring/positions/lifecycle")
    assert response.status_code == 401
