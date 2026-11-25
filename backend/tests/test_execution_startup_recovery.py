import sqlite3

from fastapi.testclient import TestClient

from app import main
from app.execution.command_queue import ExecutionCommandQueue
from app.execution.ledger import ExecutionLedger


def test_app_startup_quarantines_expired_lease_and_preserves_safety_controls(
    monkeypatch, tmp_path
):
    database = tmp_path / "startup-recovery.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))

    ledger = ExecutionLedger(str(database))
    queue = ExecutionCommandQueue(str(database))

    intent_id = "startup-recovery-intent"
    command_id = "startup-recovery-command"
    payload = {
        "symbol": "EURUSDm",
        "side": "buy",
        "volume_lots": 0.01,
        "stop_loss": 1.08,
        "take_profit": 1.10,
    }

    ledger.create_intent(intent_id, payload)
    ledger.transition(intent_id, "approved", event_type="preflight_approved")
    ledger.set_control("trading_paused", True)
    ledger.set_control("kill_switch_active", True)

    queue.enqueue_approved_intent(
        command_id=command_id,
        intent_id=intent_id,
        payload=payload,
        environment="demo",
        trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-before-restart")

    # Simulate a lease that expired while the application was stopped.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE execution_commands SET lease_until=? WHERE command_id=?",
            ("2000-01-01T00:00:00+00:00", command_id),
        )

    # Entering the application lifespan must perform recovery automatically.
    with TestClient(main.app):
        pass

    recovered_ledger = ExecutionLedger(str(database))
    recovered_queue = ExecutionCommandQueue(str(database))

    assert recovered_queue.expired_commands()[0]["command_id"] == command_id
    assert recovered_ledger.get_intent(intent_id)["status"] == "unknown"
    assert recovered_ledger.controls() == {
        "trading_paused": True,
        "kill_switch_active": True,
    }

    # A subsequent startup must not duplicate the recovery transition.
    with TestClient(main.app):
        pass

    events = recovered_ledger.audit_events(intent_id)
    recovery_events = [
        event for event in events
        if event["event_type"] == "command_lease_expired"
    ]
    assert len(recovery_events) == 1
    assert recovered_ledger.get_intent(intent_id)["status"] == "unknown"


def test_app_startup_recovers_when_queue_expired_before_ledger_transition(
    monkeypatch, tmp_path
):
    database = tmp_path / "interrupted-recovery.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))

    ledger = ExecutionLedger(str(database))
    queue = ExecutionCommandQueue(str(database))

    intent_id = "interrupted-recovery-intent"
    command_id = "interrupted-recovery-command"
    payload = {
        "symbol": "EURUSDm",
        "side": "buy",
        "volume_lots": 0.01,
        "stop_loss": 1.08,
        "take_profit": 1.10,
    }

    ledger.create_intent(intent_id, payload)
    ledger.transition(intent_id, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id=command_id,
        intent_id=intent_id,
        payload=payload,
        environment="demo",
        trading_enabled=True,
    )
    queue.lease_next(terminal_id="terminal-before-crash")

    # Simulate a crash after queue expiry was committed but before ledger update.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE execution_commands SET status='expired', lease_until=NULL "
            "WHERE command_id=?",
            (command_id,),
        )

    with TestClient(main.app):
        pass

    recovered_ledger = ExecutionLedger(str(database))
    assert recovered_ledger.get_intent(intent_id)["status"] == "unknown"

    recovery_events = [
        event for event in recovered_ledger.audit_events(intent_id)
        if event["event_type"] == "command_lease_expired"
    ]
    assert len(recovery_events) == 1
    assert recovered_ledger.controls() == {
        "trading_paused": True,
        "kill_switch_active": True,
    }


def test_app_startup_recovers_all_expired_commands_beyond_first_page(
    monkeypatch, tmp_path
):
    import json

    database = tmp_path / "large-startup-recovery.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))

    # Initialize both schemas and retain the default safe runtime controls.
    ExecutionLedger(str(database))
    ExecutionCommandQueue(str(database))

    payload = {
        "symbol": "EURUSDm",
        "side": "buy",
        "volume_lots": 0.01,
        "stop_loss": 1.08,
        "take_profit": 1.10,
    }
    encoded_payload = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )
    timestamp = "2026-01-01T00:00:00+00:00"

    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO order_intents
                (idempotency_key, payload_json, status, created_at, updated_at)
            VALUES (?, ?, 'approved', ?, ?)
            """,
            [
                (f"bulk-intent-{i:04d}", encoded_payload, timestamp, timestamp)
                for i in range(1001)
            ],
        )
        connection.executemany(
            """
            INSERT INTO execution_commands
                (command_id, intent_id, environment, payload_json, status,
                 created_at, lease_until, attempts, terminal_id)
            VALUES (?, ?, 'demo', ?, 'expired', ?, NULL, 1, 'terminal-after-crash')
            """,
            [
                (
                    f"bulk-command-{i:04d}",
                    f"bulk-intent-{i:04d}",
                    encoded_payload,
                    timestamp,
                )
                for i in range(1001)
            ],
        )

    with TestClient(main.app):
        pass

    with sqlite3.connect(database) as connection:
        unknown_count = connection.execute(
            "SELECT COUNT(*) FROM order_intents WHERE status='unknown'"
        ).fetchone()[0]
        recovery_event_count = connection.execute(
            "SELECT COUNT(*) FROM execution_audit "
            "WHERE event_type='command_lease_expired'"
        ).fetchone()[0]

    assert unknown_count == 1001
    assert recovery_event_count == 1001

    controls = ExecutionLedger(str(database)).controls()
    assert controls == {
        "trading_paused": True,
        "kill_switch_active": True,
    }


def test_startup_accepts_concurrent_recovery_only_with_matching_audit_event(
    monkeypatch, tmp_path
):
    database = tmp_path / "concurrent-recovery.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))
    ledger = ExecutionLedger(str(database))
    queue = ExecutionCommandQueue(str(database))
    intent_id = "concurrent-recovery-intent"
    command_id = "concurrent-recovery-command"
    payload = {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.08, "take_profit": 1.10,
    }
    ledger.create_intent(intent_id, payload)
    ledger.transition(intent_id, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id=command_id, intent_id=intent_id, payload=payload,
        environment="demo", trading_enabled=True,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE execution_commands SET status='expired' WHERE command_id=?",
            (command_id,),
        )

    class RacingLedger:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def transition(self, *args, **kwargs):
            ledger.transition(*args, **kwargs)
            raise ValueError("Simulated competing worker completed recovery")

    monkeypatch.setattr(main, "execution_ledger", lambda: RacingLedger())
    with TestClient(main.app):
        pass

    events = ledger.audit_events(intent_id)
    assert sum(
        event["event_type"] == "command_lease_expired"
        and event["details"].get("command_id") == command_id
        for event in events
    ) == 1


def test_startup_rejects_unrelated_concurrent_unknown_transition(
    monkeypatch, tmp_path
):
    import pytest

    database = tmp_path / "unrelated-transition.sqlite3"
    monkeypatch.setenv("FOREX_AUTOPILOT_TELEMETRY_DB", str(database))
    ledger = ExecutionLedger(str(database))
    queue = ExecutionCommandQueue(str(database))
    intent_id = "unrelated-transition-intent"
    command_id = "unrelated-transition-command"
    payload = {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.08, "take_profit": 1.10,
    }
    ledger.create_intent(intent_id, payload)
    ledger.transition(intent_id, "approved", event_type="preflight_approved")
    queue.enqueue_approved_intent(
        command_id=command_id, intent_id=intent_id, payload=payload,
        environment="demo", trading_enabled=True,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE execution_commands SET status='expired' WHERE command_id=?",
            (command_id,),
        )

    class RacingLedger:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def transition(self, *args, **kwargs):
            ledger.transition(
                intent_id, "unknown", event_type="unrelated_unknown"
            )
            raise ValueError("Unrelated transition")

    monkeypatch.setattr(main, "execution_ledger", lambda: RacingLedger())
    with pytest.raises(ValueError, match="Unrelated transition"):
        with TestClient(main.app):
            pass

    assert ledger.get_intent(intent_id)["status"] == "unknown"
    assert not ledger.has_command_lease_expiry_event(intent_id, command_id)
