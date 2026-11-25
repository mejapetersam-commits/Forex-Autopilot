from datetime import datetime, timezone

from app.execution.coordinator import ExecutionCoordinator
from app.execution.ledger import ExecutionLedger
from app.execution.preflight import ExecutionSnapshot, TradeIntent


def intent():
    return TradeIntent(
        symbol="EURUSDm", side="buy", volume_lots=0.01,
        stop_loss=1.09, take_profit=1.12,
        requested_at=datetime.now(timezone.utc),
    )


def snapshot():
    return ExecutionSnapshot(
        environment="demo", trading_enabled=True, kill_switch_active=False,
        trading_paused=False, broker_connected=True,
        account_equity=1000, free_margin=900,
        quote_bid=1.1000, quote_ask=1.1001, quote_age_seconds=0.5,
        account_age_seconds=1, open_positions=0, daily_loss_pct=0,
        symbol_allowlist=("EURUSDm",),
    )


def test_coordinator_records_preflight_approval_without_broker_submission(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "coordinator.sqlite3"))
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    coordinator = ExecutionCoordinator(ledger)
    result = coordinator.preflight_and_record("coord-001", intent(), snapshot())
    assert result["status"] == "approved"
    assert result["preflight"]["approved"] is True
    assert result["broker_submission_attempted"] is False


def test_coordinator_records_fail_closed_rejection(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "coordinator-reject.sqlite3"))
    coordinator = ExecutionCoordinator(ledger)
    result = coordinator.preflight_and_record("coord-002", intent(), snapshot())
    assert result["status"] == "preflight_rejected"
    assert result["preflight"]["approved"] is False
    assert result["broker_submission_attempted"] is False


def test_coordinator_prevents_duplicate_intent_reprocessing(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "coordinator-idempotent.sqlite3"))
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    coordinator = ExecutionCoordinator(ledger)
    order_intent = intent()
    first = coordinator.preflight_and_record("coord-003", order_intent, snapshot())
    replay = coordinator.preflight_and_record("coord-003", order_intent, snapshot())
    assert first["status"] == "approved"
    assert replay["idempotent_replay"] is True
    assert replay["broker_submission_attempted"] is False


def test_coordinator_persists_broker_state_events(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "coordinator-events.sqlite3"))
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    coordinator = ExecutionCoordinator(ledger)
    coordinator.preflight_and_record("coord-004", intent(), snapshot())
    submitted = coordinator.record_broker_event(
        "coord-004", "submitted", event_type="adapter_submit",
        broker_order_id="demo-1001",
    )
    assert submitted["status"] == "submitted"
    assert submitted["broker_order_id"] == "demo-1001"
