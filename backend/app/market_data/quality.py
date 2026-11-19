"""Market-data integrity checks for stored OHLC candles."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


def assess_candle_quality(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    interval = TIMEFRAME_SECONDS.get(timeframe.strip().upper())
    if interval is None:
        raise ValueError("Unsupported timeframe for data-quality checks.")
    issues: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
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
        except (KeyError, TypeError, ValueError) as exc:
            issues.append({"index": index, "type": "invalid_ohlc", "detail": str(exc)})

        try:
            timestamp = datetime.fromisoformat(str(candle["opened_at"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone.")
            timestamps.append(timestamp)
        except (KeyError, TypeError, ValueError) as exc:
            issues.append({"index": index, "type": "invalid_timestamp", "detail": str(exc)})

    gaps = []
    for previous, current in zip(timestamps, timestamps[1:]):
        delta = (current - previous).total_seconds()
        if delta <= 0:
            issues.append({"type": "non_increasing_timestamp", "previous": previous.isoformat(), "current": current.isoformat()})
        elif delta > interval * 1.5:
            gaps.append({
                "from": previous.isoformat(),
                "to": current.isoformat(),
                "elapsed_seconds": int(delta),
                "expected_interval_seconds": interval,
            })

    count = len(candles)
    return {
        "status": "healthy" if not issues else "issues_found",
        "candles_checked": count,
        "valid_ohlc_candles": valid_ohlc,
        "timestamp_count": len(timestamps),
        "gap_count": len(gaps),
        "gaps": gaps[:100],
        "issues": issues[:100],
        "note": "Weekend, holiday and broker-session closures can create legitimate gaps; review gap timestamps before classifying them as missing data.",
    }
