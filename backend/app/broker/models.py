
from pydantic import BaseModel, ConfigDict, Field


class BrokerInstrumentSpecs(BaseModel):
    """
    Trading instrument specifications supplied by the broker.

    Monetary values must be expressed in the account currency
    unless explicitly stated otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    # Instrument identification
    symbol: str = Field(min_length=1)
    base_currency: str = Field(min_length=1)
    quote_currency: str = Field(min_length=1)
    account_currency: str = Field(min_length=1)

    # Price and contract specifications
    contract_size: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value_profit: float = Field(gt=0)
    tick_value_loss: float = Field(gt=0)

    # Volume specifications
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)

    # Market information
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_in_ticks(self) -> float:
        return round(self.spread / self.tick_size, 8)

    @property
    def is_valid_spread(self) -> bool:
        return self.ask >= self.bid

    def validate_volume_limits(self):
        if self.volume_max < self.volume_min:
            raise ValueError(
                "Maximum volume cannot be below minimum volume."
            )

    def validate_market_prices(self):
        if self.ask < self.bid:
            raise ValueError(
                "Ask price cannot be below bid price."
            )
