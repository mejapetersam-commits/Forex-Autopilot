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



def test_recovery_status_exposes_backup_freshness_and_quarantine_safely(monkeypatch, tmp_path):
    import sqlite3
    from datetime import datetime, timezone
    from app.execution.command_queue import ExecutionCommandQueue
    from app.operations.backup_scheduler import write_worker_heartbeat

    database = str(tmp_path / "recovery.sqlite3")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / (
        "telemetry-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".sqlite3"
    )
    with sqlite3.connect(backup) as db:
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('verified')")
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", database)
    monkeypatch.setenv("FOREX_AUTOPILOT_BACKUP_DIR", str(backup_dir))

    queue = ExecutionCommandQueue(database)
    queue.enqueue_approved_intent(
        command_id="cmd-dashboard-expired", intent_id="intent-dashboard-expired",
        payload={"symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
                 "stop_loss": 1.09, "take_profit": 1.12},
        environment="demo", trading_enabled=True,
    )
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE execution_commands SET status='expired', attempts=1 "
            "WHERE command_id='cmd-dashboard-expired'"
        )
    write_worker_heartbeat(
        backup_dir, telemetry_db=database,
        backup_name=backup.name,
    )

    response = client.get("/api/v1/dashboard/recovery-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["backups"]["fresh_verified_backup"] is True
    assert payload["backups"]["verified_count"] == 1
    assert payload["backup_worker"]["fresh"] is True
    assert payload["backup_worker"]["status"] == "healthy"
    assert payload["execution_commands"]["counts"]["expired"] == 1
    assert payload["execution_commands"]["quarantined_total"] == 1
    assert "payload" not in payload["execution_commands"]["quarantined"][0]
    assert payload["trading_enabled"] is False
    assert payload["execution_mode"] == "disabled"
    assert payload["read_only"] is True


def test_recovery_status_fails_closed_when_backup_directory_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(tmp_path / "empty.sqlite3"))
    monkeypatch.setenv("FOREX_AUTOPILOT_BACKUP_DIR", str(tmp_path / "missing"))
    response = client.get("/api/v1/dashboard/recovery-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["backups"]["fresh_verified_backup"] is False
    assert payload["backups"]["status"] == "missing_directory"
    assert payload["trading_enabled"] is False
