from datetime import datetime, timezone
import pytest
from app.broker.bridge import MT5ExecutionDeal, MT5ExecutionHistory
from app.execution.ledger import ExecutionLedger
from app.execution.reconciliation import reconcile_broker_history
from app.market_data.telemetry_store import TelemetryStore


def deal(ticket, order, volume, *, symbol="EURUSDm", side="buy", magic=61119001, position_id="555"):
    return MT5ExecutionDeal(deal_ticket=str(ticket), order_ticket=str(order), position_id=position_id, symbol=symbol, side=side, entry="in", volume_lots=volume, price=1.1, magic=magic, occurred_at=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))


def history(*deals):
    observed=datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc)
    return MT5ExecutionHistory(terminal_id="demo-terminal", environment="demo", server="Exness-MT5Trial", history_from=datetime(2026, 11, 19, 11, 0, tzinfo=timezone.utc), history_to=observed, observed_at=observed, deals=list(deals))


def approved_intent(ledger, key="intent-fill", volume=0.01):
    ledger.create_intent(key, {"symbol":"EURUSDm","side":"buy","volume_lots":volume,"stop_loss":1.099,"take_profit":1.102})
    ledger.transition(key,"approved",event_type="preflight_approved")
    ledger.transition(key,"submitted",event_type="broker_submit")
    ledger.transition(key,"acknowledged",event_type="broker_ack",broker_order_id="12345")
    return key


def test_partial_fills_accumulate_idempotently(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3")); key=approved_intent(ledger)
    snap=history(deal(1,12345,0.004),deal(2,12345,0.003))
    store.save_execution_history(snap); store.save_execution_history(snap)
    result=reconcile_broker_history(ledger,store,expected_magic=61119001,expected_terminal_id='demo-terminal',expected_server='Exness-MT5Trial')
    assert result["status"]=="complete" and ledger.get_intent(key)["status"]=="partially_filled"
    assert result["results"][0]["filled_volume_lots"]==pytest.approx(0.007)


def test_full_fill_reconciliation_is_idempotent(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3")); key=approved_intent(ledger)
    store.save_execution_history(history(deal(3,12345,0.01)))
    reconcile_broker_history(ledger,store,expected_magic=61119001)
    reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert ledger.get_intent(key)["status"]=="reconciled" and len(ledger.audit_events(key))==6


@pytest.mark.parametrize("kwargs,reason",[({"magic":99},"broker_magic_mismatch"),({"symbol":"GBPUSDm"},"broker_symbol_mismatch"),({"side":"sell"},"broker_side_mismatch")])
def test_mismatched_evidence_requires_manual_review(tmp_path,kwargs,reason):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3")); key=approved_intent(ledger)
    store.save_execution_history(history(deal(4,12345,0.01,**kwargs)))
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert result["results"][0]["result"]=="manual_review_required" and reason in result["results"][0]["reasons"]
    assert ledger.get_intent(key)["status"]=="acknowledged"


def test_missing_history_does_not_infer_rejection(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3")); key=approved_intent(ledger)
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert result["results"][0]["result"]=="awaiting_broker_history" and ledger.get_intent(key)["status"]=="acknowledged"


def test_overfill_requires_manual_review(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3")); key=approved_intent(ledger)
    store.save_execution_history(history(deal(5,12345,0.02)))
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert "broker_fill_exceeds_requested_volume" in result["results"][0]["reasons"] and ledger.get_intent(key)["status"]=="acknowledged"


def test_history_rejects_duplicate_deal_tickets():
    with pytest.raises(ValueError,match="unique"): history(deal(7,12345,0.01),deal(7,12345,0.01))


def test_unknown_intent_can_recover_by_broker_comment_tag(tmp_path):
    import hashlib
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3")); store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    key=approved_intent(ledger)
    ledger.transition(key,"unknown",event_type="terminal_lost_after_dispatch")
    tag=hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    snap=history(deal(9,12345,0.01))
    tagged=snap.model_copy(update={"deals":[snap.deals[0].model_copy(update={"comment":"FA:"+tag})]})
    store.save_execution_history(tagged)
    result=reconcile_broker_history(ledger,store,expected_magic=61119001,expected_terminal_id="demo-terminal",expected_server="Exness-MT5Trial")
    assert result["results"][0]["status"]=="reconciled"
    assert ledger.get_intent(key)["status"]=="reconciled"



def test_partial_fill_can_later_reconcile_to_full_fill(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3"))
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    key=approved_intent(ledger)
    first=deal(10,12345,0.004)
    store.save_execution_history(history(first))
    partial=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert partial["results"][0]["result"]=="reconciled_partial_fill"
    assert ledger.get_intent(key)["status"]=="partially_filled"

    store.save_execution_history(history(first,deal(11,12345,0.006)))
    complete=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert complete["results"][0]["result"]=="reconciled_full_fill"
    assert ledger.get_intent(key)["status"]=="reconciled"


def test_conflicting_reuse_of_broker_deal_ticket_is_rejected(tmp_path):
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    original=deal(12,12345,0.01)
    store.save_execution_history(history(original))
    conflicting=original.model_copy(update={"volume_lots":0.02})
    with pytest.raises(ValueError,match="Conflicting broker evidence"):
        store.save_execution_history(history(conflicting))


def test_reversal_deal_requires_manual_review(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3"))
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    key=approved_intent(ledger)
    reversal=deal(13,12345,0.01).model_copy(update={"entry":"inout"})
    store.save_execution_history(history(reversal))
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert result["results"][0]["result"]=="manual_review_required"
    assert "broker_reversal_deal_requires_position_review" in result["results"][0]["reasons"]
    assert ledger.get_intent(key)["status"]=="acknowledged"


def test_reconciliation_preserves_deal_to_position_link(tmp_path):
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3"))
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    key=approved_intent(ledger)
    store.save_execution_history(history(deal(21,12345,0.01,position_id="998877")))
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert result["results"][0]["position_ids"] == ["998877"]
    assert store.execution_deals_for_position("998877")[0]["deal_ticket"] == "21"


def test_legacy_deal_can_be_enriched_with_position_identifier(tmp_path):
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    legacy=deal(31,12345,0.01,position_id="")
    store.save_execution_history(history(legacy))
    enriched=deal(31,12345,0.01,position_id="887766")
    store.save_execution_history(history(enriched))
    assert store.execution_deals_for_position("887766")[0]["deal_ticket"] == "31"


def test_conflicting_nonempty_position_identifier_is_rejected(tmp_path):
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    store.save_execution_history(history(deal(32,12345,0.01,position_id="887766")))
    with pytest.raises(ValueError, match="position_id"):
        store.save_execution_history(history(deal(32,12345,0.01,position_id="112233")))

def test_unknown_intent_tag_recovery_preserves_position_identifiers(tmp_path):
    import hashlib
    ledger=ExecutionLedger(str(tmp_path/"shared.sqlite3"))
    store=TelemetryStore(str(tmp_path/"shared.sqlite3"))
    key=approved_intent(ledger)
    ledger.transition(key,"unknown",event_type="terminal_lost_after_dispatch")
    tag=hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    tagged_deal=deal(41,12345,0.01,position_id="998812").model_copy(
        update={"comment":"FA:"+tag}
    )
    store.save_execution_history(history(tagged_deal))
    result=reconcile_broker_history(ledger,store,expected_magic=61119001)
    assert result["results"][0]["result"] == "reconciled_full_fill"
    assert result["results"][0]["position_ids"] == ["998812"]
    assert store.execution_deals_for_position("998812")[0]["deal_ticket"] == "41"
