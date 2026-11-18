from datetime import datetime, timedelta
from math import isfinite

from app.portfolio.correlation import (
    CorrelationCalculator,
    CorrelationResult,
    InstrumentReturns,
)
from app.market_data.models import MarketDataSeries, utc_now


class MarketDataValidationError(ValueError):
    """Raised when market data is unsafe or unsuitable for analysis."""


class HistoricalReturnService:
    """Build aligned return series and correlations from completed candles."""

    @staticmethod
    def calculate_returns(series: MarketDataSeries) -> InstrumentReturns:
        closes = [bar.close for bar in series.bars]
        returns = [
            (current - previous) / previous
            for previous, current in zip(closes, closes[1:])
        ]
        if any(not isfinite(value) for value in returns):
            raise MarketDataValidationError(
                "Calculated returns contain a non-finite value."
            )
        return InstrumentReturns(symbol=series.symbol, returns=returns)

    @staticmethod
    def calculate_correlation(
        series_a: MarketDataSeries,
        series_b: MarketDataSeries,
        *,
        minimum_observations: int = 30,
        maximum_age: timedelta = timedelta(minutes=90),
        as_of: datetime | None = None,
    ) -> CorrelationResult:
        if series_a.symbol == series_b.symbol:
            raise MarketDataValidationError(
                "Correlation requires two different instruments."
            )
        if series_a.timeframe != series_b.timeframe:
            raise MarketDataValidationError(
                "Correlation series must use the same timeframe."
            )

        timestamps_a = [bar.timestamp for bar in series_a.bars]
        timestamps_b = [bar.timestamp for bar in series_b.bars]
        if timestamps_a != timestamps_b:
            raise MarketDataValidationError(
                "Correlation candles must have identical timestamps."
            )

        reference_time = as_of or utc_now()
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise MarketDataValidationError("Reference time must be timezone-aware.")
        reference_time = reference_time.astimezone(timestamps_a[-1].tzinfo)

        if maximum_age.total_seconds() <= 0:
            raise MarketDataValidationError("Maximum data age must be positive.")
        if minimum_observations < 2:
            raise MarketDataValidationError(
                "Minimum observations must be at least two."
            )

        latest_timestamp = timestamps_a[-1]
        age = reference_time - latest_timestamp
        if age < timedelta(0):
            raise MarketDataValidationError(
                "Market data contains a candle timestamp in the future."
            )
        if age > maximum_age:
            raise MarketDataValidationError(
                "Market data is stale; correlation calculation rejected."
            )

        returns_a = HistoricalReturnService.calculate_returns(series_a)
        returns_b = HistoricalReturnService.calculate_returns(series_b)

        return CorrelationCalculator.calculate(
            instrument_a=returns_a,
            instrument_b=returns_b,
            minimum_observations=minimum_observations,
        )
