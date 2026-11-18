
import pytest
from pydantic import ValidationError

from app.portfolio.currency_exposure import (
    CurrencyExposure,
    CurrencyExposureCalculator,
)


def test_aggregates_exposure_for_each_currency():
    exposures = [
        CurrencyExposure(
            ticket="1001",
            currency="USD",
            amount_account_currency=-5000,
        ),
        CurrencyExposure(
            ticket="1002",
            currency="USD",
            amount_account_currency=-3000,
        ),
        CurrencyExposure(
            ticket="1003",
            currency="EUR",
            amount_account_currency=4000,
        ),
    ]

    result = CurrencyExposureCalculator.aggregate(
        exposures=exposures,
        current_equity=10000,
    )

    assert result["USD"].net_exposure == -8000
    assert result["USD"].gross_exposure == 8000
    assert result["EUR"].net_exposure == 4000
    assert result["EUR"].gross_exposure == 4000


def test_opposing_positions_do_not_hide_gross_exposure():
    exposures = [
        CurrencyExposure(
            ticket="1001",
            currency="USD",
            amount_account_currency=10000,
        ),
        CurrencyExposure(
            ticket="1002",
            currency="USD",
            amount_account_currency=-10000,
        ),
    ]

    result = CurrencyExposureCalculator.aggregate(
        exposures=exposures,
        current_equity=10000,
    )

    assert result["USD"].net_exposure == 0
    assert result["USD"].gross_exposure == 20000
    assert result["USD"].net_exposure_pct_equity == 0
    assert result["USD"].gross_exposure_pct_equity == 200


def test_calculates_exposure_as_percentage_of_equity():
    exposures = [
        CurrencyExposure(
            ticket="1001",
            currency="EUR",
            amount_account_currency=2500,
        ),
    ]

    result = CurrencyExposureCalculator.aggregate(
        exposures=exposures,
        current_equity=10000,
    )

    assert result["EUR"].net_exposure_pct_equity == 25
    assert result["EUR"].gross_exposure_pct_equity == 25


def test_empty_exposure_list_returns_empty_result():
    result = CurrencyExposureCalculator.aggregate(
        exposures=[],
        current_equity=10000,
    )

    assert result == {}


def test_rejects_invalid_currency_code():
    with pytest.raises(ValidationError):
        CurrencyExposure(
            ticket="1001",
            currency="US",
            amount_account_currency=1000,
        )


def test_rejects_lowercase_currency_code():
    with pytest.raises(ValidationError):
        CurrencyExposure(
            ticket="1001",
            currency="usd",
            amount_account_currency=1000,
        )


def test_rejects_non_finite_exposure():
    with pytest.raises(ValidationError):
        CurrencyExposure(
            ticket="1001",
            currency="USD",
            amount_account_currency=float("inf"),
        )


@pytest.mark.parametrize("equity", [0, -1000, float("inf"), float("nan")])
def test_rejects_invalid_current_equity(equity):
    with pytest.raises(ValueError):
        CurrencyExposureCalculator.aggregate(
            exposures=[],
            current_equity=equity,
        )


def test_sorts_currency_results():
    exposures = [
        CurrencyExposure(
            ticket="1001",
            currency="USD",
            amount_account_currency=1000,
        ),
        CurrencyExposure(
            ticket="1002",
            currency="EUR",
            amount_account_currency=2000,
        ),
    ]

    result = CurrencyExposureCalculator.aggregate(
        exposures=exposures,
        current_equity=10000,
    )

    assert list(result.keys()) == ["EUR", "USD"]
