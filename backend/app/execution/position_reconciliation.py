"""Read-only comparison of open MT5 managed positions to known intents."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from math import isfinite
from typing import Any


def reconcile_open_positions(
    positions: list[dict[str, Any]],
    intents: list[dict[str, Any]],
    *,
    expected_magic: int,
) -> dict[str, Any]:
    """Match managed positions to intent tags and verify immutable trade identity.

    Current volume is validated as positive and finite, but is not compared with
    requested volume: legitimate partial closes change the open amount. Fill
    accounting belongs to broker deal-history reconciliation. This function is
    strictly read-only.
    """
    known_tags: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for intent in intents:
        key = str(intent.get("idempotency_key") or "")
        if key:
            tag = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            known_tags[tag].append(intent)

    checked: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    identities: dict[str, list[str]] = defaultdict(list)

    for index, position in enumerate(positions):
        try:
            magic = int(position.get("magic", -1))
        except (TypeError, ValueError, OverflowError):
            invalid_records.append({
                "position_index": index,
                "reason": "broker_position_magic_invalid",
            })
            continue
        if magic != expected_magic:
            continue

        ticket = str(position.get("ticket") or "")
        position_id = str(position.get("position_id") or "")
        identity = position_id or ticket
        if identity:
            identities[identity].append(ticket)

        comment = str(position.get("comment") or "")
        tag = comment[3:15] if comment.startswith("FA:") else ""
        matches = known_tags.get(tag, [])
        intent = matches[0] if len(matches) == 1 else None
        payload = intent.get("payload", {}) if intent else {}

        try:
            volume = float(position.get("volume_lots", 0))
        except (TypeError, ValueError, OverflowError):
            volume = float("nan")

        row = {
            "ticket": ticket,
            "position_id": position_id,
            "symbol": str(position.get("symbol") or "").upper(),
            "side": position.get("side"),
            "volume_lots": volume if isfinite(volume) else None,
            "intent_id": intent.get("idempotency_key") if intent else None,
        }
        checked.append(row)

        if len(matches) != 1:
            orphaned.append({
                **row,
                "reason": "ambiguous_intent_tag" if len(matches) > 1
                          else "managed_position_without_matching_intent_tag",
            })
            continue

        reasons = []
        if row["symbol"] != str(payload.get("symbol") or "").upper():
            reasons.append("broker_position_symbol_mismatch")
        if row["side"] != payload.get("side"):
            reasons.append("broker_position_side_mismatch")
        if not ticket or not identity:
            reasons.append("broker_position_identity_missing")
        if not isfinite(volume) or volume <= 0:
            reasons.append("broker_position_volume_invalid")
        if reasons:
            mismatched.append({**row, "reasons": reasons})

    duplicates = [
        {"position_identity": identity, "tickets": sorted(tickets)}
        for identity, tickets in identities.items() if len(tickets) > 1
    ]
    review_required = bool(orphaned or mismatched or duplicates or invalid_records)
    return {
        "status": "review_required" if review_required else "complete",
        "managed_positions_checked": len(checked),
        "orphaned_positions": orphaned,
        "mismatched_positions": mismatched,
        "duplicate_position_identities": duplicates,
        "invalid_position_records": invalid_records,
        "trading_enabled": False,
        "read_only": True,
    }
