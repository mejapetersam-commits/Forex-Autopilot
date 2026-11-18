"""Deterministic technical indicators for chronological, closed MT5 candles.

Input candles must be ordered oldest-to-newest and contain OHLC fields.
This module is intentionally pure: it performs no I/O and never creates trades.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Candle {field} must be numeric.") from exc
    if not isfinite(result) or result <= 0:
        raise ValueError(f"Candle {field} must be a finite positive number.")
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    output[period - 1] = current
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        output[index] = current
    return output


def _sma(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    running = sum(values[:period])
    output[period - 1] = running / period
    for index in range(period, len(values)):
        running += values[index] - values[index - period]
        output[index] = running / period
    return output


def _wilder(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period]) / period
    output[period - 1] = current
    for index in range(period, len(values)):
        current = ((current * (period - 1)) + values[index]) / period
        output[index] = current
    return output


def calculate_indicators(candles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Calculate SMA20/50, EMA20/50, RSI14, MACD(12,26,9), and ATR14.

    Candles are expected oldest-to-newest. The MT5 collector requests closed
    candles only. Insufficient history returns null indicator values rather
    than fabricated readings. At least 50 candles are needed for full trend.
    """
    rows = list(candles)
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    for row in rows:
        close = _number(row.get("close"), "close")
        high = _number(row.get("high"), "high")
        low = _number(row.get("low"), "low")
        open_price = _number(row.get("open"), "open")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Candle OHLC values are inconsistent.")
        closes.append(close)
        highs.append(high)
        lows.append(low)

    count = len(rows)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = _wilder(gains, 14)
    avg_loss = _wilder(losses, 14)
    rsi: float | None = None
    if avg_gain and avg_gain[-1] is not None and avg_loss[-1] is not None:
        gain, loss = avg_gain[-1], avg_loss[-1]
        if loss == 0:
            rsi = 100.0 if gain > 0 else 50.0
        else:
            rsi = 100.0 - (100.0 / (1.0 + gain / loss))

    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        if index == 0:
            true_ranges.append(high - low)
        else:
            previous_close = closes[index - 1]
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr_values = _wilder(true_ranges, 14)
    atr = atr_values[-1] if atr_values and atr_values[-1] is not None else None

    macd_line: list[float | None] = [
        (fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(ema12, ema26)
    ]
    valid_macd = [value for value in macd_line if value is not None]
    macd_signal_values = _ema(valid_macd, 9)
    macd = macd_line[-1] if macd_line else None
    macd_signal = macd_signal_values[-1] if macd_signal_values else None
    macd_histogram = (macd - macd_signal) if macd is not None and macd_signal is not None else None

    latest_close = closes[-1] if closes else None
    latest_ema20 = ema20[-1] if ema20 else None
    latest_ema50 = ema50[-1] if ema50 else None
    trend = "insufficient_data"
    if latest_close is not None and latest_ema20 is not None and latest_ema50 is not None:
        if latest_close > latest_ema20 > latest_ema50:
            trend = "bullish"
        elif latest_close < latest_ema20 < latest_ema50:
            trend = "bearish"
        else:
            trend = "mixed"

    momentum = "insufficient_data"
    if rsi is not None:
        momentum = "bullish" if rsi >= 55 else "bearish" if rsi <= 45 else "neutral"

    volatility = "insufficient_data"
    atr_percent: float | None = None
    if atr is not None and latest_close:
        atr_percent = (atr / latest_close) * 100.0
        volatility = "low" if atr_percent < 0.25 else "normal" if atr_percent < 0.75 else "high"

    assessment = "insufficient_data"
    if trend != "insufficient_data" and momentum != "insufficient_data":
        assessment = trend if trend == momentum else "mixed"

    def last(values: list[float | None]) -> float | None:
        value = values[-1] if values else None
        return round(value, 8) if value is not None else None

    return {
        "candles_used": count,
        "latest_close": round(latest_close, 8) if latest_close is not None else None,
        "sma_20": last(sma20),
        "sma_50": last(sma50),
        "ema_20": last(ema20),
        "ema_50": last(ema50),
        "rsi_14": round(rsi, 4) if rsi is not None else None,
        "macd": round(macd, 8) if macd is not None else None,
        "macd_signal": round(macd_signal, 8) if macd_signal is not None else None,
        "macd_histogram": round(macd_histogram, 8) if macd_histogram is not None else None,
        "atr_14": round(atr, 8) if atr is not None else None,
        "atr_percent": round(atr_percent, 4) if atr_percent is not None else None,
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "assessment": assessment,
        "execution_enabled": False,
    }
