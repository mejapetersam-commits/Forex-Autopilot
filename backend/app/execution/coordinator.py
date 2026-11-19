"""Execution orchestration boundary: preflight, durable intent and audit.

This coordinator stops before broker submission. A concrete broker adapter must
be added and separately validated before any order can be sent.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.execution.ledger import ExecutionLedger
from app.execution.preflight import (
    ExecutionSnapshot,
    TradeIntent,
    evaluate_with_runtime_controls,
)


class ExecutionCoordinator:
    def __init__(self, ledger: ExecutionLedger) -> None:
        self.ledger = ledger

    def preflight_and_record(
        self,
        idempotency_key: str,
        intent: TradeIntent,
        snapshot: ExecutionSnapshot,
    ) -> dict[str, Any]:
        payload = {
            "symbol": intent.symbol.strip().upper(),
            "side": intent.side.strip().lower(),
            "volume_lots": intent.volume_lots,
            "stop_loss": intent.stop_loss,
            "take_profit": intent.take_profit,
            "requested_at": intent.requested_at.isoformat(),
        }
        record = self.ledger.create_intent(idempotency_key, payload)
        if record["status"] != "created":
            return {
                "idempotent_replay": True,
                "status": record["status"],
                "preflight": None,
                "broker_submission_attempted": False,
            }

        decision = evaluate_with_runtime_controls(
            intent, snapshot, self.ledger
        )
        if decision["approved"]:
            updated = self.ledger.transition(
                idempotency_key,
                "approved",
                event_type="preflight_approved",
                details={"symbol": decision["symbol"], "side": decision["side"]},
            )
        else:
            updated = self.ledger.transition(
                idempotency_key,
                "preflight_rejected",
                event_type="preflight_rejected",
                details={"reasons": decision["reasons"]},
            )
        return {
            "idempotent_replay": False,
            "status": updated["status"],
            "preflight": decision,
            "broker_submission_attempted": False,
        }

    def record_broker_event(
        self,
        idempotency_key: str,
        status: str,
        *,
        event_type: str,
        broker_order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a broker event supplied by a future audited adapter."""
        return self.ledger.transition(
            idempotency_key,
            status,
            event_type=event_type,
            broker_order_id=broker_order_id,
            details=details,
        )
