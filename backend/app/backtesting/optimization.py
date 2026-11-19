"""Bounded grid-search and chronological walk-forward evaluation.

The optimizer never uses future candles to select parameters for a past fold.
It ranks candidates on each training window and reports untouched subsequent
validation windows separately. It is deliberately capped to control runtime.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import product
from typing import Any, Iterable

from app.backtesting.engine import BacktestConfig, run_backtest


def _score(result: dict[str, Any], minimum_trades: int) -> float:
    if result.get("status") != "completed" or result.get("total_trades", 0) < minimum_trades:
        return -1_000_000.0
    profit_factor = result.get("profit_factor")
    if profit_factor is None:
        profit_factor = 0.0
    # Reward net return, penalise drawdown and weak trade samples.
    return (
        float(result.get("return_pct", 0.0))
        + min(float(profit_factor), 3.0) * 0.5
        - float(result.get("max_drawdown_pct", 100.0)) * 0.75
    )


def optimize_walk_forward(
    candles: Iterable[dict[str, Any]],
    base_config: BacktestConfig,
    *,
    minimum_trades: int = 5,
) -> dict[str, Any]:
    """Tune on expanding historical windows; report the next unseen window."""
    rows = list(candles)
    if len(rows) < 400:
        return {
            "status": "insufficient_data",
            "candles_available": len(rows),
            "minimum_required": 400,
            "execution_enabled": False,
        }
    if minimum_trades < 1 or minimum_trades > 100:
        raise ValueError("minimum_trades must be between 1 and 100.")

    # Eight candidates: bounded enough for the API and broad enough to compare
    # stop distance, reward/risk and momentum confirmation.
    candidates = [
        replace(
            base_config,
            atr_stop_multiple=atr,
            reward_risk_ratio=rr,
            long_rsi_min=long_rsi,
            short_rsi_max=short_rsi,
        )
        for atr, rr, long_rsi, short_rsi in product(
            (1.25, 1.75), (1.5, 2.0), (55.0, 60.0), (40.0, 45.0)
        )
    ]

    # Two expanding folds. Each test segment is strictly later than its
    # training segment; a 60-candle warm-up is included before OOS scoring.
    first_cut = int(len(rows) * 0.55)
    second_cut = int(len(rows) * 0.75)
    folds = [
        (rows[:first_cut], rows[max(0, first_cut - 60):second_cut]),
        (rows[:second_cut], rows[max(0, second_cut - 60):]),
    ]
    fold_results = []
    for fold_number, (training, validation_with_warmup) in enumerate(folds, 1):
        ranked = []
        for config in candidates:
            training_result = run_backtest(training, config)
            ranked.append({
                "config": config,
                "training_result": training_result,
                "score": _score(training_result, minimum_trades),
            })
        ranked.sort(key=lambda item: item["score"], reverse=True)
        best = ranked[0]
        validation_result = run_backtest(validation_with_warmup, best["config"])
        fold_results.append({
            "fold": fold_number,
            "training_candles": len(training),
            "validation_candles_including_warmup": len(validation_with_warmup),
            "selected_parameters": {
                "atr_stop_multiple": best["config"].atr_stop_multiple,
                "reward_risk_ratio": best["config"].reward_risk_ratio,
                "long_rsi_min": best["config"].long_rsi_min,
                "short_rsi_max": best["config"].short_rsi_max,
            },
            "training_metrics": {
                key: best["training_result"].get(key)
                for key in ("total_trades", "return_pct", "profit_factor", "max_drawdown_pct")
            },
            "out_of_sample_metrics": {
                key: validation_result.get(key)
                for key in ("status", "total_trades", "return_pct", "profit_factor",
                            "max_drawdown_pct", "expectancy_per_trade", "win_rate_pct")
            },
        })

    valid_oos = [
        fold["out_of_sample_metrics"]
        for fold in fold_results
        if fold["out_of_sample_metrics"].get("status") == "completed"
    ]
    return {
        "status": "completed",
        "candles_available": len(rows),
        "candidate_count_per_fold": len(candidates),
        "fold_count": len(fold_results),
        "folds": fold_results,
        "out_of_sample_summary": {
            "valid_folds": len(valid_oos),
            "total_trades": sum(item.get("total_trades", 0) or 0 for item in valid_oos),
            "mean_return_pct": round(
                sum(item.get("return_pct", 0.0) or 0.0 for item in valid_oos) / len(valid_oos), 4
            ) if valid_oos else None,
            "mean_profit_factor": round(
                sum(item.get("profit_factor", 0.0) or 0.0 for item in valid_oos) / len(valid_oos), 4
            ) if valid_oos else None,
            "worst_drawdown_pct": max(
                (item.get("max_drawdown_pct", 0.0) or 0.0 for item in valid_oos), default=None
            ),
        },
        "methodology": {
            "selection": "bounded grid search using training data only",
            "validation": "two chronological expanding-window out-of-sample folds",
            "candidate_count": len(candidates),
            "minimum_training_trades_for_ranking": minimum_trades,
            "data_scope": "OHLC candles; spread, slippage and commission are charged by backtester",
            "warning": "Small samples, OHLC execution assumptions and parameter search can still overfit. Require more history and forward-demo confirmation.",
        },
        "execution_enabled": False,
        "research_status": "parameter_screening_not_live_validation",
    }
