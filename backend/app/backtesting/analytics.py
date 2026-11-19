"""Additional research analytics for completed historical backtest results.

These metrics describe simulated results only. They never authorize execution.
"""
from __future__ import annotations

from math import isfinite
from statistics import mean, median
from typing import Any


class BacktestAnalyticsError(ValueError):
    """Raised when a backtest result cannot be analysed safely."""


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BacktestAnalyticsError(f"{name} must be numeric.")
    result = float(value)
    if not isfinite(result):
        raise BacktestAnalyticsError(f"{name} must be finite.")
    return result


def analyse_backtest(result: dict[str, Any]) -> dict[str, Any]:
    """Build distribution, streak and drawdown diagnostics from engine trades."""
    if result.get("status") != "completed":
        raise BacktestAnalyticsError("Only completed backtests can be analysed.")
    trades = result.get("trades")
    if not isinstance(trades, list):
        raise BacktestAnalyticsError("Backtest trades must be a list.")

    pnls: list[float] = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            raise BacktestAnalyticsError(f"Trade {index} must be an object.")
        pnls.append(_finite_number(trade.get("net_pnl"), f"trade[{index}].net_pnl"))

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    breakeven = len(pnls) - len(wins) - len(losses)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    payoff = (mean(wins) / abs(mean(losses))) if wins and losses else None

    max_win_streak = max_loss_streak = win_streak = loss_streak = 0
    for pnl in pnls:
        if pnl > 0:
            win_streak += 1
            loss_streak = 0
        elif pnl < 0:
            loss_streak += 1
            win_streak = 0
        else:
            win_streak = loss_streak = 0
        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)

    drawdown = _finite_number(result.get("max_drawdown_pct", 0), "max_drawdown_pct")
    equity = _finite_number(result.get("final_equity"), "final_equity")
    initial = _finite_number(result.get("initial_equity"), "initial_equity")
    if initial <= 0:
        raise BacktestAnalyticsError("Initial equity must be positive.")

    return {
        "status": "completed",
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": breakeven,
        "median_trade_pnl": round(median(pnls), 2) if pnls else 0.0,
        "best_trade_pnl": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade_pnl": round(min(pnls), 2) if pnls else 0.0,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "payoff_ratio": round(payoff, 4) if payoff is not None else None,
        "max_consecutive_wins": max_win_streak,
        "max_consecutive_losses": max_loss_streak,
        "max_drawdown_pct": round(drawdown, 4),
        "net_profit": round(equity - initial, 2),
        "trade_pnls": pnls,
        "execution_enabled": False,
        "interpretation": "Historical simulation diagnostics; not a forecast or profitability guarantee.",
    }
