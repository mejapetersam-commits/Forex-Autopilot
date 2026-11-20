"""Fail-closed aggregate portfolio risk gate for execution dispatch."""
from __future__ import annotations

from math import isfinite
from typing import Any


def evaluate_portfolio_risk(
    portfolio: dict[str, Any],
    *,
    max_stop_risk_pct: float = 0.50,
) -> dict[str, Any]:
    """Approve only a fresh, complete portfolio below its aggregate stop-risk cap."""
    reasons: list[str] = []
    if not isfinite(max_stop_risk_pct) or max_stop_risk_pct <= 0:
        reasons.append("Portfolio stop-risk ceiling must be a finite positive percentage.")
    if portfolio.get("status") != "healthy":
        reasons.append("Portfolio telemetry is not healthy and complete.")
    equity = portfolio.get("account_equity")
    risk = portfolio.get("total_open_stop_risk")
    if (not isinstance(equity, (int, float)) or isinstance(equity, bool)
            or not isfinite(float(equity)) or equity <= 0):
        reasons.append("Account equity is missing or invalid.")
    if (not isinstance(risk, (int, float)) or isinstance(risk, bool)
            or not isfinite(float(risk)) or risk < 0):
        reasons.append("Aggregate open stop risk is missing or invalid.")
    risk_pct = None
    if not reasons:
        risk_pct = float(risk) / float(equity) * 100.0
        if risk_pct > max_stop_risk_pct:
            reasons.append("Aggregate open stop risk exceeds the configured portfolio ceiling.")
    return {
        "approved": not reasons,
        "status": portfolio.get("status", "unavailable"),
        "open_position_count": portfolio.get("open_position_count"),
        "account_equity": equity,
        "total_open_stop_risk": risk,
        "aggregate_stop_risk_pct": round(risk_pct, 6) if risk_pct is not None else None,
        "max_stop_risk_pct": max_stop_risk_pct,
        "reasons": reasons,
        "trading_enabled": False,
        "execution_submitted": False,
    }
