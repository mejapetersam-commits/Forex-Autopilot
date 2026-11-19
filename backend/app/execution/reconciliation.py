"""Conservative, idempotent reconciliation of execution intents to MT5 deal history."""
from __future__ import annotations

import hashlib
from math import isclose
from typing import Any

from app.execution.ledger import ExecutionLedger
from app.market_data.telemetry_store import TelemetryStore


def reconcile_broker_history(
    ledger: ExecutionLedger,
    store: TelemetryStore,
    *,
    expected_magic: int,
    expected_terminal_id: str | None = None,
    expected_server: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Reconcile fills only from immutable, identity-matched broker deal evidence.

    A full requested entry volume is moved through filled to reconciled.
    Partial fills remain open to further broker evidence; missing evidence never
    implies rejection or cancellation.
    """
    reports: list[dict[str, Any]] = []
    for intent in ledger.intents_requiring_reconciliation(limit):
        intent_id = intent["idempotency_key"]
        current = intent["status"]
        order_id = str(intent.get("broker_order_id") or "")
        broker_tag = hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:12]

        order_deals = (
            store.execution_deals_for_order(order_id)
            if order_id.isdigit() and int(order_id) > 0 else []
        )
        tagged_deals = store.execution_deals_for_tag(broker_tag)
        tagged_orders = store.execution_orders_for_tag(broker_tag)
        tagged_order_ids = sorted({str(deal["order_ticket"]) for deal in tagged_deals})
        tagged_order_ids_from_orders = sorted({str(order["order_ticket"]) for order in tagged_orders})

        if len(set(tagged_order_ids + tagged_order_ids_from_orders)) > 1:
            reports.append({
                "intent_id": intent_id, "status": current,
                "result": "manual_review_required",
                "reasons": ["multiple_broker_orders_match_intent_tag"],
                "broker_order_ids": sorted(set(tagged_order_ids + tagged_order_ids_from_orders)),
            })
            continue
        if not order_deals and tagged_deals:
            order_deals = tagged_deals
            order_id = tagged_order_ids[0]
        elif order_deals and tagged_deals and tagged_order_ids != [order_id]:
            reports.append({
                "intent_id": intent_id, "broker_order_id": order_id,
                "status": current, "result": "manual_review_required",
                "reasons": ["broker_order_id_and_intent_tag_disagree"],
            })
            continue

        if not order_deals:
            order_evidence = (
                store.execution_orders_for_ticket(order_id)
                if order_id.isdigit() and int(order_id) > 0 else None
            )
            if order_evidence is None and tagged_orders and len(tagged_orders) == 1:
                order_evidence = tagged_orders[0]
                order_id = str(order_evidence["order_ticket"])
            if order_evidence is not None:
                identity_reasons = []
                if order_evidence["environment"] != "demo":
                    identity_reasons.append("broker_order_not_demo")
                if expected_terminal_id and order_evidence["terminal_id"] != expected_terminal_id:
                    identity_reasons.append("broker_terminal_mismatch")
                if expected_server and order_evidence["server"] != expected_server:
                    identity_reasons.append("broker_server_mismatch")
                if order_evidence["magic"] != expected_magic:
                    identity_reasons.append("broker_magic_mismatch")
                if order_evidence["symbol"] != intent["payload"]["symbol"].upper():
                    identity_reasons.append("broker_symbol_mismatch")
                if order_evidence["order_type"] != intent["payload"]["side"]:
                    identity_reasons.append("broker_order_side_mismatch")
                if not identity_reasons:
                    broker_state = order_evidence["state"]
                    if broker_state in {"canceled", "expired", "rejected"}:
                        target = "rejected" if broker_state == "rejected" else "cancelled"
                        if current in {"approved", "submitted", "acknowledged", "unknown", "cancel_requested"}:
                            try:
                                if target == "cancelled" and current == "acknowledged":
                                    updated = ledger.transition(
                                        intent_id, "cancel_requested",
                                        event_type="broker_history_confirms_cancel_request",
                                        broker_order_id=order_id,
                                        details={"broker_state": broker_state},
                                    )
                                    current = updated["status"]
                                elif target == "cancelled" and current == "submitted":
                                    updated = ledger.transition(
                                        intent_id, "unknown",
                                        event_type="broker_history_cancel_recovery",
                                        broker_order_id=order_id,
                                        details={"broker_state": broker_state},
                                    )
                                    current = updated["status"]
                                updated = ledger.transition(
                                    intent_id, target,
                                    event_type="broker_order_terminal_state_confirmed",
                                    broker_order_id=order_id,
                                    details={"broker_state": broker_state,
                                             "evidence": "authenticated_mt5_demo_order_history"},
                                )
                                current = updated["status"]
                                updated = ledger.transition(
                                    intent_id, "reconciled",
                                    event_type="broker_order_history_reconciled",
                                    broker_order_id=order_id,
                                    details={"broker_state": broker_state},
                                )
                                current = updated["status"]
                                reports.append({
                                    "intent_id": intent_id, "broker_order_id": order_id,
                                    "status": current, "result": "reconciled_" + broker_state,
                                    "filled_volume_lots": 0.0,
                                })
                                continue
                            except (KeyError, ValueError):
                                identity_reasons.append("illegal_terminal_order_state_transition")
                        else:
                            identity_reasons.append("terminal_order_state_after_partial_fill_requires_review")
                    elif broker_state in {"placed", "started", "request_add", "request_modify", "request_cancel"}:
                        reports.append({
                            "intent_id": intent_id, "broker_order_id": order_id,
                            "status": current, "result": "broker_order_pending",
                            "broker_state": broker_state,
                            "remaining_volume_lots": order_evidence["current_volume"],
                        })
                        continue
                    elif broker_state == "filled":
                        reports.append({
                            "intent_id": intent_id, "broker_order_id": order_id,
                            "status": current, "result": "awaiting_fill_deal_history",
                            "broker_state": broker_state,
                        })
                        continue
                reports.append({
                    "intent_id": intent_id, "broker_order_id": order_id,
                    "status": current, "result": "manual_review_required",
                    "reasons": sorted(set(identity_reasons)),
                })
                continue
            reports.append({
                "intent_id": intent_id, "status": current,
                "result": "awaiting_broker_history", "filled_volume_lots": 0.0,
            })
            continue

        # Reversal/in-out deals need position-level treatment; do not miscount
        # them as fresh entry fills or silently reconcile them as a normal order.
        if any(deal["entry"] == "inout" for deal in order_deals):
            reports.append({
                "intent_id": intent_id, "broker_order_id": order_id,
                "status": current, "result": "manual_review_required",
                "reasons": ["broker_reversal_deal_requires_position_review"],
            })
            continue

        entries = [deal for deal in order_deals if deal["entry"] == "in"]
        if not entries:
            reports.append({
                "intent_id": intent_id, "broker_order_id": order_id,
                "status": current, "result": "awaiting_entry_deal_history",
                "filled_volume_lots": 0.0,
            })
            continue

        payload = intent["payload"]
        reasons: list[str] = []
        for deal in order_deals:
            if deal["environment"] != "demo":
                reasons.append("broker_deal_not_demo")
            if expected_terminal_id and deal["terminal_id"] != expected_terminal_id:
                reasons.append("broker_terminal_mismatch")
            if expected_server and deal["server"] != expected_server:
                reasons.append("broker_server_mismatch")
            if deal["magic"] != expected_magic:
                reasons.append("broker_magic_mismatch")
            if deal["symbol"] != payload["symbol"].upper():
                reasons.append("broker_symbol_mismatch")
        for deal in entries:
            if deal["side"] != payload["side"]:
                reasons.append("broker_side_mismatch")

        filled = sum(float(deal["volume_lots"]) for deal in entries)
        requested = float(payload["volume_lots"])
        if filled > requested + 1e-8:
            reasons.append("broker_fill_exceeds_requested_volume")
        if reasons:
            reports.append({
                "intent_id": intent_id, "broker_order_id": order_id,
                "status": current, "result": "manual_review_required",
                "reasons": sorted(set(reasons)),
                "filled_volume_lots": round(filled, 8),
            })
            continue

        full_fill = isclose(filled, requested, rel_tol=0.0, abs_tol=1e-8)
        partial_fill = 0 < filled < requested
        deal_tickets = sorted(deal["deal_ticket"] for deal in entries)
        details = {
            "broker_order_id": order_id,
            "filled_volume_lots": round(filled, 8),
            "requested_volume_lots": requested,
            "deal_tickets": deal_tickets,
            "evidence": "authenticated_mt5_demo_deal_history",
        }

        try:
            if full_fill:
                if current != "filled":
                    updated = ledger.transition(
                        intent_id, "filled",
                        event_type="broker_history_full_fill_confirmed",
                        details=details, broker_order_id=order_id,
                    )
                    current = updated["status"]
                if current == "filled":
                    updated = ledger.transition(
                        intent_id, "reconciled",
                        event_type="broker_history_reconciled",
                        details=details, broker_order_id=order_id,
                    )
                    current = updated["status"]
            elif partial_fill and current != "partially_filled":
                updated = ledger.transition(
                    intent_id, "partially_filled",
                    event_type="broker_history_partial_fill",
                    details=details, broker_order_id=order_id,
                )
                current = updated["status"]
        except (KeyError, ValueError):
            reports.append({
                "intent_id": intent_id, "broker_order_id": order_id,
                "status": current, "result": "manual_review_required",
                "reasons": ["illegal_reconciliation_state_transition"],
                "filled_volume_lots": round(filled, 8),
            })
            continue

        reports.append({
            "intent_id": intent_id, "broker_order_id": order_id,
            "status": current,
            "result": "reconciled_full_fill" if full_fill else (
                "reconciled_partial_fill" if partial_fill else "no_fill_evidence"
            ),
            "filled_volume_lots": round(filled, 8),
            "requested_volume_lots": requested,
            "deal_count": len(entries),
            "deal_tickets": deal_tickets,
        })

    needs_review = any(
        report["result"] == "manual_review_required" for report in reports
    )
    return {
        "status": "review_required" if needs_review else "complete",
        "intents_checked": len(reports),
        "results": reports,
        "trading_enabled": False,
    }
