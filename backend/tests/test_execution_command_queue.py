import pytest

from app.execution.command_queue import ExecutionCommandQueue


def command_payload():
    return {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.08, "take_profit": 1.10,
    }


def make_queue(tmp_path):
    return ExecutionCommandQueue(str(tmp_path / "execution.sqlite3"))


def test_commands_are_demo_only_and_disabled_by_default(tmp_path):
    queue = make_queue(tmp_path)
    with pytest.raises(ValueError, match="demo"):
        queue.enqueue_approved_intent(
            command_id="c1", intent_id="i1", payload=command_payload(),
            environment="live", trading_enabled=True,
        )
    with pytest.raises(ValueError, match="disabled"):
        queue.enqueue_approved_intent(
            command_id="c1", intent_id="i1", payload=command_payload(),
            environment="demo", trading_enabled=False,
        )


def test_command_delivery_is_leased_and_idempotent(tmp_path):
    queue = make_queue(tmp_path)
    queued = queue.enqueue_approved_intent(
        command_id="c1", intent_id="i1", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    assert queued["status"] == "queued"
    leased = queue.lease_next(terminal_id="mt5-demo-1")
    assert leased["command_id"] == "c1"
    assert leased["payload"] == command_payload()
    assert queue.lease_next(terminal_id="mt5-demo-1") is None
    result = {"broker_order_id": "12345", "filled_volume": 0.01}
    recorded = queue.record_result(
        "c1", terminal_id="mt5-demo-1", outcome="acknowledged", result=result
    )
    assert recorded["status"] == "acknowledged"
    assert queue.record_result(
        "c1", terminal_id="mt5-demo-1", outcome="acknowledged", result=result
    )["status"] == "acknowledged"


def test_terminal_cannot_acknowledge_another_terminals_lease(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c1", intent_id="i1", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-a")
    with pytest.raises(ValueError, match="not leased"):
        queue.record_result(
            "c1", terminal_id="terminal-b", outcome="rejected",
            result={"reason": "unexpected"},
        )


def test_idempotency_rejects_changed_payload(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c1", intent_id="i1", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    changed = {**command_payload(), "volume_lots": 0.02}
    with pytest.raises(ValueError, match="different"):
        queue.enqueue_approved_intent(
            command_id="c2", intent_id="i1", payload=changed,
            environment="demo", trading_enabled=True,
        )



def test_expired_lease_is_quarantined_not_redelivered(tmp_path):
    import sqlite3
    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c-expire", intent_id="i-expire", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-a")
    with sqlite3.connect(queue.database_path) as db:
        db.execute(
            "UPDATE execution_commands SET lease_until='2000-01-01T00:00:00+00:00' WHERE command_id='c-expire'"
        )
    assert queue.lease_next(terminal_id="terminal-b") is None
    with pytest.raises(ValueError, match="not leased"):
        queue.record_result(
            "c-expire", terminal_id="terminal-a", outcome="acknowledged",
            result={"broker_order_id": "maybe-sent"},
        )
