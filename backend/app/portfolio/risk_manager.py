
from math import isfinite

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.risk.risk_config import RiskConfig
from app.portfolio.currency_exposure import (
    CurrencyExposure,
    CurrencyExposureCalculator,
)


class OpenPositionRisk(BaseModel):
    """
    Risk information for one currently open trading position.

    risk_to_stop represents estimated additional monetary loss
    from the current market price to the stop-loss, including
    estimated transaction costs.

    currency_exposures represents the position's individual
    currency exposures, converted into the account currency.
    """

    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    risk_to_stop: float = Field(gt=0)

    currency_exposures: list[CurrencyExposure] = Field(
        default_factory=list
    )

    @field_validator("risk_to_stop")
    @classmethod
    def validate_finite_risk(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Position risk must be finite.")
        return value


class PortfolioSnapshot(BaseModel):
    """
    Current account and portfolio state supplied by an account adapter.
    """

    model_config = ConfigDict(extra="forbid")

    current_equity: float = Field(gt=0)
    day_start_equity: float = Field(gt=0)
    peak_equity: float = Field(gt=0)

    daily_realized_loss: float = Field(ge=0)
    daily_floating_pnl: float = 0.0

    open_positions: list[OpenPositionRisk] = Field(
        default_factory=list
    )

    emergency_halt: bool = False

    @field_validator(
        "current_equity",
        "day_start_equity",
        "peak_equity",
        "daily_realized_loss",
        "daily_floating_pnl",
    )
    @classmethod
    def validate_finite_amount(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Account amounts must be finite.")
        return value

    @model_validator(mode="after")
    def validate_equity_relationships(self):
        if self.peak_equity < self.current_equity:
            raise ValueError(
                "Peak equity cannot be below current equity."
            )

        if self.peak_equity < self.day_start_equity:
            raise ValueError(
                "Peak equity cannot be below day-start equity."
            )

        tickets = [
            position.ticket for position in self.open_positions
        ]

        if len(tickets) != len(set(tickets)):
            raise ValueError(
                "Open position tickets must be unique."
            )

        return self


class PortfolioRiskDecision(BaseModel):
    """Result of a portfolio-level trade approval check."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reasons: list[str]

    open_position_count: int

    existing_open_risk: float
    proposed_trade_risk: float
    projected_total_open_risk: float

    daily_realized_loss: float
    daily_floating_pnl: float
    actual_daily_loss: float
    projected_daily_loss: float
    daily_loss_limit: float

    current_drawdown_amount: float
    current_drawdown_pct: float

    projected_equity_after_stops: float
    projected_drawdown_amount: float
    projected_drawdown_pct: float

    max_drawdown_pct: float
    per_trade_risk_limit: float

    max_currency_exposure_pct: float
    projected_currency_exposure_pct: dict[str, float]

    emergency_halt: bool


class PortfolioRiskManager:
    """
    Central portfolio-level risk approval engine.

    Evaluates:
    - Emergency trading halt.
    - Maximum open positions.
    - Individual trade risk.
    - Daily loss.
    - Account drawdown.
    - Projected currency concentration.

    It does not connect to a broker or execute trades.

    The caller must supply a current and trustworthy portfolio
    snapshot and, when using currency exposure enforcement,
    the proposed trade's converted currency exposures.
    """

    @staticmethod
    def evaluate_new_trade(
        snapshot: PortfolioSnapshot,
        proposed_trade_risk: float,
        risk_config: RiskConfig,
        proposed_currency_exposures: list[CurrencyExposure] | None = None,
    ) -> PortfolioRiskDecision:

        if not isfinite(proposed_trade_risk):
            raise ValueError(
                "Proposed trade risk must be finite."
            )

        if proposed_trade_risk <= 0:
            raise ValueError(
                "Proposed trade risk must be greater than zero."
            )

        # Calculate existing aggregate open-position risk.
        existing_open_risk = sum(
            position.risk_to_stop
            for position in snapshot.open_positions
        )

        projected_total_open_risk = (
            existing_open_risk + proposed_trade_risk
        )

        # Calculate actual daily loss.
        actual_daily_loss = max(
            0.0,
            snapshot.daily_realized_loss
            - snapshot.daily_floating_pnl,
        )

        daily_loss_limit = (
            snapshot.day_start_equity
            * risk_config.max_daily_loss_pct
            / 100
        )

        projected_daily_loss = (
            actual_daily_loss
            + projected_total_open_risk
        )

        # Calculate maximum permitted individual trade risk.
        per_trade_risk_limit = (
            snapshot.current_equity
            * risk_config.risk_per_trade_pct
            / 100
        )

        # Calculate current account drawdown.
        current_drawdown_amount = (
            snapshot.peak_equity - snapshot.current_equity
        )

        current_drawdown_pct = (
            current_drawdown_amount
            / snapshot.peak_equity
            * 100
        )

        # Project equity if all stops are reached.
        projected_equity_after_stops = (
            snapshot.current_equity
            - projected_total_open_risk
        )

        projected_drawdown_amount = max(
            0.0,
            snapshot.peak_equity
            - projected_equity_after_stops,
        )

        projected_drawdown_pct = (
            projected_drawdown_amount
            / snapshot.peak_equity
            * 100
        )

        # Calculate projected currency concentration.
        projected_currency_exposure_pct = {}

        if proposed_currency_exposures is not None:
            existing_currency_exposures = [
                exposure
                for position in snapshot.open_positions
                for exposure in position.currency_exposures
            ]

            all_currency_exposures = (
                existing_currency_exposures
                + proposed_currency_exposures
            )

            exposure_summary = CurrencyExposureCalculator.aggregate(
                exposures=all_currency_exposures,
                current_equity=snapshot.current_equity,
            )

            for currency, summary in exposure_summary.items():
                projected_currency_exposure_pct[currency] = (
                    summary.gross_exposure_pct_equity
                )

        reasons = []

        # Emergency halt.
        if snapshot.emergency_halt:
            reasons.append(
                "Emergency trading halt is active."
            )

        # Maximum simultaneous positions.
        if (
            len(snapshot.open_positions)
            >= risk_config.max_open_positions
        ):
            reasons.append(
                "Maximum open position limit has been reached."
            )

        # Individual trade risk.
        if proposed_trade_risk > per_trade_risk_limit:
            reasons.append(
                "Proposed trade exceeds the per-trade risk limit."
            )

        # Projected daily loss limit.
        if projected_daily_loss > daily_loss_limit:
            reasons.append(
                "Projected daily loss would exceed the daily loss limit."
            )

        # Existing daily loss limit breach.
        if actual_daily_loss >= daily_loss_limit:
            reasons.append(
                "Daily loss limit has already been reached."
            )

        # Current account drawdown.
        if current_drawdown_pct >= risk_config.max_drawdown_pct:
            reasons.append(
                "Maximum account drawdown limit has been reached."
            )

        # Projected account drawdown.
        if projected_drawdown_pct >= risk_config.max_drawdown_pct:
            reasons.append(
                "Projected account drawdown would reach or exceed "
                "the maximum drawdown limit."
            )

        # Currency exposure limit.
        for currency, exposure_pct in (
            projected_currency_exposure_pct.items()
        ):
            if (
                exposure_pct
                > risk_config.max_currency_exposure_pct
            ):
                reasons.append(
                    f"Projected gross {currency} exposure of "
                    f"{exposure_pct:.2f}% exceeds the configured "
                    f"currency exposure limit of "
                    f"{risk_config.max_currency_exposure_pct:.2f}%."
                )

        approved = len(reasons) == 0

        if approved:
            reasons.append(
                "Trade approved by portfolio risk manager."
            )

        return PortfolioRiskDecision(
            approved=approved,
            reasons=reasons,
            open_position_count=len(snapshot.open_positions),
            existing_open_risk=existing_open_risk,
            proposed_trade_risk=proposed_trade_risk,
            projected_total_open_risk=projected_total_open_risk,
            daily_realized_loss=snapshot.daily_realized_loss,
            daily_floating_pnl=snapshot.daily_floating_pnl,
            actual_daily_loss=actual_daily_loss,
            projected_daily_loss=projected_daily_loss,
            daily_loss_limit=daily_loss_limit,
            current_drawdown_amount=current_drawdown_amount,
            current_drawdown_pct=current_drawdown_pct,
            projected_equity_after_stops=projected_equity_after_stops,
            projected_drawdown_amount=projected_drawdown_amount,
            projected_drawdown_pct=projected_drawdown_pct,
            max_drawdown_pct=risk_config.max_drawdown_pct,
            per_trade_risk_limit=per_trade_risk_limit,
            max_currency_exposure_pct=(
                risk_config.max_currency_exposure_pct
            ),
            projected_currency_exposure_pct=(
                projected_currency_exposure_pct
            ),
            emergency_halt=snapshot.emergency_halt,
        )
