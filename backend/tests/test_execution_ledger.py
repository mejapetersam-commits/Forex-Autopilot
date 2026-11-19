import pytest

from app.execution.ledger import ExecutionLedger


def test_ledger_is_idempotent_and_rejects_payload_reuse(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    first = ledger.create_intent("intent-001", {"symbol": "EURUSDm", "volume": 0.01})
    duplicate = ledger.create_intent("intent-001", {"symbol": "EURUSDm", "volume": 0.01})
    assert first["id"] == duplicate["id"]
    with pytest.raises(ValueError, match="different payload"):
        ledger.create_intent("intent-001", {"symbol": "GBPUSDm", "volume": 0.01})


def test_ledger_enforces_state_transitions_and_audits_them(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    ledger.create_intent("intent-002", {"symbol": "EURUSDm"})
    approved = ledger.transition("intent-002", "approved", event_type="preflight_passed")
    submitted = ledger.transition(
        "intent-002", "submitted", event_type="broker_submit",
        broker_order_id="demo-ticket-123",
    )
    assert approved["status"] == "approved"
    assert submitted["status"] == "submitted"
    assert submitted["broker_order_id"] == "demo-ticket-123"
    events = ledger.audit_events("intent-002")
    assert [event["new_status"] for event in events] == ["created", "approved", "submitted"]


def test_ledger_rejects_invalid_transition_and_missing_intent(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    ledger.create_intent("intent-003", {"symbol": "EURUSDm"})
    with pytest.raises(ValueError, match="Invalid order state"):
        ledger.transition("intent-003", "filled", event_type="bad")
    with pytest.raises(KeyError):
        ledger.transition("unknown", "approved", event_type="bad")


def test_runtime_controls_default_to_paused_and_kill_switch_active(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    assert ledger.controls() == {"trading_paused": True, "kill_switch_active": True}
    ledger.set_control("trading_paused", False)
    ledger.set_control("kill_switch_active", False)
    assert ledger.controls() == {"trading_paused": False, "kill_switch_active": False}


def test_runtime_control_rejects_unknown_keys(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    with pytest.raises(ValueError, match="Unsupported"):
        ledger.set_control("live_trading_enabled", True)



def test_terminal_broker_state_can_be_marked_reconciled(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "reconcile.sqlite3"))
    ledger.create_intent("intent-reconcile", {"symbol": "EURUSDm"})
    ledger.transition("intent-reconcile", "approved", event_type="preflight_passed")
    ledger.transition("intent-reconcile", "submitted", event_type="submit")
    ledger.transition("intent-reconcile", "acknowledged", event_type="broker_ack")
    ledger.transition("intent-reconcile", "filled", event_type="broker_fill")
    final = ledger.transition("intent-reconcile", "reconciled", event_type="broker_history_confirmed")
    assert final["status"] == "reconciled"



def test_get_intent_returns_decoded_payload_and_status(tmp_path):
    ledger = ExecutionLedger(str(tmp_path / "ledger.sqlite3"))
    payload = {"symbol": "EURUSDm", "volume_lots": 0.01}
    ledger.create_intent("intent-read", payload)
    result = ledger.get_intent("intent-read")
    assert result["status"] == "created"
    assert result["payload"] == payload
    assert ledger.get_intent("missing") is None
