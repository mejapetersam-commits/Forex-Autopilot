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
