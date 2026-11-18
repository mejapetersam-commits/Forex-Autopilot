from datetime import datetime, timezone
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    def validate_spread(self) -> None:
        if self.ask < self.bid:
            raise ValueError("Ask price cannot be below bid price.")
