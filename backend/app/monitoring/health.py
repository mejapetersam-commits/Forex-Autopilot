"""Operational health assessment for the telemetry and risk data pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _age(timestamp: str | None, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
        age = (now - observed.astimezone(timezone.utc)).total_seconds()
        if age < -5:
            return None
        return max(0.0, age)
    except (TypeError, ValueError):
        return None


def assess_system_health(
    heartbeat: dict[str, Any] | None,
    account: dict[str, Any] | None,
    quotes: list[dict[str, Any]],
    *,
    stale_after_seconds: int = 60,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    checks = []
    alerts = []

    heartbeat_age = _age(heartbeat.get("observed_at") if heartbeat else None, current)
    if not heartbeat:
        alerts.append({"code": "HEARTBEAT_MISSING", "severity": "critical", "message": "No MT5 heartbeat has been received."})
    elif not heartbeat.get("terminal_connected"):
        alerts.append({"code": "TERMINAL_DISCONNECTED", "severity": "critical", "message": "MT5 reports that the terminal is disconnected."})
    elif heartbeat_age is None or heartbeat_age > stale_after_seconds:
        alerts.append({"code": "HEARTBEAT_STALE", "severity": "critical", "message": "MT5 heartbeat is stale or has an invalid timestamp."})
    checks.append({"name": "mt5_heartbeat", "healthy": bool(heartbeat and heartbeat.get("terminal_connected") and heartbeat_age is not None and heartbeat_age <= stale_after_seconds), "age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None})

    account_age = _age(account.get("observed_at") if account else None, current)
    account_healthy = bool(account and account_age is not None and account_age <= stale_after_seconds)
    if not account:
        alerts.append({"code": "ACCOUNT_SNAPSHOT_MISSING", "severity": "critical", "message": "No account snapshot has been received."})
    elif not account_healthy:
        alerts.append({"code": "ACCOUNT_SNAPSHOT_STALE", "severity": "critical", "message": "Account telemetry is stale or has an invalid timestamp."})
    margin_level = None
    if account and float(account.get("margin") or 0) > 0:
        margin_level = float(account["equity"]) / float(account["margin"]) * 100
        if margin_level < 100:
            alerts.append({"code": "MARGIN_LEVEL_CRITICAL", "severity": "critical", "message": "Reported margin level is below 100%."})
        elif margin_level < 200:
            alerts.append({"code": "MARGIN_LEVEL_WARNING", "severity": "warning", "message": "Reported margin level is below 200%."})
    checks.append({"name": "account_snapshot", "healthy": account_healthy, "age_seconds": round(account_age, 1) if account_age is not None else None, "margin_level_pct": round(margin_level, 2) if margin_level is not None else None})

    fresh_quotes = 0
    for quote in quotes:
        quote_age = _age(quote.get("observed_at"), current)
        fresh = quote_age is not None and quote_age <= stale_after_seconds
        fresh_quotes += int(fresh)
        if not fresh:
            alerts.append({"code": "QUOTE_STALE", "severity": "warning", "symbol": quote.get("symbol"), "message": f"Quote is stale for {quote.get('symbol', 'unknown symbol')}."})
    if not quotes:
        alerts.append({"code": "QUOTES_MISSING", "severity": "critical", "message": "No market quotes have been received."})
    checks.append({"name": "market_quotes", "healthy": bool(quotes) and fresh_quotes == len(quotes), "fresh_count": fresh_quotes, "total_count": len(quotes)})

    status = "critical" if any(item["severity"] == "critical" for item in alerts) else "degraded" if alerts else "healthy"
    return {
        "status": status,
        "checks": checks,
        "alerts": alerts,
        "trading_enabled": False,
        "execution_mode": "disabled",
        "assessed_at": current.isoformat(),
    }
