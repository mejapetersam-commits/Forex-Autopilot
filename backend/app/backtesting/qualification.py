"""Conservative research qualification; never authorizes broker execution."""

from __future__ import annotations

from math import isfinite
from typing import Any


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def evaluate_strategy_qualification(
    walk_forward: dict[str, Any],
    data_quality: dict[str, Any],
    *,
    minimum_oos_trades: int = 20,
    minimum_profit_factor: float = 1.2,
    maximum_drawdown_pct: float = 5.0,
) -> dict[str, Any]:
    """Qualify only when aggregate and individual OOS folds pass."""

    folds = walk_forward.get("folds") or []
    valid_folds = [
        fold for fold in folds
        if (fold.get("out_of_sample_metrics") or {}).get("status") == "completed"
    ]
    metrics = [
        fold.get("out_of_sample_metrics") or {}
        for fold in valid_folds
    ]

    total_trades = sum(
        int(item.get("total_trades") or 0)
        for item in metrics
        if _finite_number(item.get("total_trades"))
        and float(item.get("total_trades")) >= 0
    )

    reasons: list[str] = []

    if walk_forward.get("status") != "completed":
        reasons.append("Walk-forward validation has not completed.")

    if len(valid_folds) < 2:
        reasons.append("Both chronological out-of-sample folds must be valid.")

    if total_trades < minimum_oos_trades:
        reasons.append(
            f"At least {minimum_oos_trades} out-of-sample trades are required."
        )

    fold_checks = []
    for index, item in enumerate(metrics, 1):
        fold_reasons = []
        trades = item.get("total_trades")
        ret = item.get("return_pct")
        pf = item.get("profit_factor")
        realised_dd = item.get("max_drawdown_pct")
        mark_dd = item.get("mark_to_market_max_drawdown_pct")
        dd = item.get("qualification_drawdown_pct")
        expectancy = item.get("expectancy_per_trade")

        if not _finite_number(trades) or float(trades) < 1:
            fold_reasons.append("must contain at least one valid trade")
        if not _finite_number(ret) or float(ret) <= 0:
            fold_reasons.append("return must be positive")
        if not _finite_number(pf) or float(pf) < minimum_profit_factor:
            fold_reasons.append(
                f"profit factor must be at least {minimum_profit_factor:.2f}"
            )
        if not _finite_number(realised_dd):
            fold_reasons.append("realised drawdown is missing or invalid")
        elif float(realised_dd) < 0 or float(realised_dd) > maximum_drawdown_pct:
            fold_reasons.append(
                f"realised drawdown must be between 0 and {maximum_drawdown_pct:.2f}%"
            )
        if not _finite_number(mark_dd):
            fold_reasons.append("mark-to-market drawdown is missing or invalid")
        elif float(mark_dd) < 0 or float(mark_dd) > maximum_drawdown_pct:
            fold_reasons.append(
                f"mark-to-market drawdown must be between 0 and {maximum_drawdown_pct:.2f}%"
            )
        if not _finite_number(dd) or float(dd) < 0 or float(dd) > maximum_drawdown_pct:
            fold_reasons.append(
                f"conservative qualification drawdown must not exceed {maximum_drawdown_pct:.2f}%"
            )
        if not _finite_number(expectancy) or float(expectancy) <= 0:
            fold_reasons.append("expectancy per trade must be positive")

        fold_checks.append({
            "fold": index,
            "total_trades": trades,
            "return_pct": ret,
            "profit_factor": pf,
            "max_drawdown_pct": realised_dd,
            "mark_to_market_max_drawdown_pct": mark_dd,
            "qualification_drawdown_pct": dd,
            "expectancy_per_trade": expectancy,
            "passed": not fold_reasons,
            "reasons": fold_reasons,
        })
        if fold_reasons:
            reasons.append(
                f"Out-of-sample fold {index} failed: " + "; ".join(fold_reasons) + "."
            )

    summary = walk_forward.get("out_of_sample_summary") or {}
    mean_return = summary.get("mean_return_pct")
    mean_pf = summary.get("mean_profit_factor")
    worst_dd = summary.get("worst_qualification_drawdown_pct")

    if not _finite_number(mean_return) or float(mean_return) <= 0:
        reasons.append("Mean out-of-sample return must be positive.")
    if not _finite_number(mean_pf) or float(mean_pf) < minimum_profit_factor:
        reasons.append(
            f"Mean out-of-sample profit factor must be at least {minimum_profit_factor:.2f}."
        )
    if not _finite_number(worst_dd) or float(worst_dd) > maximum_drawdown_pct or float(worst_dd) < 0:
        reasons.append(
            f"Worst out-of-sample drawdown must not exceed {maximum_drawdown_pct:.2f}%."
        )

    issue_count = data_quality.get("issue_count")
    if issue_count is None:
        issue_count = len(data_quality.get("issues") or [])
    if data_quality.get("status") != "healthy" or issue_count:
        reasons.append("Candle quality must be healthy with no reported issues.")
    if data_quality.get("ready_for_research") is False:
        reasons.append("Historical candle coverage has not met the research minimum.")

    insufficient = (
        walk_forward.get("status") == "insufficient_data"
        or len(valid_folds) < 2
        or total_trades < minimum_oos_trades
    )
    status = (
        "insufficient_evidence" if insufficient
        else "under_review" if reasons
        else "eligible_for_demo_observation"
    )

    return {
        "status": status,
        "eligible_for_demo_observation": status == "eligible_for_demo_observation",
        "checks": {
            "valid_oos_folds": len(valid_folds),
            "oos_trades": total_trades,
            "mean_oos_return_pct": mean_return,
            "mean_oos_profit_factor": mean_pf,
            "worst_oos_drawdown_pct": worst_dd,
            "worst_oos_realised_drawdown_pct": summary.get("worst_drawdown_pct"),
            "individual_fold_checks": fold_checks,
            "data_quality": data_quality.get("status", "unknown"),
        },
        "thresholds": {
            "minimum_valid_folds": 2,
            "minimum_oos_trades": minimum_oos_trades,
            "minimum_trades_per_fold": 1,
            "minimum_mean_profit_factor": minimum_profit_factor,
            "minimum_fold_profit_factor": minimum_profit_factor,
            "maximum_worst_drawdown_pct": maximum_drawdown_pct,
            "require_positive_return_each_fold": True,
            "require_positive_expectancy_each_fold": True,
        },
        "reasons": reasons,
        "execution_enabled": False,
        "trading_enabled": False,
        "disclaimer": (
            "Research classification only. Demo observation still requires manual "
            "review and forward monitoring; this result never authorizes live trading."
        ),
    }
