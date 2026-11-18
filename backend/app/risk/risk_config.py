
from pydantic import BaseModel, Field, ConfigDict, model_validator


class RiskConfig(BaseModel):
    """
    Configurable risk settings for FOREX AUTOPILOT.

    These are initial demo defaults, not live-trading authorisation.
    """

    model_config = ConfigDict(extra="forbid")

    # Risk limits
    risk_per_trade_pct: float = Field(default=0.25, gt=0, le=1.0)
    max_daily_loss_pct: float = Field(default=1.0, gt=0, le=3.0)
    max_drawdown_pct: float = Field(default=5.0, gt=0, le=10.0)

    # Currency concentration limits
    max_currency_exposure_pct: float = Field(
        default=200.0,
        gt=0,
        le=1000.0,
    )

    # Position limits
    max_open_positions: int = Field(default=2, ge=1, le=10)

    # Correlation controls. Kept disabled until a live market-data
    # adapter supplies timestamp-aligned historical returns.
    correlation_check_enabled: bool = False
    correlation_threshold: float = Field(default=0.80, gt=0, le=1)
    max_correlated_group_risk_pct: float = Field(default=0.50, gt=0, le=3.0)

    # Trading safeguards
    require_stop_loss: bool = True
    allow_martingale: bool = False
    allow_grid_trading: bool = False
    trading_enabled: bool = False

    @model_validator(mode="after")
    def validate_risk_relationships(self):
        if self.risk_per_trade_pct > self.max_daily_loss_pct:
            raise ValueError(
                "Risk per trade cannot exceed the daily loss limit."
            )

        if self.max_daily_loss_pct > self.max_drawdown_pct:
            raise ValueError(
                "Daily loss limit cannot exceed maximum drawdown."
            )

        if self.allow_martingale or self.allow_grid_trading:
            raise ValueError(
                "Martingale and grid trading are prohibited."
            )

        if not self.require_stop_loss:
            raise ValueError("A mandatory stop-loss is required.")

        return self
