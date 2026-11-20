from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.broker.bridge import MT5ExecutionDeal, MT5ExecutionHistory, MT5ExecutionOrder, MT5ExecutionOrderHistory
from app.execution.ledger import ExecutionLedger
from app.execution.reconciliation import reconcile_broker_history
from app.market_data.telemetry_store import TelemetryStore


def order_history(state="placed", *, comment="FA:abcdef123456", current=0.01):
    now = datetime.now(timezone.utc)
    order = MT5ExecutionOrder(
        order_ticket="12345", symbol="EURUSDm", order_type="buy", state=state,
        initial_volume=0.01, current_volume=current, price=1.1,
        stop_loss=1.099, take_profit=1.102, magic=61119001,
        comment=comment, setup_at=now - timedelta(minutes=2),
        done_at=now if state in {"canceled", "rejected", "expired", "filled"} else None,
    )
    return MT5ExecutionOrderHistory(
        terminal_id="demo-terminal", environment="demo", server="Exness-MT5Trial",
        history_from=now - timedelta(days=1), history_to=now,
        observed_at=now, orders=[order],
    )


def make_intent(ledger, key="order-state-intent"):
    ledger.create_intent(key, {
        "symbol": "EURUSDm", "side": "buy", "volume_lots": 0.01,
        "stop_loss": 1.099, "take_profit": 1.102,
    })
    ledger.transition(key, "approved", event_type="preflight_approved")
    ledger.transition(key, "submitted", event_type="broker_submit")
    ledger.transition(key, "acknowledged", event_type="broker_ack", broker_order_id="12345")
    return key


def test_order_history_validates_and_normalizes_symbol():
    payload = order_history()
    assert payload.orders[0].symbol == "EURUSDM"
    original = payload.orders[0]
    with pytest.raises(ValidationError):
        MT5ExecutionOrder(
            order_ticket=original.order_ticket, symbol=original.symbol,
            order_type=original.order_type, state=original.state,
            initial_volume=original.initial_volume, current_volume=0.02,
            price=original.price, stop_loss=original.stop_loss,
            take_profit=original.take_profit, magic=original.magic,
            comment=original.comment, setup_at=original.setup_at,
        )


def test_order_history_persists_and_updates_state_idempotently(tmp_path):
    store = TelemetryStore(str(tmp_path / "telemetry.sqlite3"))
    placed = order_history("placed")
    assert store.save_execution_order_history(placed) == 1
    assert store.save_execution_order_history(placed) == 1
    canceled = placed.model_copy(update={
        "orders": [placed.orders[0].model_copy(update={
            "state": "canceled", "current_volume": 0.0,
            "done_at": datetime.now(timezone.utc),
        })],
        "observed_at": datetime.now(timezone.utc),
    })
    store.save_execution_order_history(canceled)
    result = store.execution_orders_for_ticket("12345")
    assert result["state"] == "canceled"
    assert result["current_volume"] == 0.0


def test_order_history_rejects_conflicting_ticket_identity(tmp_path):
    store = TelemetryStore(str(tmp_path / "telemetry.sqlite3"))
    store.save_execution_order_history(order_history())
    conflict = order_history().model_copy(update={
        "orders": [order_history().orders[0].model_copy(update={"symbol": "GBPUSDm"})]
    })
    with pytest.raises(ValueError, match="Conflicting broker evidence"):
        store.save_execution_order_history(conflict)


def test_pending_order_is_not_misreported_as_a_fill(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    ledger, store = ExecutionLedger(path), TelemetryStore(path)
    key = make_intent(ledger)
    store.save_execution_order_history(order_history("placed"))
    result = reconcile_broker_history(ledger, store, expected_magic=61119001,
                                      expected_terminal_id="demo-terminal",
                                      expected_server="Exness-MT5Trial")
    assert result["results"][0]["result"] == "broker_order_pending"
    assert ledger.get_intent(key)["status"] == "acknowledged"


@pytest.mark.parametrize("state,expected", [("canceled", "reconciled_canceled"),
                                             ("expired", "reconciled_expired"),
                                             ("rejected", "reconciled_rejected")])
def test_terminal_order_states_reconcile_without_deal_fills(tmp_path, state, expected):
    path = str(tmp_path / "shared.sqlite3")
    ledger, store = ExecutionLedger(path), TelemetryStore(path)
    key = make_intent(ledger)
    store.save_execution_order_history(order_history(state, current=0.0))
    result = reconcile_broker_history(ledger, store, expected_magic=61119001,
                                      expected_terminal_id="demo-terminal",
                                      expected_server="Exness-MT5Trial")
    assert result["results"][0]["result"] == expected
    assert ledger.get_intent(key)["status"] == "reconciled"


def test_cancelled_order_with_partial_deal_fill_requires_manual_review(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    ledger, store = ExecutionLedger(path), TelemetryStore(path)
    key = make_intent(ledger)
    now = datetime.now(timezone.utc)
    deal = MT5ExecutionDeal(
        deal_ticket="987", order_ticket="12345", position_id="998877", symbol="EURUSDm",
        side="buy", entry="in", volume_lots=0.004, price=1.1,
        magic=61119001, comment="", occurred_at=now - timedelta(minutes=1),
    )
    store.save_execution_history(MT5ExecutionHistory(
        terminal_id="demo-terminal", environment="demo", server="Exness-MT5Trial",
        history_from=now - timedelta(days=1), history_to=now,
        observed_at=now, deals=[deal],
    ))
    store.save_execution_order_history(order_history("canceled", current=0.0))
    result = reconcile_broker_history(ledger, store, expected_magic=61119001,
                                      expected_terminal_id="demo-terminal",
                                      expected_server="Exness-MT5Trial")
    assert result["results"][0]["result"] == "manual_review_required"
    assert "broker_order_terminal_with_unfilled_remainder" in result["results"][0]["reasons"]
    assert ledger.get_intent(key)["status"] == "acknowledged"

def test_broker_partial_order_state_waits_for_deal_history(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    ledger, store = ExecutionLedger(path), TelemetryStore(path)
    key = make_intent(ledger)
    store.save_execution_order_history(order_history("partial", current=0.006))
    result = reconcile_broker_history(
        ledger, store, expected_magic=61119001,
        expected_terminal_id="demo-terminal", expected_server="Exness-MT5Trial",
    )
    assert result["results"][0]["result"] == "broker_order_pending"
    assert result["results"][0]["broker_state"] == "partial"
    assert result["results"][0]["remaining_volume_lots"] == pytest.approx(0.006)
    assert ledger.get_intent(key)["status"] == "acknowledged"
