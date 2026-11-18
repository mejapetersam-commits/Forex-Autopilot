from datetime import datetime, timezone
from math import isfinite
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PriceBar(BaseModel):
    """One completed OHLC price candle. Timestamps must be timezone-aware."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Market-data timestamps must include a timezone.")
        return value.astimezone(timezone.utc)

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def require_finite_numbers(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Market-data values must be finite.")
        return value

    @model_validator(mode="after")
    def validate_ohlc_relationships(self):
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Bar high must be at least open, close and low.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Bar low must be no greater than open, close and high.")
        return self


class MarketDataSeries(BaseModel):
    """Completed candles for one instrument and one timeframe."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=2, max_length=3)
    bars: list[PriceBar] = Field(min_length=2)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Market-data symbol cannot be empty.")
        return value

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
            raise ValueError("Unsupported timeframe.")
        return value

    @model_validator(mode="after")
    def validate_bar_order(self):
        timestamps = [bar.timestamp for bar in self.bars]
        if timestamps != sorted(timestamps):
            raise ValueError("Market-data bars must be in chronological order.")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("Market-data bar timestamps must be unique.")
        return self


class MarketDataProvider(Protocol):
    """Adapter contract implemented by a broker or market-data vendor."""

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> MarketDataSeries:
        """Return completed candles or raise a provider-specific exception."""
        ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
