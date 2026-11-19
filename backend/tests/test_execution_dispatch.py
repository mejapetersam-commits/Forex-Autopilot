import pytest
from fastapi import HTTPException

from app import main
from app.execution.command_queue import ExecutionCommandQueue
from app.execution.ledger import ExecutionLedger


def make_intent(ledger, key="intent-demo"):
    payload = {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.08, "take_profit": 1.10,
        "requested_at": "2026-11-19T12:00:00+00:00",
    }
    ledger.create_intent(key, payload)
    return key


def configure(monkeypatch, tmp_path, approved=True):
    ledger = ExecutionLedger(str(tmp_path / "execution.sqlite3"))
    queue = ExecutionCommandQueue(str(tmp_path / "execution.sqlite3"))
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
