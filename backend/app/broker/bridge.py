from datetime import datetime, timezone
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MT5Heartbeat(BaseModel):
    """Read-only terminal connectivity report from the MT5 bridge."""

    model_config = ConfigDict(extra="forbid")

    server: str = Field(min_length=1, max_length=128)
    terminal_connected: bool
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(timezone.utc)


class MT5AccountSnapshot(BaseModel):
    """Minimal account telemetry; never includes passwords or account login."""

    model_config = ConfigDict(extra="forbid")

    server: str = Field(min_length=1, max_length=128)
    account_currency: str = Field(min_length=3, max_length=8)
    balance: float = Field(ge=0)
    equity: float = Field(ge=0)
    margin: float = Field(ge=0)
    free_margin: float = Field(ge=0)
    leverage: int = Field(gt=0)
    observed_at: datetime

    @field_validator("account_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("balance", "equity", "margin", "free_margin")
    @classmethod
    def require_finite_amounts(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Account amounts must be finite.")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(timezone.utc)


class MT5Quote(BaseModel):
    """A single broker quote received from MT5; it cannot trigger an order."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    timestamp: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("bid", "ask")
    @classmethod
    def require_finite_prices(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Quote prices must be finite.")
        return value

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(timezone.utc)

    @field_validator("ask")
    @classmethod
    def ask_must_be_positive(cls, value: float) -> float:
        return value

    @model_validator(mode="after")
    def validate_spread(self):
        if self.ask < self.bid:
            raise ValueError("Ask price cannot be below bid price.")
        return self



class MT5Candle(BaseModel):
    """One completed or forming OHLC candle received from the read-only MT5 bridge."""

    model_config = ConfigDict(extra="forbid")

    opened_at: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    tick_volume: int = Field(ge=0)

    @field_validator("open", "high", "low", "close")
    @classmethod
    def require_finite_prices(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Candle prices must be finite.")
        return value

    @field_validator("opened_at")
    @classmethod
    def normalize_open_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Candle open time must include a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_ohlc(self):
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high must be the highest OHLC price.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low must be the lowest OHLC price.")
        return self


class MT5CandleBatch(BaseModel):
    """A bounded batch of historical candles for one symbol and timeframe."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=2, max_length=3)
    candles: list[MT5Candle] = Field(min_length=1, max_length=500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
            raise ValueError("Unsupported timeframe.")
        return normalized

    @model_validator(mode="after")
    def validate_unique_candle_times(self):
        times = [candle.opened_at for candle in self.candles]
        if len(times) != len(set(times)):
            raise ValueError("Candle timestamps must be unique within a batch.")
        return self



class MT5CandleBulk(BaseModel):
    """Atomic upload of multiple bounded symbol/timeframe candle batches."""

    model_config = ConfigDict(extra="forbid")

    batches: list[MT5CandleBatch] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_bulk_batches(self):
        keys = [(batch.symbol, batch.timeframe) for batch in self.batches]
        if len(keys) != len(set(keys)):
            raise ValueError("Bulk candle batches must have unique symbol/timeframe pairs.")
        total = sum(len(batch.candles) for batch in self.batches)
        if total > 4000:
            raise ValueError("Bulk candle upload cannot exceed 4000 candles.")
        return self



class MT5SymbolSpecification(BaseModel):
    """Broker-provided contract and volume metadata in the account currency."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    digits: int = Field(ge=0, le=10)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value_profit: float = Field(ge=0)
    tick_value_loss: float = Field(gt=0)
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    stops_level_points: int = Field(ge=0)
    freeze_level_points: int = Field(ge=0)
    trade_allowed: bool
    base_currency: str = Field(min_length=3, max_length=8)
    profit_currency: str = Field(min_length=3, max_length=8)
    margin_currency: str = Field(min_length=3, max_length=8)
    account_currency: str = Field(min_length=3, max_length=8)
    observed_at: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("base_currency", "profit_currency", "margin_currency", "account_currency")
    @classmethod
    def normalize_currencies(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator(
        "point", "tick_size", "tick_value_profit", "tick_value_loss",
        "contract_size", "volume_min", "volume_max", "volume_step",
    )
    @classmethod
    def require_finite_spec_values(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Broker specification values must be finite.")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Specification timestamp must include a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_volume_constraints(self):
        if self.volume_max < self.volume_min or self.volume_step > self.volume_max:
            raise ValueError("Invalid broker volume constraints.")
        return self
