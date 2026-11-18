
from collections import defaultdict
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CurrencyExposure(BaseModel):
    """
    Represents one currency exposure arising from a single position.

    Positive amount = long currency exposure.
    Negative amount = short currency exposure.

    Amounts must be converted into the account currency
    before being supplied to this model.
    """

    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=1)
    currency: str
    amount_account_currency: float

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.strip()

        if len(value) != 3 or not value.isalpha() or not value.isupper():
            raise ValueError(
                "Currency must be a three-letter uppercase code."
            )

        return value

    @field_validator("amount_account_currency")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Exposure amount must be finite.")

        return value


class CurrencyExposureSummary(BaseModel):
    """Aggregated exposure for one currency."""

    model_config = ConfigDict(extra="forbid")

    currency: str
    net_exposure: float
    gross_exposure: float
    net_exposure_pct_equity: float
    gross_exposure_pct_equity: float


class CurrencyExposureCalculator:
    """
    Aggregates currency exposure across open and proposed positions.

    Net exposure:
        Sum of signed exposures.

    Gross exposure:
        Sum of absolute exposures.

    Gross exposure is useful for concentration limits because
    opposing positions cannot simply cancel each other out.
    """

    @staticmethod
    def aggregate(
        exposures: list[CurrencyExposure],
        current_equity: float,
    ) -> dict[str, CurrencyExposureSummary]:

        if not isfinite(current_equity) or current_equity <= 0:
            raise ValueError("Current equity must be finite and positive.")

        net_totals: dict[str, float] = defaultdict(float)
        gross_totals: dict[str, float] = defaultdict(float)

        for exposure in exposures:
            currency = exposure.currency
            amount = exposure.amount_account_currency

            net_totals[currency] += amount
            gross_totals[currency] += abs(amount)

        summaries = {}

        for currency in sorted(net_totals):
            net = net_totals[currency]
            gross = gross_totals[currency]

            summaries[currency] = CurrencyExposureSummary(
                currency=currency,
                net_exposure=net,
                gross_exposure=gross,
                net_exposure_pct_equity=(net / current_equity) * 100,
                gross_exposure_pct_equity=(gross / current_equity) * 100,
            )

        return summaries
