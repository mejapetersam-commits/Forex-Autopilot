"""Conservative research qualification; never authorizes broker execution."""
from __future__ import annotations

from typing import Any


def evaluate_strategy_qualification(
    walk_forward: dict[str, Any],
    data_quality: dict[str, Any],
    *,
    minimum_oos_trades: int = 20,
    minimum_profit_factor: float = 1.2,
    maximum_drawdown_pct: float = 5.0,
) -> dict[str, Any]:
    """Classify evidence quality using untouched walk-forward validation folds."""
    summary = walk_forward.get("out_of_sample_summary") or {}
    folds = walk_forward.get("folds") or []
    valid_folds = [
        fold for fold in folds
        if (fold.get("out_of_sample_metrics") or {}).get("status") == "completed"
    ]
    total_trades = int(summary.get("total_trades") or 0)
    mean_return = summary.get("mean_return_pct")
    mean_pf = summary.get("mean_profit_factor")
    worst_dd = summary.get("worst_drawdown_pct")
    reasons: list[str] = []

    if walk_forward.get("status") != "completed":
        reasons.append("Walk-forward validation has not completed.")
    if len(valid_folds) < 2:
        reasons.append("Both chronological out-of-sample folds must be valid.")
    if total_trades < minimum_oos_trades:
        reasons.append(f"At least {minimum_oos_trades} out-of-sample trades are required.")
    if mean_return is None or float(mean_return) <= 0:
        reasons.append("Mean out-of-sample return must be positive.")
    if mean_pf is None or float(mean_pf) < minimum_profit_factor:
        reasons.append(f"Mean out-of-sample profit factor must be at least {minimum_profit_factor:.2f}.")
    if worst_dd is None or float(worst_dd) > maximum_drawdown_pct:
        reasons.append(f"Worst out-of-sample drawdown must not exceed {maximum_drawdown_pct:.2f}%.")
    if data_quality.get("status") != "healthy" or data_quality.get("issue_count", 0):
        reasons.append("Candle quality must be healthy with no reported issues.")

    if walk_forward.get("status") == "insufficient_data" or len(valid_folds) < 2 or total_trades < minimum_oos_trades:
        status = "insufficient_evidence"
    elif reasons:
        status = "under_review"
    else:
        status = "eligible_for_demo_observation"

    return {
        "status": status,
        "eligible_for_demo_observation": status == "eligible_for_demo_observation",
        "checks": {
            "valid_oos_folds": len(valid_folds),
            "oos_trades": total_trades,
            "mean_oos_return_pct": mean_return,
            "mean_oos_profit_factor": mean_pf,
            "worst_oos_drawdown_pct": worst_dd,
            "data_quality": data_quality.get("status", "unknown"),
        },
        "thresholds": {
            "minimum_valid_folds": 2,
            "minimum_oos_trades": minimum_oos_trades,
            "minimum_mean_profit_factor": minimum_profit_factor,
            "maximum_worst_drawdown_pct": maximum_drawdown_pct,
        },
        "reasons": reasons,
        "execution_enabled": False,
        "trading_enabled": False,
        "disclaimer": "Research classification only. Demo observation still requires manual review and forward monitoring; this result never authorizes live trading.",
    }
