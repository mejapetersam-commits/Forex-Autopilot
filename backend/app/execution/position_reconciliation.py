"""Read-only comparison of open MT5 managed positions to known intents."""
from __future__ import annotations

import hashlib
from typing import Any


def reconcile_open_positions(
    positions: list[dict[str, Any]],
    intents: list[dict[str, Any]],
    *,
    expected_magic: int,
) -> dict[str, Any]:
    """Flag managed positions whose deterministic intent tag is not in the ledger.

    A position without a matching tag is not automatically closed or modified.
    Non-managed magic numbers are deliberately excluded.
    """
    known_tags = {
        hashlib.sha256(str(item["idempotency_key"]).encode("utf-8")).hexdigest()[:12]:
        item["idempotency_key"]
        for item in intents
    }
    checked = []
    orphaned = []
    for position in positions:
        if int(position.get("magic", -1)) != expected_magic:
            continue
        comment = str(position.get("comment") or "")
        tag = comment[3:15] if comment.startswith("FA:") else ""
        intent_id = known_tags.get(tag)
        row = {
            "ticket": str(position.get("ticket", "")),
            "position_id": str(position.get("position_id", "")),
            "symbol": str(position.get("symbol", "")),
            "side": position.get("side"),
            "volume_lots": float(position.get("volume_lots", 0)),
            "intent_id": intent_id,
        }
        checked.append(row)
        if intent_id is None:
            orphaned.append({**row, "reason": "managed_position_without_matching_intent_tag"})
    return {
        "status": "review_required" if orphaned else "complete",
        "managed_positions_checked": len(checked),
        "orphaned_positions": orphaned,
        "trading_enabled": False,
    }
