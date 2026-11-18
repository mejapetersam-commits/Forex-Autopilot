from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.market_data.models import MarketDataSeries, PriceBar
from app.market_data.returns import (
    HistoricalReturnService,
    MarketDataValidationError,
)


BASE = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


def make_series(symbol, closes, *, timestamps=None, timeframe="H1"):
    if timestamps is None:
        timestamps = [BASE + timedelta(hours=index) for index in range(len(closes))]
    bars = []
    previous = closes[0]
    for timestamp, close in zip(timestamps, closes):
        high = max(previous, close) * 1.001
        low = min(previous, close) * 0.999
        bars.append(
            PriceBar(
                timestamp=timestamp,
                open=previous,
                high=high,
                low=low,
                close=close,
                volume=100,
            )
        )
        previous = close
    return MarketDataSeries(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
    )


def test_price_bar_requires_timezone_aware_timestamp():
    with pytest.raises(ValidationError, match="timezone"):
        PriceBar(
            timestamp=datetime(2026, 11, 18, 10, 0),
            open=1.1,
            high=1.2,
            low=1.0,
            close=1.15,
        )


def test_price_bar_rejects_invalid_ohlc_relationships():
    with pytest.raises(ValidationError, match="Bar high"):
        PriceBar(
            timestamp=BASE,
            open=1.1,
            high=1.05,
            low=1.0,
            close=1.02,
        )


def test_series_normalizes_symbol_and_rejects_duplicate_timestamps():
    with pytest.raises(ValidationError, match="unique"):
        MarketDataSeries(
            symbol=" eurusd ",
            timeframe="H1",
            bars=[
                PriceBar(timestamp=BASE, open=1.1, high=1.2, low=1.0, close=1.15),
                PriceBar(timestamp=BASE, open=1.1, high=1.2, low=1.0, close=1.16),
            ],
        )


def test_calculates_returns_from_consecutive_closes():
    series = make_series("eurusd", [1.0, 1.1, 1.21])
    result = HistoricalReturnService.calculate_returns(series)

    assert result.symbol == "EURUSD"
    assert result.returns == pytest.approx([0.10, 0.10])


def test_calculates_correlation_for_aligned_fresh_series():
    closes_a = [100 + index + (index % 3) for index in range(40)]
    closes_b = [200 + 2 * index + (index % 3) * 2 for index in range(40)]
    a = make_series("EURUSD", closes_a)
    b = make_series("GBPUSD", closes_b)

    result = HistoricalReturnService.calculate_correlation(
        a,
        b,
        minimum_observations=30,
        as_of=BASE + timedelta(hours=39),
    )

    assert result.symbol_a == "EURUSD"
    assert result.symbol_b == "GBPUSD"
    assert result.observations == 39
    assert result.coefficient == pytest.approx(1.0)


def test_rejects_misaligned_timestamps():
    a = make_series("EURUSD", [1.0 + index * 0.01 for index in range(35)])
    shifted = [BASE + timedelta(hours=index, minutes=5) for index in range(35)]
    b = make_series(
        "GBPUSD",
        [2.0 + index * 0.01 for index in range(35)],
        timestamps=shifted,
    )

    with pytest.raises(MarketDataValidationError, match="identical timestamps"):
        HistoricalReturnService.calculate_correlation(
            a, b, as_of=shifted[-1]
        )


def test_rejects_stale_market_data():
    closes = [1.0 + index * 0.001 for index in range(35)]
    a = make_series("EURUSD", closes)
    b = make_series("GBPUSD", closes)

    with pytest.raises(MarketDataValidationError, match="stale"):
        HistoricalReturnService.calculate_correlation(
            a,
            b,
            maximum_age=timedelta(minutes=30),
            as_of=BASE + timedelta(hours=34, minutes=31),
        )


def test_rejects_future_market_data():
    closes = [1.0 + index * 0.001 for index in range(35)]
    a = make_series("EURUSD", closes)
    b = make_series("GBPUSD", closes)

    with pytest.raises(MarketDataValidationError, match="future"):
        HistoricalReturnService.calculate_correlation(
            a,
            b,
            as_of=BASE + timedelta(hours=33),
        )


def test_rejects_different_timeframes():
    closes = [1.0 + index * 0.001 for index in range(35)]
    a = make_series("EURUSD", closes, timeframe="H1")
    b = make_series("GBPUSD", closes, timeframe="M15")

    with pytest.raises(MarketDataValidationError, match="same timeframe"):
        HistoricalReturnService.calculate_correlation(
            a, b, as_of=BASE + timedelta(hours=34)
        )


def test_rejects_insufficient_history():
    closes = [1.0 + index * 0.001 for index in range(20)]
    a = make_series("EURUSD", closes)
    b = make_series("GBPUSD", closes)

    with pytest.raises(ValueError, match="observations"):
        HistoricalReturnService.calculate_correlation(
            a,
            b,
            minimum_observations=30,
            as_of=BASE + timedelta(hours=19),
        )
