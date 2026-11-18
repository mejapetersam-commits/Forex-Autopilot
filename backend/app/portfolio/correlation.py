from math import isfinite, sqrt
from statistics import mean

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InstrumentReturns(BaseModel):
    """Historical periodic returns for one trading instrument."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    returns: list[float] = Field(min_length=2)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Instrument symbol cannot be empty.")
        return value

    @field_validator("returns")
    @classmethod
    def validate_returns(cls, values: list[float]) -> list[float]:
        if len(values) < 2:
            raise ValueError("At least two returns are required.")
        if any(not isfinite(value) for value in values):
            raise ValueError("Returns must contain only finite values.")
        return values


class CorrelationResult(BaseModel):
    """Correlation measurement between two instruments."""

    model_config = ConfigDict(extra="forbid")

    symbol_a: str
    symbol_b: str
    coefficient: float
    observations: int

    @field_validator("coefficient")
    @classmethod
    def validate_coefficient(cls, value: float) -> float:
        if not isfinite(value) or not -1.0 <= value <= 1.0:
            raise ValueError("Correlation coefficient must be between -1 and 1.")
        return value


class CorrelationCalculator:
    """
    Calculates Pearson correlation between paired historical returns.

    The caller must ensure both series use identical timestamps,
    intervals, chronological ordering, and return methodology.
    This calculator does not retrieve market data.
    """

    @staticmethod
    def calculate(
        instrument_a: InstrumentReturns,
        instrument_b: InstrumentReturns,
        minimum_observations: int = 30,
    ) -> CorrelationResult:
        if instrument_a.symbol == instrument_b.symbol:
            raise ValueError("Correlation requires two different instruments.")

        if minimum_observations < 2:
            raise ValueError("Minimum observations must be at least two.")

        returns_a = instrument_a.returns
        returns_b = instrument_b.returns

        if len(returns_a) != len(returns_b):
            raise ValueError("Instrument return series must have matching lengths.")

        observations = len(returns_a)
        if observations < minimum_observations:
            raise ValueError(
                f"At least {minimum_observations} observations are required."
            )

        mean_a = mean(returns_a)
        mean_b = mean(returns_b)
        deviations_a = [value - mean_a for value in returns_a]
        deviations_b = [value - mean_b for value in returns_b]

        sum_squares_a = sum(value ** 2 for value in deviations_a)
        sum_squares_b = sum(value ** 2 for value in deviations_b)

        if sum_squares_a == 0 or sum_squares_b == 0:
            raise ValueError(
                "Correlation cannot be calculated for a constant return series."
            )

        covariance_sum = sum(
            a * b for a, b in zip(deviations_a, deviations_b)
        )
        coefficient = covariance_sum / sqrt(sum_squares_a * sum_squares_b)
        coefficient = max(-1.0, min(1.0, coefficient))

        return CorrelationResult(
            symbol_a=instrument_a.symbol,
            symbol_b=instrument_b.symbol,
            coefficient=coefficient,
            observations=observations,
        )

    @staticmethod
    def is_strongly_correlated(
        result: CorrelationResult,
        threshold: float = 0.80,
    ) -> bool:
        if not isfinite(threshold) or not 0 < threshold <= 1:
            raise ValueError(
                "Correlation threshold must be greater than zero "
                "and no greater than one."
            )
        return abs(result.coefficient) >= threshold
