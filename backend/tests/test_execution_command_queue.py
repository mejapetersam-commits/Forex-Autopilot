import sqlite3
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



def test_expired_command_quarantine_survives_queue_restart(tmp_path):
    import sqlite3

    database = tmp_path / "durable-queue.sqlite3"
    first_process = ExecutionCommandQueue(str(database))
    first_process.enqueue_approved_intent(
        command_id="c-restart", intent_id="i-restart",
        payload=command_payload(), environment="demo", trading_enabled=True,
    )
    first_process.lease_next(terminal_id="terminal-before-restart")
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE execution_commands SET lease_until='2000-01-01T00:00:00+00:00' "
            "WHERE command_id='c-restart'"
        )

    restarted_process = ExecutionCommandQueue(str(database))
    expired = restarted_process.expire_leases()
    assert len(expired) == 1
    assert expired[0]["command_id"] == "c-restart"
    assert restarted_process.expired_commands()[0]["attempts"] == 1
    assert restarted_process.lease_next(terminal_id="terminal-after-restart") is None

    with sqlite3.connect(database) as db:
        status, attempts = db.execute(
            "SELECT status, attempts FROM execution_commands WHERE command_id='c-restart'"
        ).fetchone()
    assert status == "expired"
    assert attempts == 1



def test_operational_summary_counts_and_redacts_command_payload(tmp_path):
    queue = ExecutionCommandQueue(str(tmp_path / "summary.sqlite3"))
    queue.enqueue_approved_intent(
        command_id="summary-command", intent_id="summary-intent",
        payload={"symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
                 "stop_loss": 1.09, "take_profit": 1.12, "private_note": "must-not-leak"},
        environment="demo", trading_enabled=True,
    )
    with sqlite3.connect(queue.database_path) as db:
        db.execute(
            "UPDATE execution_commands SET status='expired', attempts=2, terminal_id='terminal-1' "
            "WHERE command_id='summary-command'"
        )

    result = queue.operational_summary()
    assert result["counts"]["expired"] == 1
    assert result["quarantined_total"] == 1
    item = result["quarantined"][0]
    assert item["command_id"] == "summary-command"
    assert "payload_json" not in item
    assert "private_note" not in str(item)

def test_conflicting_duplicate_terminal_result_is_rejected(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c-conflict", intent_id="i-conflict", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-a")
    accepted = {"intent_id": "i-conflict", "broker_order_id": "123"}
    queue.record_result(
        "c-conflict", terminal_id="terminal-a", outcome="acknowledged",
        result=accepted, expected_intent_id="i-conflict",
    )
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        queue.record_result(
            "c-conflict", terminal_id="terminal-a", outcome="rejected",
            result={"intent_id": "i-conflict", "reason": "late contradictory callback"},
            expected_intent_id="i-conflict",
        )


def test_duplicate_terminal_result_must_match_immutable_intent(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c-intent-bind", intent_id="i-original", payload=command_payload(),
        environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-a")
    accepted = {"intent_id": "i-original", "broker_order_id": "456"}
    queue.record_result(
        "c-intent-bind", terminal_id="terminal-a", outcome="acknowledged",
        result=accepted, expected_intent_id="i-original",
    )
    with pytest.raises(ValueError, match="does not match"):
        queue.record_result(
            "c-intent-bind", terminal_id="terminal-a", outcome="acknowledged",
            result={"intent_id": "i-forged", "broker_order_id": "456"},
            expected_intent_id="i-forged",
        )

def test_late_broker_callback_after_expiry_is_rejected_and_stays_quarantined(tmp_path):
    import sqlite3

    queue = make_queue(tmp_path)
    queue.enqueue_approved_intent(
        command_id="c-late-callback", intent_id="i-late-callback",
        payload=command_payload(), environment="demo", trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-a")
    with sqlite3.connect(queue.database_path) as db:
        db.execute(
            "UPDATE execution_commands SET lease_until='2000-01-01T00:00:00+00:00' "
            "WHERE command_id='c-late-callback'"
        )

    expired = queue.expire_leases()
    assert [item["command_id"] for item in expired] == ["c-late-callback"]
    with pytest.raises(ValueError, match="not leased"):
        queue.record_result(
            "c-late-callback", terminal_id="terminal-a", outcome="acknowledged",
            result={"intent_id": "i-late-callback", "broker_order_id": "late-123"},
            expected_intent_id="i-late-callback",
        )

    summary = queue.operational_summary()
    assert summary["counts"]["expired"] == 1
    assert summary["counts"]["queued"] == 0
    assert queue.lease_next(terminal_id="terminal-b") is None

