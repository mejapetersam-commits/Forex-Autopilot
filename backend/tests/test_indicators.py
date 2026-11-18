import pytest

from app.market_data.indicators import calculate_indicators


def candles(values):
    return [
        {"open": value - 0.1, "high": value + 0.2, "low": value - 0.2, "close": value}
        for value in values
    ]


def test_insufficient_history_returns_null_indicators_without_guessing():
    result = calculate_indicators(candles([1.0 + i * 0.001 for i in range(10)]))
    assert result["candles_used"] == 10
    assert result["sma_20"] is None
    assert result["rsi_14"] is None
    assert result["assessment"] == "insufficient_data"
    assert result["execution_enabled"] is False


def test_full_indicator_set_and_uptrend_classification():
    result = calculate_indicators(candles([1.0 + i * 0.001 for i in range(80)]))
    assert result["sma_20"] is not None
    assert result["sma_50"] is not None
    assert result["ema_20"] is not None
    assert result["ema_50"] is not None
    assert result["rsi_14"] == 100.0
    assert result["macd"] is not None
    assert result["macd_signal"] is not None
    assert result["atr_14"] > 0
    assert result["trend"] == "bullish"
    assert result["momentum"] == "bullish"
    assert result["assessment"] == "bullish"
    assert result["execution_enabled"] is False


def test_downtrend_classification():
    result = calculate_indicators(candles([2.0 - i * 0.001 for i in range(80)]))
    assert result["trend"] == "bearish"
    assert result["momentum"] == "bearish"
    assert result["assessment"] == "bearish"


def test_rejects_invalid_ohlc():
    bad = [{"open": 1.0, "high": 0.9, "low": 0.8, "close": 0.85}]
    with pytest.raises(ValueError, match="inconsistent"):
        calculate_indicators(bad)


def test_rejects_non_finite_prices():
    bad = [{"open": 1.0, "high": float("inf"), "low": 0.8, "close": 0.9}]
    with pytest.raises(ValueError, match="finite positive"):
        calculate_indicators(bad)
