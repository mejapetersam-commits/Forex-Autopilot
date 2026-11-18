import pytest
from pydantic import ValidationError

from app.portfolio.correlation import (
    CorrelationCalculator,
    InstrumentReturns,
)


def make_returns(symbol, values):
    return InstrumentReturns(symbol=symbol, returns=values)


def test_perfect_positive_correlation():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", [1, 2, 3, 4, 5]),
        make_returns("GBPUSD", [2, 4, 6, 8, 10]),
        minimum_observations=5,
    )
    assert result.coefficient == pytest.approx(1.0)


def test_perfect_negative_correlation():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", [1, 2, 3, 4, 5]),
        make_returns("USDCHF", [-1, -2, -3, -4, -5]),
        minimum_observations=5,
    )
    assert result.coefficient == pytest.approx(-1.0)


def test_strong_positive_correlation_is_detected():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", list(range(1, 31))),
        make_returns("GBPUSD", list(range(2, 62, 2))),
        minimum_observations=30,
    )
    assert CorrelationCalculator.is_strongly_correlated(result, threshold=0.80)


def test_strong_negative_correlation_is_detected():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", list(range(1, 31))),
        make_returns("USDCHF", list(range(-1, -61, -2))),
        minimum_observations=30,
    )
    assert CorrelationCalculator.is_strongly_correlated(result, threshold=0.80)


def test_weak_correlation_is_not_detected():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", [1, 2, 3, 4, 5, 6]),
        make_returns("GBPUSD", [1, -1, -1, 1, 1, -1]),
        minimum_observations=6,
    )
    assert abs(result.coefficient) < 0.80
    assert not CorrelationCalculator.is_strongly_correlated(
        result,
        threshold=0.80,
    )


def test_insufficient_observations_are_rejected():
    with pytest.raises(ValueError):
        CorrelationCalculator.calculate(
            make_returns("EURUSD", [1, 2, 3]),
            make_returns("GBPUSD", [2, 4, 6]),
            minimum_observations=30,
        )


def test_mismatched_return_lengths_are_rejected():
    with pytest.raises(ValueError):
        CorrelationCalculator.calculate(
            make_returns("EURUSD", [1, 2, 3]),
            make_returns("GBPUSD", [2, 4]),
            minimum_observations=2,
        )


def test_constant_returns_are_rejected():
    with pytest.raises(ValueError):
        CorrelationCalculator.calculate(
            make_returns("EURUSD", [1, 1, 1, 1]),
            make_returns("GBPUSD", [2, 3, 4, 5]),
            minimum_observations=4,
        )


def test_same_instrument_is_rejected():
    with pytest.raises(ValueError):
        CorrelationCalculator.calculate(
            make_returns("EURUSD", [1, 2, 3]),
            make_returns("EURUSD", [2, 4, 6]),
            minimum_observations=3,
        )


def test_non_finite_returns_are_rejected():
    with pytest.raises(ValidationError):
        make_returns("EURUSD", [1.0, float("nan"), 3.0])


def test_invalid_threshold_is_rejected():
    result = CorrelationCalculator.calculate(
        make_returns("EURUSD", [1, 2, 3, 4]),
        make_returns("GBPUSD", [2, 4, 6, 8]),
        minimum_observations=4,
    )
    with pytest.raises(ValueError):
        CorrelationCalculator.is_strongly_correlated(
            result,
            threshold=1.5,
        )
