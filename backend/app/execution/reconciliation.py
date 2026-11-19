"""Conservative reconciliation of known order IDs against broker deal history."""
from __future__ import annotations
from math import isclose
from typing import Any
from app.execution.ledger import ExecutionLedger
from app.market_data.telemetry_store import TelemetryStore


def reconcile_broker_history(ledger: ExecutionLedger, store: TelemetryStore, *, expected_magic: int, expected_terminal_id: str | None = None, expected_server: str | None = None, limit: int = 500) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for intent in ledger.intents_requiring_reconciliation(limit):
        order_id = str(intent.get("broker_order_id") or "")
        broker_tag = __import__("hashlib").sha256(
            intent["idempotency_key"].encode("utf-8")
        ).hexdigest()[:12]
        if order_id.isdigit() and int(order_id) > 0:
            deals = store.execution_deals_for_order(order_id)
        else:
            deals = store.execution_deals_for_tag(broker_tag)
            order_ids = sorted({str(deal["order_ticket"]) for deal in deals})
            if len(order_ids) > 1:
                reports.append({"intent_id": intent["idempotency_key"], "status": intent["status"], "result": "manual_review_required", "reasons": ["multiple_broker_orders_match_intent_tag"], "broker_order_ids": order_ids})
                continue
            if len(order_ids) == 1:
                order_id = order_ids[0]
            else:
                reports.append({"intent_id": intent["idempotency_key"], "status": intent["status"], "result": "awaiting_broker_history", "filled_volume_lots": 0.0})
                continue
        entries = [d for d in deals if d["entry"] == "in"]
        if not entries:
            reports.append({"intent_id": intent["idempotency_key"], "broker_order_id": order_id, "status": intent["status"], "result": "awaiting_entry_deal_history", "filled_volume_lots": 0.0})
            continue
        payload = intent["payload"]
        reasons = []
        for deal in entries:
            if deal["environment"] != "demo": reasons.append("broker_deal_not_demo")
            if expected_terminal_id and deal["terminal_id"] != expected_terminal_id: reasons.append("broker_terminal_mismatch")
            if expected_server and deal["server"] != expected_server: reasons.append("broker_server_mismatch")
            if deal["magic"] != expected_magic: reasons.append("broker_magic_mismatch")
            if deal["symbol"] != payload["symbol"].upper(): reasons.append("broker_symbol_mismatch")
            if deal["side"] != payload["side"]: reasons.append("broker_side_mismatch")
        filled = sum(float(d["volume_lots"]) for d in entries)
        requested = float(payload["volume_lots"])
        if filled > requested + 1e-8: reasons.append("broker_fill_exceeds_requested_volume")
        if reasons:
            reports.append({"intent_id": intent["idempotency_key"], "broker_order_id": order_id, "status": intent["status"], "result": "manual_review_required", "reasons": sorted(set(reasons)), "filled_volume_lots": round(filled, 8)})
            continue
        target = "filled" if isclose(filled, requested, rel_tol=0.0, abs_tol=1e-8) else ("partially_filled" if 0 < filled < requested else None)
        current = intent["status"]
        if target and target != current:
            try:
                updated = ledger.transition(intent["idempotency_key"], target, event_type="broker_history_reconciled", details={"broker_order_id": order_id, "filled_volume_lots": round(filled, 8), "requested_volume_lots": requested, "deal_tickets": [d["deal_ticket"] for d in entries]}, broker_order_id=order_id)
                current = updated["status"]
            except ValueError:
                reports.append({"intent_id": intent["idempotency_key"], "broker_order_id": order_id, "status": current, "result": "manual_review_required", "reasons": ["illegal_reconciliation_state_transition"], "filled_volume_lots": round(filled, 8)})
                continue
        reports.append({"intent_id": intent["idempotency_key"], "broker_order_id": order_id, "status": current, "result": "reconciled_fill" if target else "no_fill_evidence", "filled_volume_lots": round(filled, 8), "requested_volume_lots": requested, "deal_count": len(entries)})
    return {"status": "review_required" if any(r["result"] == "manual_review_required" for r in reports) else "complete", "intents_checked": len(reports), "results": reports, "trading_enabled": False}
