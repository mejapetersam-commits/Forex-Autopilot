from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from app import main
from app.execution.command_queue import ExecutionCommandQueue
from app.execution.ledger import ExecutionLedger
from app.broker.bridge import (
    MT5AccountSnapshot, MT5ExecutionState, MT5Heartbeat, MT5Quote,
    MT5SymbolSpecification,
)
from app.market_data.telemetry_store import TelemetryStore


def make_intent(ledger, key="intent-demo"):
    payload = {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.0991, "take_profit": 1.102,
        "requested_at": "2026-11-19T12:00:00+00:00",
    }
    ledger.create_intent(key, payload)
    return key


def configure(monkeypatch, tmp_path, approved=True):
    ledger = ExecutionLedger(str(tmp_path / "execution.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "execution.sqlite3"))
    store = TelemetryStore(str(tmp_path / "execution.sqlite3"))
    now = datetime.now(timezone.utc)
    server = "Exness-MT5Trial"
    store.save_heartbeat(MT5Heartbeat(server=server, terminal_connected=True, observed_at=now))
    store.save_account(MT5AccountSnapshot(
        server=server, account_currency="USD", balance=1000, equity=1000,
        margin=0, free_margin=1000, leverage=100, observed_at=now,
    ))
    store.save_quote(MT5Quote(symbol="EURUSDm", bid=1.1000, ask=1.1001, timestamp=now))
    store.save_symbol_specification(MT5SymbolSpecification(
        symbol="EURUSDm", digits=5, point=0.00001, tick_size=0.00001,
        tick_value_profit=1, tick_value_loss=1, contract_size=100000,
        volume_min=0.01, volume_max=100, volume_step=0.01,
        stops_level_points=10, freeze_level_points=0, trade_allowed=True,
        base_currency="EUR", profit_currency="USD", margin_currency="EUR",
        account_currency="USD", observed_at=now,
    ))
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server=server,
        observed_at=now, daily_loss_pct=0, positions=[],
    ))
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    key = make_intent(ledger)
    if approved:
        ledger.transition(key, "approved", event_type="preflight_approved")
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    monkeypatch.setenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo")
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "EURUSDm")
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_DAILY_LOSS_PCT", "1.0")
    monkeypatch.setenv("FOREX_AUTOPILOT_MAX_RISK_PER_TRADE_PCT", "0.25")
    return ledger, queue, key


def test_dispatch_disabled_by_default(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false")
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 403
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_only_approved_intents_can_be_dispatched(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path, approved=False)
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 409
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_demo_dispatch_requires_allowlisted_symbol(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "GBPUSDm")
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 403
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_approved_intent_is_queued_only_when_demo_gates_open(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    result = main.queue_approved_demo_intent(key)
    assert result["status"] == "queued"
    assert result["environment"] == "demo"
    assert result["trading_enabled"] is False
    leased = queue.lease_next(terminal_id="demo-terminal")
    assert leased["intent_id"] == key
    assert leased["payload"]["symbol"] == "EURUSDm"


def test_dispatch_refuses_when_kill_switch_active(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    ledger.set_control("kill_switch_active", True)
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 423



def test_terminal_acknowledgement_updates_order_ledger(monkeypatch, tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "shared.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "shared.sqlite3"))
    key = make_intent(ledger, "intent-ack")
    ledger.transition(key, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id="cmd-ack", intent_id=key,
        payload=ledger.get_intent(key)["payload"],
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-ack")
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    payload = main.MT5ExecutionResult(
        terminal_id="terminal-ack", outcome="acknowledged",
        result={"intent_id": key, "broker_order_id": "123456", "filled_volume": 0.01},
    )
    response = main.record_execution_command_result("cmd-ack", payload)
    assert response["intent_status"] == "acknowledged"
    assert ledger.get_intent(key)["broker_order_id"] == "123456"


def test_uncertain_terminal_result_is_recorded_as_unknown(monkeypatch, tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "shared.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "shared.sqlite3"))
    key = make_intent(ledger, "intent-unknown")
    ledger.transition(key, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id="cmd-unknown", intent_id=key,
        payload=ledger.get_intent(key)["payload"],
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-unknown")
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    payload = main.MT5ExecutionResult(
        terminal_id="terminal-unknown", outcome="unknown",
        result={"intent_id": key, "reason": "terminal_result_uncertain"},
    )
    response = main.record_execution_command_result("cmd-unknown", payload)
    assert response["intent_status"] == "unknown"


def test_command_polling_is_disabled_by_default(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "false")
    response = main.lease_next_execution_command("demo-terminal")
    assert response["command"] is None
    assert response["reason"] == "demo_execution_disabled"


def test_dispatch_refuses_non_demo_environment(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("FOREX_AUTOPILOT_ENVIRONMENT", "live")
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 403
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_admin_preflight_creates_approved_intent_from_fresh_demo_telemetry(monkeypatch, tmp_path):
    ledger, queue, _ = configure(monkeypatch, tmp_path)
    request = main.ExecutionIntentRequest(
        idempotency_key="intent-preflight-api", symbol="EURUSDm", side="buy",
        volume_lots=0.01, stop_loss=1.0991, take_profit=1.102,
        requested_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    result = main.preflight_execution_intent(request)
    assert result["status"] == "approved"
    assert result["preflight"]["approved"] is True
    assert result["broker_submission_attempted"] is False
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_admin_preflight_fails_closed_when_position_state_is_missing(monkeypatch, tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "empty.sqlite3"))
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    store = TelemetryStore(str(tmp_path / "empty.sqlite3"))
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "telemetry_store", lambda: store)
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("FOREX_AUTOPILOT_EXECUTION_SYMBOLS", "EURUSDm")
    request = main.ExecutionIntentRequest(
        idempotency_key="intent-no-state", symbol="EURUSDm", side="buy",
        volume_lots=0.01, stop_loss=1.0991, take_profit=1.102,
        requested_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    result = main.preflight_execution_intent(request)
    assert result["status"] == "preflight_rejected"
    assert result["preflight"]["approved"] is False
    assert any("connected" in reason.lower() for reason in result["preflight"]["reasons"])


def test_dispatch_rechecks_daily_loss_immediately_before_queueing(monkeypatch, tmp_path):
    ledger, queue, key = configure(monkeypatch, tmp_path)
    store = main.telemetry_store()
    now = datetime.now(timezone.utc)
    store.save_execution_state(MT5ExecutionState(
        terminal_id="demo-terminal", environment="demo", server="Exness-MT5Trial",
        observed_at=now, daily_loss_pct=1.2, positions=[],
    ))
    with pytest.raises(HTTPException) as exc:
        main.queue_approved_demo_intent(key)
    assert exc.value.status_code == 423
    assert ledger.get_intent(key)["status"] == "rejected"
    assert queue.lease_next(terminal_id="demo-terminal") is None


def test_mismatched_terminal_intent_does_not_consume_command(monkeypatch, tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "shared.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "shared.sqlite3"))
    key = make_intent(ledger, "intent-bound")
    ledger.transition(key, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id="cmd-bound", intent_id=key,
        payload=ledger.get_intent(key)["payload"],
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-bound")
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    payload = main.MT5ExecutionResult(
        terminal_id="terminal-bound", outcome="acknowledged",
        result={"intent_id": "some-other-intent", "broker_order_id": "999"},
    )
    with pytest.raises(HTTPException) as exc:
        main.record_execution_command_result("cmd-bound", payload)
    assert exc.value.status_code == 409
    with queue._connect() as db:
        row = db.execute(
            "SELECT status, result_json FROM execution_commands WHERE command_id=?",
            ("cmd-bound",),
        ).fetchone()
    assert row["status"] == "leased"
    assert row["result_json"] is None
    assert ledger.get_intent(key)["status"] == "approved"


def test_terminal_result_requires_intent_id_before_queue_mutation(monkeypatch, tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "shared.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "shared.sqlite3"))
    key = make_intent(ledger, "intent-required")
    ledger.transition(key, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id="cmd-required", intent_id=key,
        payload=ledger.get_intent(key)["payload"],
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-required")
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    payload = main.MT5ExecutionResult(
        terminal_id="terminal-required", outcome="acknowledged",
        result={"broker_order_id": "123"},
    )
    with pytest.raises(HTTPException) as exc:
        main.record_execution_command_result("cmd-required", payload)
    assert exc.value.status_code == 422
    with queue._connect() as db:
        row = db.execute(
            "SELECT status, result_json FROM execution_commands WHERE command_id=?",
            ("cmd-required",),
        ).fetchone()
    assert row["status"] == "leased"
    assert row["result_json"] is None
    assert ledger.get_intent(key)["status"] == "approved"


def test_expired_command_lease_marks_approved_intent_unknown(monkeypatch, tmp_path):
    from datetime import timedelta
    ledger = ExecutionLedger(str(tmp_path / "shared.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "shared.sqlite3"))
    key = make_intent(ledger, "intent-expired")
    ledger.transition(key, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id="cmd-expired", intent_id=key,
        payload={**ledger.get_intent(key)["payload"], "broker_tag": "abcdef123456"},
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-expired", lease_seconds=5)
    with queue._connect() as db:
        db.execute(
            "UPDATE execution_commands SET lease_until=? WHERE command_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), "cmd-expired"),
        )
    monkeypatch.setattr(main, "execution_ledger", lambda: ledger)
    monkeypatch.setattr(main, "execution_command_queue", lambda: queue)
    monkeypatch.setenv("FOREX_AUTOPILOT_ENVIRONMENT", "demo")
    monkeypatch.setenv("FOREX_AUTOPILOT_DEMO_EXECUTION_ENABLED", "true")
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    response = main.lease_next_execution_command("terminal-expired")
    assert response["command"] is None
    assert ledger.get_intent(key)["status"] == "unknown"
    assert queue.expired_commands()[0]["intent_id"] == key
