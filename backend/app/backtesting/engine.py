"""Deterministic OHLC backtester with conservative intrabar execution assumptions.

Signals are evaluated only on completed candles. Entries occur at the next bar's
open. If stop and target are both touched in one bar, stop is assumed first.
This is research tooling, not a broker execution module.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite, sqrt
from statistics import mean, pstdev
from typing import Any, Iterable

from app.strategy.engine import StrategyConfig, evaluate_signal


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: float = 10_000.0
    risk_per_trade_pct: float = 0.25
    pip_size: float = 0.0001
    pip_value_per_lot: float = 10.0
    spread_pips: float = 1.0
    slippage_pips_per_side: float = 0.2
    commission_per_lot_per_side: float = 3.5
    lot_min: float = 0.01
    lot_max: float = 100.0
    lot_step: float = 0.01
    minimum_candles: int = 60
    atr_stop_multiple: float = 1.5
    reward_risk_ratio: float = 2.0

    def __post_init__(self) -> None:
        positive = ("initial_equity", "risk_per_trade_pct", "pip_size",
                    "pip_value_per_lot", "lot_min", "lot_max", "lot_step",
                    "atr_stop_multiple", "reward_risk_ratio")
        for name in positive:
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero.")
        nonnegative = ("spread_pips", "slippage_pips_per_side",
                       "commission_per_lot_per_side")
        for name in nonnegative:
            value = float(getattr(self, name))
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} cannot be negative.")
        if self.risk_per_trade_pct > 1.0:
            raise ValueError("Backtest risk per trade cannot exceed 1%.")
        if self.lot_max < self.lot_min or self.minimum_candles < 60:
            raise ValueError("Invalid lot limits or insufficient minimum history.")


def _validate_candles(rows: list[dict[str, Any]]) -> None:
    previous_time = None
    for index, row in enumerate(rows):
        try:
            values = [float(row[key]) for key in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Candle {index} has invalid OHLC values.") from exc
        if not all(isfinite(value) and value > 0 for value in values):
            raise ValueError(f"Candle {index} OHLC values must be positive and finite.")
        op, high, low, close = values
        if high < max(op, low, close) or low > min(op, high, close):
            raise ValueError(f"Candle {index} has inconsistent OHLC values.")
        timestamp = row.get("opened_at")
        if timestamp is not None:
            if previous_time is not None and timestamp <= previous_time:
                raise ValueError("Candles must have strictly increasing opened_at timestamps.")
            previous_time = timestamp


def run_backtest(
    candles: Iterable[dict[str, Any]],
    config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """Run a single-position, next-open, closed-candle strategy simulation."""
    settings = config or BacktestConfig()
    rows = list(candles)
    _validate_candles(rows)
    if len(rows) < settings.minimum_candles + 1:
        return {
            "status": "insufficient_data",
            "candles_tested": len(rows),
            "minimum_required": settings.minimum_candles + 1,
            "trades": [],
            "execution_enabled": False,
        }

    equity = settings.initial_equity
    peak_equity = equity
    max_drawdown_pct = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve = [equity]
    warmup = settings.minimum_candles
    spread = settings.spread_pips * settings.pip_size
    slippage = settings.slippage_pips_per_side * settings.pip_size
    costs_pips = settings.spread_pips + 2 * settings.slippage_pips_per_side
    position = None

    for index in range(warmup, len(rows)):
        bar = rows[index]
        op, high, low, close = (float(bar[k]) for k in ("open", "high", "low", "close"))

        if position is None:
            candidate = evaluate_signal(
                rows[:index],
                StrategyConfig(
                    minimum_candles=settings.minimum_candles,
                    atr_stop_multiple=settings.atr_stop_multiple,
                    reward_risk_ratio=settings.reward_risk_ratio,
                ),
            )
            side = candidate["signal"]
            levels = candidate.get("candidate_levels")
            if side not in ("buy", "sell") or not levels:
                continue

            entry_mid = op
            entry = entry_mid + (spread / 2 + slippage) if side == "buy" else entry_mid - (spread / 2 + slippage)
            stop = float(levels["stop_loss"])
            target = float(levels["take_profit"])
            stop_pips = abs(entry - stop) / settings.pip_size
            risk_budget = equity * settings.risk_per_trade_pct / 100
            risk_per_lot = (
                (stop_pips + costs_pips) * settings.pip_value_per_lot
                + 2 * settings.commission_per_lot_per_side
            )
            raw_lots = risk_budget / risk_per_lot if risk_per_lot > 0 else 0
            lots = floor(min(raw_lots, settings.lot_max) / settings.lot_step + 1e-10) * settings.lot_step
            lots = round(lots, 8)
            if lots < settings.lot_min:
                continue
            position = {
                "side": side, "entry": entry, "entry_mid": entry_mid,
                "stop": stop, "target": target, "lots": lots,
                "entry_index": index, "entry_time": bar.get("opened_at"),
                "risk_budget": risk_budget,
            }

        if position is None:
            continue

        side = position["side"]
        stop_hit = low <= position["stop"] if side == "buy" else high >= position["stop"]
        target_hit = high >= position["target"] if side == "buy" else low <= position["target"]
        exit_reason = None
        exit_mid = None

        if stop_hit:
            exit_reason = "stop_loss"
            # Respect adverse gaps through the stop; otherwise assume stop price.
            exit_mid = min(op, position["stop"]) if side == "buy" else max(op, position["stop"])
        elif target_hit:
            exit_reason = "take_profit"
            # Conservative target fill: no favourable gap improvement.
            exit_mid = position["target"]
        elif index == len(rows) - 1:
            exit_reason = "end_of_data"
            exit_mid = close

        if exit_reason is None:
            continue

        exit_price = exit_mid - (spread / 2 + slippage) if side == "buy" else exit_mid + (spread / 2 + slippage)
        price_delta = exit_price - position["entry"] if side == "buy" else position["entry"] - exit_price
        gross_pips = price_delta / settings.pip_size
        gross_pnl = gross_pips * settings.pip_value_per_lot * position["lots"]
        commission = 2 * settings.commission_per_lot_per_side * position["lots"]
        net_pnl = gross_pnl - commission
        equity_before = equity
        equity += net_pnl
        peak_equity = max(peak_equity, equity)
        drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity else 0
        max_drawdown_pct = max(max_drawdown_pct, drawdown)
        trades.append({
            "side": side,
            "entry_time": position["entry_time"],
            "exit_time": bar.get("opened_at"),
            "entry_index": position["entry_index"],
            "exit_index": index,
            "entry_price": round(position["entry"], 8),
            "exit_price": round(exit_price, 8),
            "stop_loss": round(position["stop"], 8),
            "take_profit": round(position["target"], 8),
            "lots": position["lots"],
            "exit_reason": exit_reason,
            "gross_pips": round(gross_pips, 2),
            "gross_pnl": round(gross_pnl, 2),
            "commission": round(commission, 2),
            "net_pnl": round(net_pnl, 2),
            "equity_before": round(equity_before, 2),
            "equity_after": round(equity, 2),
            "risk_budget": round(position["risk_budget"], 2),
        })
        equity_curve.append(equity)
        position = None

    pnls = [trade["net_pnl"] for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    returns = [
        (current - previous) / previous
        for previous, current in zip(equity_curve, equity_curve[1:])
        if previous > 0
    ]
    avg_return = mean(returns) if returns else 0.0
    return_volatility = pstdev(returns) if len(returns) > 1 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)

    return {
        "status": "completed",
        "candles_tested": len(rows),
        "initial_equity": round(settings.initial_equity, 2),
        "final_equity": round(equity, 2),
        "net_profit": round(equity - settings.initial_equity, 2),
        "return_pct": round((equity / settings.initial_equity - 1) * 100, 4),
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(profit_factor, 4) if isfinite(profit_factor) else None,
        "expectancy_per_trade": round(mean(pnls), 2) if pnls else 0.0,
        "average_win": round(mean(wins), 2) if wins else 0.0,
        "average_loss": round(mean(losses), 2) if losses else 0.0,
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "trade_return_volatility": round(return_volatility, 6),
        "trade_return_sharpe_like": round((avg_return / return_volatility) * sqrt(len(returns)), 4) if return_volatility else None,
        "assumptions": {
            "signal_timing": "completed candle; entry at next candle open",
            "intrabar_conflict": "stop loss assumed first if stop and target both touched",
            "spread_pips": settings.spread_pips,
            "slippage_pips_per_side": settings.slippage_pips_per_side,
            "commission_per_lot_per_side": settings.commission_per_lot_per_side,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "single_position": True,
            "compounding": True,
            "data_quality": "OHLC-only; no tick-level execution simulation",
        },
        "trades": trades,
        "execution_enabled": False,
        "research_status": "historical_simulation_not_a_profitability_guarantee",
    }
