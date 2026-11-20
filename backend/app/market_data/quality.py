"""Market-data integrity and history-readiness checks for stored OHLC candles."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


def _possible_weekend_closure(previous: datetime, current: datetime, interval_seconds: int) -> bool:
    """Heuristic only: identify gaps mostly contained in the common UTC FX weekend pause.

    Broker sessions and daylight-saving schedules differ. Gaps outside this
    broad Friday/Sunday window remain unclassified and require calendar review.
    """
    from datetime import timedelta, time as clock_time

    previous = previous.astimezone(timezone.utc)
    current = current.astimezone(timezone.utc)
    if current <= previous:
        return False
    total_seconds = (current - previous).total_seconds()
    overlap_seconds = 0.0
    day = previous.date() - timedelta(days=previous.weekday() + 1)
    final_day = current.date()
    while day <= final_day:
        if day.weekday() == 4:  # Friday
            start = datetime.combine(day, clock_time(21, 0), tzinfo=previous.tzinfo)
            end = start + timedelta(days=2)
            overlap_start = max(previous, start)
            overlap_end = min(current, end)
            if overlap_end > overlap_start:
                overlap_seconds += (overlap_end - overlap_start).total_seconds()
        day += timedelta(days=1)
    outside_seconds = max(0.0, total_seconds - overlap_seconds)
    return overlap_seconds > 0 and outside_seconds <= max(4 * 3600, interval_seconds * 2)


def assess_candle_quality(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    interval = TIMEFRAME_SECONDS.get(timeframe.strip().upper())
    if interval is None:
        raise ValueError("Unsupported timeframe for data-quality checks.")

    issues: list[dict[str, Any]] = []
    valid_timestamps: list[tuple[int, datetime]] = []
    valid_ohlc = 0
    for index, candle in enumerate(candles):
        try:
            values = [float(candle[key]) for key in ("open", "high", "low", "close")]
            if not all(isfinite(value) and value > 0 for value in values):
                raise ValueError("OHLC values must be positive finite numbers.")
            op, high, low, close = values
            if high < max(op, low, close) or low > min(op, high, close):
                raise ValueError("OHLC high/low relationship is invalid.")
            valid_ohlc += 1
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            issues.append({"index": index, "type": "invalid_ohlc", "detail": str(exc)})

        try:
            timestamp = datetime.fromisoformat(str(candle["opened_at"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone.")
            valid_timestamps.append((index, timestamp))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            issues.append({"index": index, "type": "invalid_timestamp", "detail": str(exc)})

    gaps: list[dict[str, Any]] = []
    for (previous_index, previous), (current_index, current) in zip(valid_timestamps, valid_timestamps[1:]):
        delta = (current - previous).total_seconds()
        if delta <= 0:
            issue_type = "duplicate_timestamp" if delta == 0 else "out_of_order_timestamp"
            issues.append({
                "index": current_index, "type": issue_type,
                "previous_index": previous_index,
                "previous": previous.isoformat(), "current": current.isoformat(),
            })
        elif delta > interval * 1.5:
            possible_weekend = _possible_weekend_closure(previous, current, interval)
            gaps.append({
                "from": previous.isoformat(), "to": current.isoformat(),
                "elapsed_seconds": int(delta),
                "missing_interval_estimate": max(0, int(delta // interval) - 1),
                "expected_interval_seconds": interval,
                "classification": "possible_weekend_closure" if possible_weekend else "calendar_review_required",
                "classification_note": (
                    "Likely overlaps the common Friday-to-Sunday FX weekend closure; verify against this broker's session and daylight-saving schedule."
                    if possible_weekend else
                    "Not explained by the weekend heuristic. Review broker trading hours, holidays, maintenance and feed completeness."
                ),
                "previous_index": previous_index, "current_index": current_index,
            })

    count = len(candles)
    issue_count = len(issues)
    return {
        "status": "healthy" if issue_count == 0 else "issues_found",
        "candles_checked": count,
        "valid_ohlc_candles": valid_ohlc,
        "valid_ohlc_pct": round(valid_ohlc / count * 100, 2) if count else 0.0,
        "timestamp_count": len(valid_timestamps),
        "issue_count": issue_count,
        "gap_count": len(gaps),
        "possible_weekend_gap_count": sum(gap["classification"] == "possible_weekend_closure" for gap in gaps),
        "calendar_review_gap_count": sum(gap["classification"] == "calendar_review_required" for gap in gaps),
        "gaps": gaps[:100],
        "issues": issues[:100],
        "note": "Gap classifications are heuristic only. The weekend label is not broker-calendar confirmation; review unclassified gaps against broker hours, holidays, maintenance and daylight-saving changes.",
    }


def assess_candle_readiness(
    candles: list[dict[str, Any]],
    timeframe: str,
    *,
    minimum_candles: int = 500,
) -> dict[str, Any]:
    """Assess whether a history sample is adequate for research, never for execution."""
    if minimum_candles < 1:
        raise ValueError("Minimum candle target must be at least one.")
    quality = assess_candle_quality(candles, timeframe)
    count = quality["candles_checked"]
    valid_count = quality["valid_ohlc_candles"]
    reasons: list[str] = []
    if count < minimum_candles:
        reasons.append(f"History target not met: {count} of {minimum_candles} candles.")
    if quality["issue_count"]:
        reasons.append(f"{quality['issue_count']} candle integrity issue(s) require correction or review.")
    if valid_count < minimum_candles:
        reasons.append(f"Only {valid_count} candles have valid OHLC values; {minimum_candles} are required.")

    ready = not reasons
    return {
        "status": "ready_for_research" if ready else (
            "integrity_review_required" if quality["issue_count"] else "insufficient_history"
        ),
        "ready_for_research": ready,
        "candles_available": count,
        "valid_candles": valid_count,
        "minimum_candles": minimum_candles,
        "coverage_pct": round(min(100.0, valid_count / minimum_candles * 100), 2),
        "quality": quality,
        "reasons": reasons,
        "execution_enabled": False,
        "trading_enabled": False,
        "note": "Research-data readiness only. It does not authorize demo or live execution.",
    }
