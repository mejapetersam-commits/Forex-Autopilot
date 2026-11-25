"""Read-only position lifecycle comparison using snapshots and broker deal evidence."""
from __future__ import annotations

from math import isclose
from typing import Any


def _identity(position: dict[str, Any]) -> str:
    return str(position.get("position_id") or position.get("ticket") or "")


def _close_evidence(deals: list[dict[str, Any]]) -> dict[str, Any]:
    opened = sum(
        float(item.get("volume_lots", 0))
        for item in deals if item.get("entry") == "in"
    )
    closed = sum(
        float(item.get("volume_lots", 0))
        for item in deals if item.get("entry") in {"out", "out_by"}
    )
    ambiguous = any(item.get("entry") == "inout" for item in deals)
    confirmed = bool(deals) and not ambiguous and opened > 0 and closed >= opened - 1e-8
    return {
        "opened_volume_lots": round(opened, 8),
        "closed_volume_lots": round(closed, 8),
        "close_confirmed_by_deals": confirmed,
        "ambiguous_reversal_deal": ambiguous,
    }


def compare_position_lifecycle(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    deals_by_position: dict[str, list[dict[str, Any]]] | None = None,
    expected_magic: int,
) -> dict[str, Any]:
    """Describe observed transitions; absence alone is never treated as closure."""
    deals_by_position = deals_by_position or {}
    current_positions = {
        _identity(item): item for item in current.get("positions", [])
        if int(item.get("magic", -1)) == expected_magic and _identity(item)
    }
    previous_positions = {}
    compatible_previous = bool(
        previous
        and previous.get("terminal_id") == current.get("terminal_id")
        and previous.get("server") == current.get("server")
        and previous.get("environment") == "demo"
        and current.get("environment") == "demo"
    )
    if compatible_previous:
        previous_positions = {
            _identity(item): item for item in previous.get("positions", [])
            if int(item.get("magic", -1)) == expected_magic and _identity(item)
        }

    events: list[dict[str, Any]] = []
    for key, position in current_positions.items():
        old = previous_positions.get(key)
        if old is None:
            if compatible_previous:
                events.append({
                    "event_type": "position_opened_observed",
                    "position_id": key, "ticket": str(position.get("ticket", "")),
                    "symbol": position.get("symbol"),
                    "volume_lots": position.get("volume_lots"),
                })
            continue
        if str(old.get("ticket")) != str(position.get("ticket")):
            events.append({
                "event_type": "position_ticket_replaced",
                "position_id": key, "previous_ticket": str(old.get("ticket", "")),
                "current_ticket": str(position.get("ticket", "")),
            })
        old_volume = float(old.get("volume_lots", 0))
        new_volume = float(position.get("volume_lots", 0))
        if new_volume < old_volume and not isclose(new_volume, old_volume, abs_tol=1e-8):
            events.append({
                "event_type": "position_partially_closed_observed",
                "position_id": key, "previous_volume_lots": old_volume,
                "current_volume_lots": new_volume,
                "reduced_volume_lots": round(old_volume - new_volume, 8),
            })
        for field in ("stop_loss", "take_profit"):
            before, after = float(old.get(field, 0)), float(position.get(field, 0))
            if not isclose(before, after, rel_tol=0, abs_tol=1e-10):
                events.append({
                    "event_type": "position_protection_changed",
                    "position_id": key, "field": field,
                    "previous_value": before, "current_value": after,
                })

    for key, old in previous_positions.items():
        if key in current_positions:
            continue
        evidence = _close_evidence(deals_by_position.get(key, []))
        events.append({
            "event_type": "position_closed_confirmed" if evidence["close_confirmed_by_deals"]
                          else "position_disappearance_unconfirmed",
            "position_id": key, "previous_ticket": str(old.get("ticket", "")),
            "symbol": old.get("symbol"), **evidence,
            "reason": "broker_deal_volume_confirms_full_close"
                      if evidence["close_confirmed_by_deals"]
                      else "position_absent_from_latest_snapshot_without_sufficient_close_deals",
        })

    return {
        "status": "complete" if compatible_previous else "baseline_only",
        "previous_snapshot_available": compatible_previous,
        "current_snapshot_at": current.get("observed_at"),
        "events": events,
        "managed_positions_current": len(current_positions),
        "trading_enabled": False,
        "read_only": True,
    }
