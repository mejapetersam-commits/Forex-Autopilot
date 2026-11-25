"""Rule-based signal research engine using completed historical candles only.

This module produces a candidate signal and reference levels. It never places,
modifies, or closes broker orders. The default rules are hypotheses requiring
out-of-sample backtesting and forward-demo validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from app.market_data.indicators import calculate_indicators


@dataclass(frozen=True)
class StrategyConfig:
    minimum_candles: int = 60
    long_rsi_min: float = 55.0
    short_rsi_max: float = 45.0
    atr_stop_multiple: float = 1.5
    reward_risk_ratio: float = 2.0

    def __post_init__(self) -> None:
        numeric_parameters = (
            self.long_rsi_min,
            self.short_rsi_max,
            self.atr_stop_multiple,
            self.reward_risk_ratio,
        )
        if not all(isfinite(float(value)) for value in numeric_parameters):
            raise ValueError("Strategy parameters must be finite numbers.")
        if self.minimum_candles < 50:
            raise ValueError("minimum_candles cannot be below 50.")
        if not 50 < self.long_rsi_min <= 100:
            raise ValueError("long_rsi_min must be between 50 and 100.")
        if not 0 <= self.short_rsi_max < 50:
            raise ValueError("short_rsi_max must be between 0 and 50.")
        if self.atr_stop_multiple <= 0 or self.reward_risk_ratio <= 0:
            raise ValueError("ATR stop and reward/risk multipliers must be positive.")


def evaluate_signal(
    candles: Iterable[dict[str, Any]],
    config: StrategyConfig | None = None,
) -> dict[str, Any]:
    """Evaluate EMA trend + RSI + MACD alignment and ATR-based reference levels."""
    settings = config or StrategyConfig()
    rows = list(candles)

    if len(rows) < settings.minimum_candles:
        return {
            "signal": "insufficient_data",
            "candles_used": len(rows),
            "minimum_candles": settings.minimum_candles,
            "reason": "Not enough completed candles for the configured indicators.",
            "execution_enabled": False,
            "research_status": "unvalidated_hypothesis",
        }

    metrics = calculate_indicators(rows)
    required = ("latest_close", "ema_20", "ema_50", "rsi_14",
                "macd_histogram", "atr_14")
    if any(metrics.get(key) is None for key in required):
        signal = "insufficient_data"
        reason = "One or more required indicators are unavailable."
    else:
        close = metrics["latest_close"]
        ema20 = metrics["ema_20"]
        ema50 = metrics["ema_50"]
        rsi = metrics["rsi_14"]
        macd_hist = metrics["macd_histogram"]

        long_aligned = close > ema20 > ema50
        short_aligned = close < ema20 < ema50
        long_confirmed = rsi >= settings.long_rsi_min and macd_hist > 0
        short_confirmed = rsi <= settings.short_rsi_max and macd_hist < 0

        if long_aligned and long_confirmed:
            signal, reason = "buy", "Bullish EMA structure confirmed by RSI and MACD."
        elif short_aligned and short_confirmed:
            signal, reason = "sell", "Bearish EMA structure confirmed by RSI and MACD."
        else:
            signal, reason = "flat", "Trend and momentum conditions are not fully aligned."

    result: dict[str, Any] = {
        "signal": signal,
        "candles_used": len(rows),
        "reason": reason,
        "indicators": metrics,
        "strategy": {
            "name": "EMA trend + RSI + MACD confirmation",
            "version": "0.1.0",
            "minimum_candles": settings.minimum_candles,
            "long_rsi_min": settings.long_rsi_min,
            "short_rsi_max": settings.short_rsi_max,
            "atr_stop_multiple": settings.atr_stop_multiple,
            "reward_risk_ratio": settings.reward_risk_ratio,
        },
        "execution_enabled": False,
        "research_status": "unvalidated_hypothesis",
    }

    if signal in {"buy", "sell"}:
        close = float(metrics["latest_close"])
        stop_distance = float(metrics["atr_14"]) * settings.atr_stop_multiple
        result["candidate_levels"] = {
            "reference_close": close,
            "stop_distance_price": round(stop_distance, 8),
            "stop_loss": round(
                close - stop_distance if signal == "buy" else close + stop_distance, 8
            ),
            "take_profit": round(
                close + stop_distance * settings.reward_risk_ratio
                if signal == "buy"
                else close - stop_distance * settings.reward_risk_ratio,
                8,
            ),
            "reward_risk_ratio": settings.reward_risk_ratio,
            "note": "Reference levels only; execution price, spread, slippage and broker stops must be checked separately.",
        }
    return result
